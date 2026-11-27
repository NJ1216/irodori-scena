from __future__ import annotations

import scena_test_isolation  # noqa: F401
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules.llm_contracts import LlmRecordContract, extract_complete_records, merge_record_fields
from server.modules.draft_packets import extract_required_sources


class JsonOffsetAcceptanceTests(unittest.TestCase):
    def test_each_decoder_receives_the_original_string_and_an_offset(self):
        inputs = [
            (extract_complete_records, '{"records":[{"owner":"A"},{"owner":"B"}]}', ()),
            (extract_required_sources, '{"D1.1":{"lines":[{"text":"保持"}]} }', (['D1.1'],)),
        ]
        original = json.JSONDecoder.raw_decode
        for extract, content, arguments in inputs:
            calls = []

            def counted(decoder, source, idx=0):
                self.assertIs(source, content)
                calls.append(idx)
                return original(decoder, source, idx)

            with self.subTest(extractor=extract.__name__), patch.object(json.JSONDecoder, 'raw_decode', counted):
                extract(content, *arguments)
            self.assertGreater(len(calls), 1)
            self.assertEqual(calls, sorted(calls))
            self.assertGreater(calls[0], 0)

    def test_frozen_record_acceptance_partial_and_manifest(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/llm-offset-acceptance.json').read_text())
        contract = LlmRecordContract('offset-fixture', 1, fixture['schema'], 'owner', frozenset({'A', 'B'}))
        for case in fixture['records']:
            with self.subTest(content=case['content']):
                records, partial = extract_complete_records(case['content'])
                self.assertEqual(records, case['records'])
                self.assertEqual(partial, case['partial'])
                accepted, manifest = merge_record_fields(records, contract)
                self.assertEqual(accepted, case['accepted'])
                self.assertEqual(manifest, case['manifest'])

    def test_frozen_source_ownership_and_partial_results(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/llm-offset-acceptance.json').read_text())
        for case in fixture['sources']:
            with self.subTest(content=case['content']):
                self.assertEqual(extract_required_sources(case['content'], ['D1.1', 'D1.2']),
                                 (case['records'], case['partial']))

    def test_record_limits_preserve_exception_types_and_messages(self):
        cases = [
            ('{"records":[' + ','.join(['{}'] * 2049) + ']}', 'LLM record count limit exceeded'),
            (json.dumps({'records': [{'text': 'a' * 1_048_576}]}), 'LLM record size limit exceeded'),
            ('{"records":[{"value":' + '[' * 33 + '0' + ']' * 33 + '}]}',
             'LLM record nesting limit exceeded'),
        ]
        for content, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                extract_complete_records(content)
