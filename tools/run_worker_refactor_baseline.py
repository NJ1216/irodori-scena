#!/usr/bin/env python3
"""Compare SCENA worker exchanges using fixed assets and A/B/C reference WAVs.

Run once for each checkout with separate output directories. The second run
must use the first run's no-reference directory as --reference-dir. No app,
server, project file, model setting, or upstream checkout is modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, required=True)
    parser.add_argument('--asset-registry', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--reference-dir', type=Path)
    return parser.parse_args()


class RecordingInput:
    def __init__(self, stream, requests):
        self.stream, self.requests = stream, requests

    def write(self, text):
        self.requests.append(json.loads(text))
        return self.stream.write(text)

    def flush(self):
        return self.stream.flush()

    def close(self):
        return self.stream.close()


def run(args):
    checkout = args.checkout.resolve()
    destination = args.output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    os.environ['SCENA_DATA_ROOT'] = str(destination / 'data')
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.path.insert(0, str(checkout))
    import server.app  # noqa: F401
    from server.modules import inference, tts_registry

    registry = json.loads(args.asset_registry.read_text())
    engine = next(item for item in registry['engines'] if item['id'] == registry['defaultEngineId'])
    model = next(item for item in registry['models'] if item['id'] == registry['defaultModelId'])
    model = {**model, 'tokenizerPath': str(Path(model['path']) / 'tokenizer')}
    fixture = json.loads((checkout / 'tests/inference/dialogue-context-fixture.json').read_text())
    report = {
        'commit': subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip(),
        'python': platform.python_version(), 'platform': platform.platform(),
        'engineCommit': engine['commit'], 'modelRevision': model['revision'],
        'codecRevision': model['codecRevision'], 'fixture': fixture, 'requests': [], 'results': [],
    }
    original_worker = inference.inference_worker_locked

    def worker_with_recording(path):
        worker = original_worker(path)
        if not isinstance(worker.stdin, RecordingInput):
            worker.stdin = RecordingInput(worker.stdin, report['requests'])
        return worker

    def generate(name, text, caption, seed, reference=None):
        output = destination / name
        started = time.monotonic()
        inference.run_irodori(text=text, caption=caption, output=output, seed=seed,
                             ref_wav=reference, quality='fast',
                             generation_settings={'steps': 16, 'speechRate': 1.0,
                                                  'textCfg': 3.0, 'voiceCfg': 5.0, 'captionCfg': 3.0})
        result = {'name': name, 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
                  'bytes': output.stat().st_size, 'elapsedSeconds': time.monotonic() - started,
                  'execution': inference.last_inference_execution(),
                  'referenceSha256': hashlib.sha256(reference.read_bytes()).hexdigest() if reference else None}
        report['results'].append(result)
        (destination / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'name': name, 'sha256': result['sha256'], 'seconds': result['elapsedSeconds']}), flush=True)

    with patch.object(tts_registry, 'selected_tts_runtime', return_value={'engine': engine, 'model': model}), \
            patch.object(inference, 'inference_worker_locked', side_effect=worker_with_recording):
        try:
            inference.prepare_irodori_worker()
            for speaker in fixture['speakers']:
                generate(f"no-reference/{speaker['id']}.wav", speaker['reference_text'],
                         speaker['reference_caption'], speaker['seed'])
            references = args.reference_dir.resolve() if args.reference_dir else destination / 'no-reference'
            speakers = {item['id']: item for item in fixture['speakers']}
            first = fixture['dialogue'][0]
            generate('reference/A.wav', first['text'], None, speakers['A']['seed'], references / 'A.wav')
            for index, line in enumerate(fixture['dialogue']):
                speaker = speakers[line['speaker']]
                generate(f"dialogue/{line['id']}-{line['speaker']}.wav", line['text'],
                         fixture['scene_context'] + '\n' + line['stage_direction'],
                         speaker['seed'] + index, references / f"{speaker['id']}.wav")
        finally:
            inference.shutdown_inference_worker()
    return 0


if __name__ == '__main__':
    raise SystemExit(run(parse_args()))
