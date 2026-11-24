#!/usr/bin/env python3
"""Optional addon worker. No network, transcript forcing, or app imports."""
import argparse
import hashlib
import json
import sys
import time
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import onnxruntime as ort

from evaluate_japanese_lipsync import LABELS, read_wav
from lipsync_ctc_probe import recognize
from lipsync_japanese_pipeline import ANALYSIS_VERSION, COMMON_ANALYSIS_VERSION, refine_japanese
from lipsync_model_profile import COMMON_MODEL_SHA256, V3_MODEL_SHA256, common_execution, model_hash

MODEL_SHA256 = V3_MODEL_SHA256
MAX_PARALLEL_REQUESTS = 4


def analysis_version(model_sha):
    return COMMON_ANALYSIS_VERSION if model_sha == COMMON_MODEL_SHA256 else ANALYSIS_VERSION


def execution_identity(*, threads=2, spinning=True, provider='CPUExecutionProvider', mode='baseline', model_sha=MODEL_SHA256):
    settings = {'runtime': 'onnxruntime', 'runtimeVersion': ort.__version__, 'provider': provider,
                'intraThreads': threads, 'interThreads': 1, 'spinning': spinning,
                'preprocessing': 'resample-normalize-float32-v1', 'mode': mode}
    settings.update(common_execution(model_sha, Path(ort.__file__).parent, threads=threads, provider=provider))
    if sys.platform == 'win32':
        from lipsync_runtime_identity import windows_runtime_identity
        settings.update(windows_runtime_identity(Path(ort.__file__).parent, ort.__version__))
    return settings, hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()


def processor_identity(model_dir):
    files = {name: hashlib.sha256((model_dir / name).read_bytes()).hexdigest()
             for name in ('vocab.json', 'config.json', 'preprocessor_config.json')}
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def validate_rows(rows, duration):
    cursor = 0
    output = []
    for start, end, label in rows:
        if (type(start) is not int or type(end) is not int or start != cursor
                or end <= start or label not in LABELS):
            raise ValueError('Invalid or discontinuous LAB')
        output.append((start, end, label))
        cursor = end
    if not output or cursor != round(duration * 1e7):
        raise ValueError('LAB does not cover WAV exactly')
    return output


def load_recognizer(model_dir, *, threads=2, spinning=True, diagnostic_mode=None,
                    cache=True, provider='CPUExecutionProvider', profile=None, collect_diagnostics=True):
    model = model_dir / 'model_quantized.onnx'
    actual_model_sha = model_hash(model_dir)
    settings = [json.loads((model_dir / name).read_text(encoding='utf-8')) for name in
                ('vocab.json', 'config.json', 'preprocessor_config.json')]
    execution = execution_identity(threads=threads, spinning=spinning, provider=provider,
                                   mode=diagnostic_mode or 'baseline', model_sha=actual_model_sha)
    options = ort.SessionOptions()
    options.intra_op_num_threads, options.inter_op_num_threads = threads, 1
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.add_session_config_entry('session.intra_op.allow_spinning', str(int(spinning)))
    options.add_session_config_entry('session.inter_op.allow_spinning', str(int(spinning)))
    for name, value in execution[0].get('runtimeSessionOptions', {}).items():
        options.add_session_config_entry(name, value)
    if profile:
        options.enable_profiling = True
        options.profile_file_prefix = str(profile)
    if provider not in ort.get_available_providers():
        raise ValueError('Requested execution provider unavailable')
    started = time.perf_counter()
    session = ort.InferenceSession(str(model), options, providers=[provider] if provider == 'CPUExecutionProvider'
                                  else [provider, 'CPUExecutionProvider'])
    loaded = time.perf_counter() - started
    if diagnostic_mode:
        from lipsync_inference_diagnostics import CandidateRecognizer, DiagnosticRecognizer
        identity = {'modelSha256': actual_model_sha, 'processorSha256': processor_identity(model_dir),
                    'runtime': ort.__version__, 'providers': session.get_providers(),
                    'intraThreads': threads, 'interThreads': 1, 'spinning': spinning,
                    'preprocessing': 'resample-normalize-float32-v1', 'mode': diagnostic_mode}
        if sys.platform == 'win32':
            identity['executionSha256'] = execution[1]
        implementation = DiagnosticRecognizer if collect_diagnostics else CandidateRecognizer
        result = implementation(session, settings, identity, mode=diagnostic_mode, cache=cache)
        result.load_seconds = loaded
        result.execution_identity = execution
        result.model_sha256 = actual_model_sha
        return result

    def recognizer(audio, rate):
        return recognize(session, audio, rate, *settings, with_frames=True)

    recognizer.execution_identity = execution
    recognizer.model_sha256 = actual_model_sha
    return recognizer


def process(request, recognizer):
    wav = Path(request['wavPath'])
    if hashlib.sha256(wav.read_bytes()).hexdigest() != request['wavSha256']:
        raise ValueError('WAV changed')
    audio, rate = read_wav(wav)
    before = validate_rows(request['rows'], len(audio) / rate)
    if hasattr(recognizer, 'clear'):
        recognizer.clear()
        recognizer.calls.clear()
        recognizer.stages.clear()
    model_sha = getattr(recognizer, 'model_sha256', MODEL_SHA256)
    try:
        after, audit = refine_japanese(before, audio, rate, recognizer,
                                      confirm_vowels=model_sha == COMMON_MODEL_SHA256)
    finally:
        if hasattr(recognizer, 'clear'):
            recognizer.clear()
    after = validate_rows(after, len(audio) / rate)
    result = {'schemaVersion': 1, 'wavSha256': request['wavSha256'], 'rows': after,
            'analysisVersion': analysis_version(model_sha), 'modelSha256': model_sha,
            'textInfluence': 'none'}
    if hasattr(recognizer, 'execution_identity'):
        result['execution'], result['executionSha256'] = recognizer.execution_identity
    if request.get('diagnostics'):
        result['audit'] = audit
        if hasattr(recognizer, 'calls'):
            result['calls'], result['stages'] = recognizer.calls, recognizer.stages
    return result


def atomic_json(path, payload):
    temporary = path.with_suffix('.pending')
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def serve(directory, recognizer, processor_sha, *, recognizer_factory=None, workers=MAX_PARALLEL_REQUESTS,
          execution=None, model_sha=MODEL_SHA256):
    identity = {'analysisVersion': analysis_version(model_sha), 'modelSha256': model_sha,
                'processorSha256': processor_sha, 'textInfluence': 'none'}
    if execution:
        identity['execution'], identity['executionSha256'] = execution
    atomic_json(directory / 'ready.json', identity)
    local = threading.local()

    def handle_request(request):
        if not hasattr(local, 'recognizer'):
            local.recognizer = recognizer_factory() if recognizer_factory else recognizer
        return serve_request(request, local.recognizer, processor_sha)
    pending = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        while not (directory / 'stop').exists():
            for path, future in list(pending.items()):
                if future.done():
                    future.result()
                    del pending[path]
            requests = [p for p in sorted(directory.glob('*.request.json')) if p not in pending]
            for request in requests[:workers - len(pending)]:
                pending[request] = executor.submit(handle_request, request)
            time.sleep(.02)


def serve_request(request, recognizer, processor_sha):
    try:
        result = process(json.loads(request.read_text(encoding='utf-8')), recognizer)
        result['processorSha256'] = processor_sha
    except Exception as error:
        # Failed rows cannot erase successful siblings or poison the model.
        result = {'error': type(error).__name__}
    output = request.parent / request.name.replace('.request.json', '.result.json')
    atomic_json(output, result)
    request.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--ctc-workers', type=int, choices=(1, 2, 4), default=4)
    parser.add_argument('--spinning', type=int, choices=(0, 1), default=1)
    parser.add_argument('--candidate', choices=('baseline', 'lazy', 'prepared'), default='baseline')
    parser.add_argument('--diagnostics', action='store_true', help='Collect inference traces for diagnostic requests')
    args = parser.parse_args()
    # Model assets live beside the addon executable, never in an arbitrary user path.
    root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
    actual_model_sha = model_hash(root / 'model')
    if args.self_test:
        import numpy as np
        recognizer = load_recognizer(root / 'model')
        recognizer(np.zeros(16000, dtype=np.float32), 16000)
        execution, execution_sha = recognizer.execution_identity
        print(json.dumps({'analysisVersion': analysis_version(actual_model_sha), 'modelSha256': actual_model_sha,
                          'processorSha256': processor_identity(root / 'model'), 'textInfluence': 'none',
                          'execution': execution, 'executionSha256': execution_sha}))
        return
    if args.serve:
        if not args.directory or args.input or args.output:
            parser.error('Serve mode needs only --directory')
        serve(args.directory, None, processor_identity(root / 'model'), workers=args.ctc_workers,
              execution=execution_identity(spinning=bool(args.spinning), mode=args.candidate, model_sha=actual_model_sha), model_sha=actual_model_sha,
              recognizer_factory=lambda: load_recognizer(root / 'model', spinning=bool(args.spinning),
                                                        diagnostic_mode=args.candidate if args.candidate != 'baseline' or args.diagnostics
                                                        else None, collect_diagnostics=args.diagnostics))
        return
    if not args.input or not args.output or args.directory:
        parser.error('Single mode needs --input and --output')
    result = process(json.loads(args.input.read_text(encoding='utf-8')),
                     load_recognizer(root / 'model', spinning=bool(args.spinning),
                                     diagnostic_mode=args.candidate if args.candidate != 'baseline' or args.diagnostics else None,
                                     collect_diagnostics=args.diagnostics))
    result['processorSha256'] = processor_identity(root / 'model')
    args.output.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
