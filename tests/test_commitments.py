"""Commitment manifest — validator + repair ladder (L1/L2/L3)."""
from __future__ import annotations

import unittest

from youtube_pipeline.resource_pack.commitments import (
    normalize_commitments,
    numeric_hints,
    validate_commitments,
)


def _plan(psychological_job: str = "七つの静かなサインを観察項目として束ねる。"):
    return {
        "sections": [
            {"id": "S4", "psychological_job": "behavior の背景を見る。", "new_information": "x"},
            {"id": "S5", "psychological_job": psychological_job, "new_information": "y"},
        ]
    }


class NormalizeCommitmentsTests(unittest.TestCase):
    def test_drops_junk_and_coerces_types(self):
        raw = {
            "commitments": [
                {"type": "enumeration", "label": "静かなサイン", "count": "7",
                 "items": ["a", "b", "", None, "c", "d", "e", "f", "g"],
                 "sections": ["S5", "S9"]},
                {"type": "alien_type", "x": 1},
                "not-a-dict",
                {"type": "factual_claim", "value": "99%", "framing": "SOURCED", "ledger_ref": "c1"},
                {"type": "promise", "kind": "beginner_friendly", "note": "x"},
                {"type": "enumeration", "label": "", "count": "abc", "items": []},
            ]
        }
        rows = normalize_commitments(raw)
        self.assertEqual(len(rows), 3)
        enum = rows[0]
        self.assertEqual(enum["count"], 7)
        self.assertEqual(len(enum["items"]), 7)  # rỗng/None bị lọc
        # normalize không biết plan — section lạ để validator bắt riêng
        self.assertEqual(enum["sections"], ["S5", "S9"])
        self.assertEqual(rows[1]["framing"], "sourced")

    def test_coerces_invented_type_and_dict_items(self):
        """LLM tự sáng tạo type 'topic' + items dạng dict → coerce về enumeration."""
        raw = {"commitments": [{
            "type": "topic", "text": "7つ", "number_framing": "symbolic", "count": 3,
            "items": [
                {"item": "拒否感情が同時に存在している可能性", "source_ref": "S1"},
                {"text": "シャドウは象徴的に扱える", "source_ref": "S2"},
                "三つ目の論点",
            ],
            "sections": ["S5"],
        }]}
        rows = normalize_commitments(raw)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["type"], "enumeration")
        self.assertEqual(row["label"], "7つ")
        self.assertEqual(row["number_framing"], "symbolic")
        self.assertEqual(row["items"], [
            "拒否感情が同時に存在している可能性", "シャドウは象徴的に扱える", "三つ目の論点",
        ])

    def test_non_dict_input(self):
        self.assertEqual(normalize_commitments(None), [])
        self.assertEqual(normalize_commitments("x"), [])


class ValidateCommitmentsTests(unittest.TestCase):
    def test_video12_scenario_count_mismatch_is_caught(self):
        """Title hứa 7, manifest khai count=7 nhưng chỉ liệt kê 5 items → chặn."""
        plan = _plan()
        hints = numeric_hints("7つの静かなサイン｜...", plan)
        commitments = normalize_commitments({"commitments": [
            {"type": "enumeration", "label": "静かなサイン", "count": 7,
             "items": ["返事の速さ", "身体のこわばり", "同じ文脈", "自己非難", "遅れた怒り"],
             "sections": ["S5"]},
        ]})
        issues = validate_commitments(commitments, plan, hints)
        self.assertTrue(any("count=7 nhưng items=5" in i for i in issues))

    def test_uncovered_number_is_caught(self):
        """Con số trong psychological_job không được commitment nào cover → chặn."""
        plan = _plan()
        hints = numeric_hints("7つの静かなサイン", plan)
        issues = validate_commitments([], plan, hints)
        # psychological_job viết kanji "七つ" — hint giữ nguyên văn
        self.assertTrue(any("'七つ'" in i and "S5" in i for i in issues))

    def test_full_coverage_passes(self):
        plan = _plan()
        hints = numeric_hints("7つの静かなサイン", plan)
        commitments = normalize_commitments({"commitments": [
            {"type": "enumeration", "label": "静かなサイン 7つ", "count": 7,
             "items": ["a", "b", "c", "d", "e", "f", "g"], "sections": ["S5"]},
        ]})
        self.assertEqual(validate_commitments(commitments, plan, hints), [])

    def test_sourced_claim_requires_ledger_ref(self):
        plan = _plan("99%の人が知らないという話。")
        hints = numeric_hints("99%の人が知らない", plan)
        commitments = normalize_commitments({"commitments": [
            {"type": "factual_claim", "value": "99%", "framing": "sourced", "ledger_ref": ""},
        ]})
        issues = validate_commitments(commitments, plan, hints, ledger_text="{}")
        self.assertTrue(any("thiếu ledger_ref" in i for i in issues))

    def test_rhetorical_claim_covers_hint_without_ledger(self):
        plan = _plan("99%の人が知らないという話。")
        hints = numeric_hints("99%の人が知らない", plan)
        commitments = normalize_commitments({"commitments": [
            {"type": "factual_claim", "value": "99%", "framing": "rhetorical", "note": "ẩn dụ"},
        ]})
        self.assertEqual(validate_commitments(commitments, plan, hints), [])

    def test_sourced_ledger_ref_must_exist(self):
        plan = _plan("1万人に聞いた調査。")
        hints = numeric_hints("1万人に聞いた", plan)
        commitments = normalize_commitments({"commitments": [
            {"type": "factual_claim", "value": "1万人", "framing": "sourced", "ledger_ref": "claim-xyz"},
        ]})
        issues = validate_commitments(commitments, plan, hints, ledger_text='{"claims": []}')
        self.assertTrue(any("không có trong claim ledger" in i for i in issues))


class NumericHintsTests(unittest.TestCase):
    def test_scans_topic_and_psychological_job_only(self):
        plan = _plan("8つの理由を束ねる。")
        hints = numeric_hints("5分でわかる「99%の人が知らない」話", plan)
        texts = {(h["where"], h["text"]) for h in hints}
        self.assertIn(("topic", "5分"), texts)
        self.assertIn(("topic", "99%"), texts)
        self.assertIn(("S5", "8つ"), texts)
        # S4 không có số → không hint


if __name__ == "__main__":
    unittest.main()
