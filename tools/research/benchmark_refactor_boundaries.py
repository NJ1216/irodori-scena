#!/usr/bin/env python3
"""Measure fixed parser/cast fixtures; run in a fresh process for each checkout."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch


def median_ms(action, repetitions=31):
    samples = []
    for _ in range(repetitions):
        started = time.perf_counter()
        action()
        samples.append((time.perf_counter() - started) * 1000)
    return statistics.median(samples)


def measure(checkout, root):
    os.environ['SCENA_DATA_ROOT'] = str(root)
    sys.path.insert(0, str(checkout.resolve()))
    import server.app  # noqa: F401
    from server.modules import cast_sync, constants, llm_contracts, project_repository

    content = json.dumps({'records': [{'owner': f'A{index:04}', 'text': '固定の本文と検査条件を保持します。'}
                                      for index in range(1024)]}, ensure_ascii=False)
    decoder_calls = []
    original = json.JSONDecoder.raw_decode

    def counted(decoder, text, idx=0):
        decoder_calls.append((text is content, len(text), idx))
        return original(decoder, text, idx)

    with patch.object(json.JSONDecoder, 'raw_decode', counted):
        records, partial = llm_contracts.extract_complete_records(content)
    result = {'parser': {'inputChars': len(content), 'inputSha256': hashlib.sha256(content.encode()).hexdigest(),
                         'records': len(records), 'partial': partial,
                         'decoderCalls': len(decoder_calls),
                         'originalStringCalls': sum(item[0] for item in decoder_calls),
                         'copiedChars': sum(item[1] for item in decoder_calls if not item[0]),
                         'medianMs': median_ms(lambda: llm_contracts.extract_complete_records(content))}}
    characters = [{'id': f'cast-{index}', 'name': f'cast {index}', 'audioHash': str(index)}
                  for index in range(100)]
    library = root / 'global-characters.json'
    library.write_text(json.dumps(characters, ensure_ascii=False))
    project = {'characters': [{**item, 'name': 'old', 'scope': 'project'} for item in characters]}
    with patch.object(constants, 'GLOBAL_CHARACTERS_FILE', library), \
            patch('server.modules.workspace.ensure_data_root'):
        original_read = project_repository.read_global_characters
        with patch.object(project_repository, 'read_global_characters', wraps=original_read) as read:
            candidates = cast_sync.global_cast_update_candidates(project)
            reads = read.call_count
        result['cast'] = {'characters': 100, 'candidates': len(candidates), 'libraryReads': reads,
                          'fixtureSha256': hashlib.sha256(library.read_bytes()).hexdigest(),
                          'medianMs': median_ms(lambda: cast_sync.global_cast_update_candidates(project))}
    result['maxRssBytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result['python'] = sys.version
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='scena-rf-benchmark-') as directory:
        print(json.dumps(measure(args.checkout, Path(directory)), indent=2))
