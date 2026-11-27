from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules import llm_completion_service
from server.modules import llm_registry_metadata
from server.modules.llm_contracts import LlmRecordContract, extract_complete_records, merge_record_fields


class LlmContractTests(unittest.TestCase):
    def test_ollama_uses_native_structured_output_before_capability_probe(self):
        request = SimpleNamespace(provider='ollama', base_url='http://127.0.0.1:11434/v1', model='gemma4:12b')
        with patch.object(llm_registry_metadata, 'resolve_llm_capabilities') as capabilities:
            self.assertTrue(llm_completion_service._schema_enabled(request, stream=True))
            self.assertTrue(llm_completion_service._schema_enabled(request, stream=False))
        capabilities.assert_not_called()

    def test_operator_can_disable_ollama_structured_output(self):
        request = SimpleNamespace(provider='ollama', base_url='http://127.0.0.1:11434/v1', model='gemma4:12b')
        with patch.dict('os.environ', {'SCENA_DISABLE_STRUCTURED_OUTPUT': '1'}):
            self.assertFalse(llm_completion_service._schema_enabled(request, stream=True))

    def contract(self):
        return LlmRecordContract("fixture", 1, {
            "type": "object", "additionalProperties": False,
            "properties": {
                "owner": {"type": "string", "enum": ["A", "B"]},
                "text": {"type": ["string", "null"]},
                "rate": {"type": ["integer", "null"]},
            }, "required": ["owner", "text", "rate"],
        }, "owner", frozenset({"A", "B"}))

    def test_extracts_complete_prefix_from_truncated_json(self):
        content = 'thinking\n```json\n{"records":[{"owner":"A","text":"a } \\\" quote","rate":1},{"owner":"B","text":"途中'
        records, partial = extract_complete_records(content)
        self.assertEqual(records, [{"owner": "A", "text": 'a } " quote', "rate": 1}])
        self.assertTrue(partial)

    def test_malformed_or_non_object_record_does_not_hide_later_valid_siblings(self):
        for middle in ('{"field":"X","value":}', '"stray"', '42'):
            with self.subTest(middle=middle):
                content = '{"records":[{"owner":"A"},' + middle + ',{"owner":"B"}]}'
                records, _ = extract_complete_records(content)
                self.assertEqual(records, [{"owner": "A"}, {"owner": "B"}])

    def test_truncated_trailing_record_keeps_preceding_valid_records(self):
        records, partial = extract_complete_records('{"records":[{"owner":"A"},"stray",{"owner":"B"},{"owner":"C","te')
        self.assertEqual(records, [{"owner": "A"}, {"owner": "B"}])
        self.assertTrue(partial)

    def test_uses_only_root_records_key(self):
        content = ('{"meta":{"records":[{"owner":"B","text":"nested"}]},'
                   '"records":[{"owner":"A","text":"root"}]}')
        records, partial = extract_complete_records(content)
        self.assertEqual(records, [{"owner": "A", "text": "root"}])
        self.assertFalse(partial)

    def test_keeps_valid_siblings_and_drops_unknown_fields(self):
        records, manifest = merge_record_fields([
            {"owner": "A", "text": "usable", "rate": "bad", "unknown": 1},
        ], self.contract())
        self.assertEqual(records, [{"owner": "A", "text": "usable"}])
        self.assertEqual({item.get("reason") for item in manifest if item["status"] == "rejected"},
                         {"invalid_field", "unknown_field"})

    def test_conflict_rejects_only_conflicting_field(self):
        records, _ = merge_record_fields([
            {"owner": "A", "text": "one", "rate": 1},
            {"owner": "A", "text": "two", "rate": 1},
        ], self.contract())
        self.assertEqual(records, [{"owner": "A", "rate": 1}])

    def test_unknown_owner_does_not_remove_valid_record(self):
        records, _ = merge_record_fields([
            {"owner": "X", "text": "bad"}, {"owner": "B", "text": "good"},
        ], self.contract())
        self.assertEqual(records, [{"owner": "B", "text": "good"}])

    def test_nested_schema_failure_rejects_only_that_field(self):
        contract = LlmRecordContract("nested", 1, {
            "type": "object", "additionalProperties": False,
            "properties": {
                "owner": {"type": "string", "enum": ["A"]},
                "text": {"type": "string"},
                "items": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "properties": {"name": {"type": "string"}}, "required": ["name"],
                }},
            }, "required": ["owner", "text", "items"],
        }, "owner", frozenset({"A"}))
        records, manifest = merge_record_fields([
            {"owner": "A", "text": "usable", "items": [{"name": 42}]},
        ], contract)
        self.assertEqual(records, [{"owner": "A", "text": "usable"}])
        self.assertIn("invalid_field", {item.get("reason") for item in manifest})

    def test_unenforced_warning_downgrades_without_replay_and_keeps_body(self):
        request = SimpleNamespace(provider="scena-local", base_url="http://local/v1", model="gemma")
        payload = {
            "choices": [{"message": {"content": '{"records":[{"owner":"A","text":"kept"}]}'}}],
            "_transport_headers": {"warning": 'response_format is not enforced'},
        }
        states = []
        with (
            patch.object(llm_completion_service, "_schema_enabled", return_value=True),
            patch.object(llm_completion_service, "_structured_content",
                         return_value=(payload["choices"][0]["message"]["content"], payload)),
            patch.object(llm_registry_metadata, "set_structured_output_state",
                         side_effect=lambda *args, **kwargs: states.append(kwargs)),
        ):
            result = llm_completion_service.complete_records(
                request, contract=self.contract(), system="meaning", user={}, max_tokens=100,
            )
        self.assertEqual(result.records[0]["text"], "kept")
        self.assertEqual(result.transport.warnings, ("response_format_unenforced",))
        self.assertEqual(states[0]["state"], "unsupported")


if __name__ == "__main__":
    unittest.main()
