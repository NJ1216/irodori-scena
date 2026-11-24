import json
import unittest
from pathlib import Path
from unittest.mock import patch

from server.app import (DraftRequest, LlmContractResult, LlmTransportResult, create_draft_plan,
                        draft_author_ending, draft_plan_contract, extract_contract_records,
                        merge_record_fields, planned_draft_beats, plan_from_records)


class EndingAcceptanceTests(unittest.TestCase):
    def test_stage_direction_tail_and_absent_ending_are_not_invented(self):
        self.assertIsNone(draft_author_ending("配信で近況を話す。親しみを込めて話す。"))
        self.assertIsNone(draft_author_ending("雨の喫茶店で二人が話す。"))

    def test_explicit_ending_in_middle_uses_only_exact_unique_quote(self):
        quote = "最後に二人で傘を差して帰る。"
        theme = "喫茶店で再会する。" + quote + "声は静かに。"
        ending = draft_author_ending(theme, quotes=[quote])
        self.assertEqual(ending["text"], quote)
        self.assertIsNone(draft_author_ending(theme, quotes=["最後に一人で帰る。"]))
        self.assertIsNone(draft_author_ending(theme + quote, quotes=[quote]))
        self.assertIsNone(draft_author_ending(theme, quotes=[quote, "声は静かに。"]))

    def test_truncated_plan_keeps_valid_scenes_and_author_theme(self):
        contract = draft_plan_contract({"A"})
        content = ('{"records":[{"kind":"title","text":"再会"},'
                   '{"kind":"chapter","index":1,"scenes":['
                   '{"purpose":"再会😊","start":"入店","end":"着席"},null,'
                   '{"purpose":42},{"purpose":"約束する","start":"相談","end":"途')
        raw, partial = extract_contract_records(content, contract)
        records, _ = merge_record_fields(raw, contract)
        self.assertTrue(partial)
        plan = plan_from_records(tuple(records))
        self.assertEqual(len(plan["chapters"][0]["beats"]), 2)
        self.assertIn("目的: 再会", plan["chapters"][0]["beats"][0])
        self.assertNotIn("😊", str(plan))
        request = DraftRequest(base_url="http://example.invalid/v1", model="test", character_ids=["a"],
                               target_minutes=1, theme="途中の構成でもこの作者指定は消さない。")
        result = LlmContractResult(tuple(records), "schema", content, (), LlmTransportResult(content, partial=True))
        with patch("server.modules.llm_completion_service.complete_records", return_value=result):
            generated = create_draft_plan(request, cast_context=[], chunk_count=1, target_characters=300,
                                           token_budget=4096, debug_directory=Path("unused"))
        self.assertEqual(generated["story_bible"], request.theme)
        self.assertIsNone(generated["_author_ending"])

    def test_outgoing_schema_has_kind_specific_fields_and_one_final_scene(self):
        schema = draft_plan_contract({"A"}).response_schema
        variants = schema["properties"]["records"]["items"]["anyOf"]
        title = next(v for v in variants if v["properties"]["kind"]["enum"] == ["title"])
        self.assertEqual(title["required"], ["kind", "text"])
        ending = draft_author_ending("最後に手を振って配信を終える。", quotes=["最後に手を振って配信を終える。"])
        chapters = [{"beats": ["近況", "締め"], "author_ending": ending}]
        beats = planned_draft_beats(chapters, 500)
        self.assertEqual(len(beats), 2)
        self.assertEqual(ending["id"], beats[-1].source)
        self.assertIn(ending["text"], beats[-1].text)
        json.dumps(schema)
