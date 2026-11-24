from __future__ import annotations

import unittest

from server.app import parse_profile_suggestion
from server.modules.profile_suggestions import RELATION_SYSTEM


def parse_relations(content: str):
    return parse_profile_suggestion(
        content, labels={}, blank_fields=set(), allowed_relation_names={"紗良"},
        allowed_relation_fields={"紗良": {"address", "relationship"}},
    )


class AiRelationAddressPolicyTests(unittest.TestCase):
    def test_relation_prompt_defaults_to_names_and_contrasts_setting_labels(self) -> None:
        for text in ("名前・愛称を既定", "王子様", "文学少女ちゃん", "調停役さん", "formal_title", "relational_nickname"):
            self.assertIn(text, RELATION_SYSTEM)

    def test_discards_unnatural_ai_addresses_but_keeps_valid_sibling(self) -> None:
        disallowed = (
            "あなたさん", "貴方さん", "君さん", "きみさん", "あなたちゃん", "あなたくん",
            "あんた様", "お前様", "てめえさん", "貴様様", "紗良さん様", "紗良ちゃんさん",
        )
        for address in disallowed:
            with self.subTest(address=address):
                parsed = parse_relations(
                    f"RELATION|紗良|呼び方|{address}\nRELATION|紗良|関係性|大切な友人。"
                )
                self.assertEqual(parsed, ({}, {"紗良": {"relationship": "大切な友人。"}}))

    def test_keeps_contextually_natural_pronoun_addresses(self) -> None:
        for address in ("あなた様", "貴方様", "お前さん", "お宅様", "そちら様"):
            with self.subTest(address=address):
                self.assertEqual(parse_relations(f"RELATION|紗良|呼び方|{address}"), (
                    {}, {"紗良": {"address": address}},
                ))

    def test_json_discards_spaced_bad_address_but_keeps_relationship(self) -> None:
        parsed = parse_relations(
            '{"profile_details":{},"cast_relations":{"紗良":'
            '{"address":"あなた さん","relationship":"大切な友人。"}}}'
        )
        self.assertEqual(parsed, ({}, {"紗良": {"relationship": "大切な友人。"}}))


if __name__ == "__main__":
    unittest.main()
