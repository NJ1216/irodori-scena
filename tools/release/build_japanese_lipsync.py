"""Build a local review worker; never download models or publish an archive."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from packaging.requirements import Requirement

from tools.release.license_sources import distribution_licenses

ROOT = Path(__file__).resolve().parents[2]
MODEL_IDENTITY = Path(__file__).with_name('japanese-lipsync-model.json')
EXCLUDED = ('torch', 'transformers', 'tensorflow', 'matplotlib', 'pandas', 'PIL', 'pytest', 'IPython')
WINDOWS_PYTHON = (3, 12, 13)


def verify_build_python(platform_name, version):
    # 3.13.12 failed in dis._unpack_opargs during native Windows modulegraph analysis.
    if platform_name == 'win32' and tuple(version[:3]) != WINDOWS_PYTHON:
        raise ValueError('Windows Japanese worker requires Python 3.12.13')


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def profile_build_args(profile):
    if profile == 'v3':
        return []
    if profile != 'common-v4':
        raise ValueError('Unknown worker model profile')
    # Native workers otherwise failed with PackageNotFoundError. Windows also
    # hit the optional setuptools hook with a None version; neither build-time
    # setuptools nor pkg_resources is used by this inference worker.
    return ([part for name in ('onnxruntime', 'numpy', 'scipy') for part in ('--copy-metadata', name)]
            + ['--exclude-module', 'setuptools', '--exclude-module', 'pkg_resources'])


def packaged_execution(executable, identity):
    probe = json.loads(subprocess.check_output([str(executable), '--self-test'], timeout=120))
    execution = probe['execution']
    digest = hashlib.sha256(json.dumps(execution, sort_keys=True).encode()).hexdigest()
    if (probe['modelSha256'] != identity['files']['model_quantized.onnx']
            or execution.get('modelExecutionProfile') != identity['executionProfile']
            or probe['executionSha256'] != digest):
        raise ValueError('Packaged new worker execution identity differs')
    return execution, digest


def copy_model(source, target, *, profile='v3'):
    identity_path = MODEL_IDENTITY if profile == 'v3' else MODEL_IDENTITY.with_name('japanese-lipsync-common-model.json')
    if profile not in ('v3', 'common-v4'):
        raise ValueError('Unknown worker model profile')
    identity = json.loads(identity_path.read_text(encoding='utf-8'))
    for name, expected in identity['files'].items():
        if sha256(source / name) != expected:
            raise ValueError('Accepted model/settings hash mismatch: ' + name)
    target.mkdir()
    for name in identity['files']:
        shutil.copyfile(source / name, target / name)
    return identity


def dependency_notices(target):
    pending, seen, inventory = ['numpy', 'scipy', 'onnxruntime', 'pyinstaller', 'cffi',
                                'charset-normalizer', 'pyyaml', 'psutil'], set(), []
    target.mkdir()
    while pending:
        name = pending.pop()
        distribution = importlib.metadata.distribution(name)
        name = distribution.metadata['Name'].lower()
        if name in seen:
            continue
        seen.add(name)
        texts = distribution_licenses(distribution)
        supplement = MODEL_IDENTITY.parent / 'japanese-lipsync-notices' / f'{name}-{distribution.version}.txt'
        if not texts and supplement.is_file():
            texts = [(supplement.name, supplement.read_text(encoding='utf-8'))]
        text = '\n\n'.join(f'{file}\n{content}' for file, content in texts)
        if not texts:
            text = 'Redistribution review pending: installed distribution has no license text.\n'
        (target / (name + '.txt')).write_text(text, encoding='utf-8')
        inventory.append({'name': name, 'version': distribution.version, 'notice': name + '.txt',
                          'noticeComplete': bool(texts)})
        for raw in distribution.requires or []:
            requirement = Requirement(raw)
            if requirement.marker is None or requirement.marker.evaluate({'extra': ''}):
                pending.append(requirement.name)
    (target / 'inventory.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    return inventory


def runtime_notices(target, *, profile='v3'):
    for file in (MODEL_IDENTITY.parent / 'japanese-lipsync-notices').iterdir():
        shutil.copyfile(file, target / file.name)
    if profile == 'common-v4':
        shutil.copyfile(MODEL_IDENTITY.with_name('japanese-lipsync-common-notice.md'), target / 'MODEL-NOTICE.md')
    shutil.copyfile(ROOT / 'LICENSE', target / 'SCENA-MIT.txt')
    candidates = [Path(sys.base_prefix) / 'LICENSE.txt',
                  Path(sys.base_prefix) / f'lib/python{sys.version_info.major}.{sys.version_info.minor}/LICENSE.txt']
    license_path = next((p for p in candidates if p.is_file()), None)
    if license_path is None:
        raise ValueError('Python redistribution license text is missing')
    shutil.copyfile(license_path, target / 'Python-LICENSE.txt')


def finalize(root, model_dir, *, profile='v3'):
    sys.path.insert(0, str(ROOT / 'tools'))
    from tools.japanese_lipsync_worker import execution_identity, processor_identity
    identity = copy_model(model_dir, root / 'model', profile=profile)
    inventory = dependency_notices(root / 'licenses')
    runtime_notices(root / 'licenses', profile=profile)
    (root / 'MODEL-PROVENANCE.json').write_text(json.dumps(identity, indent=2), encoding='utf-8')
    executable = root / ('japanese-lipsync-worker.exe' if sys.platform == 'win32' else 'japanese-lipsync-worker')
    execution, execution_sha = execution_identity(model_sha=identity['files']['model_quantized.onnx'])
    if profile == 'common-v4':
        execution, execution_sha = packaged_execution(executable, identity)
    manifest = {'schemaVersion': 1, 'enabled': True, 'analysisVersion': identity['analysisVersion'],
                'modelSha256': identity['files']['model_quantized.onnx'],
                'processorSha256': processor_identity(root / 'model'), 'textInfluence': 'none',
                'executable': executable.name, 'executableSha256': sha256(executable),
                'execution': execution, 'executionSha256': execution_sha,
                'platform': platform.system() + '-' + platform.machine(),
                'pythonVersion': platform.python_version(),
                'dependencies': inventory, 'publicationReview': identity['publicationReview'],
                'publicationReady': profile == 'v3' and all(x['noticeComplete'] for x in inventory),
                'licenseNoticesComplete': all(x['noticeComplete'] for x in inventory),
                'qualityReview': 'previous-reviewed' if profile == 'v3' else 'pending',
                'files': {p.relative_to(root).as_posix(): sha256(p)
                          for p in sorted(root.rglob('*')) if p.is_file()}}
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return root


def main():
    verify_build_python(sys.platform, sys.version_info)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--profile', choices=('v3', 'common-v4'), default='v3')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error('Use a new output directory')
    output.mkdir(parents=True)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir',
               '--name', 'japanese-lipsync-worker', '--distpath', str(output / 'dist'),
               '--workpath', str(output / 'build'), '--specpath', str(output),
               '--paths', str(ROOT / 'tools')]
    command += profile_build_args(args.profile)
    for name in EXCLUDED:
        command += ['--exclude-module', name]
    if sys.platform == 'win32':
        import onnxruntime
        runtime_metadata = Path(onnxruntime.__file__).parent / 'scena-runtime.json'
        if runtime_metadata.is_file():
            command += ['--add-data', str(runtime_metadata) + os.pathsep + 'onnxruntime']
    command.append(str(ROOT / 'tools/japanese_lipsync_worker.py'))
    environment = {**os.environ, 'PYINSTALLER_CONFIG_DIR': str(output / 'cache')}
    subprocess.run(command, check=True, cwd=ROOT, env=environment)
    root = finalize(output / 'dist/japanese-lipsync-worker', args.model_dir.resolve(), profile=args.profile)
    print(json.dumps({'workerRoot': str(root), 'publicationReady':
                      json.loads((root / 'manifest.json').read_text())['publicationReady']}))


if __name__ == '__main__':
    main()
