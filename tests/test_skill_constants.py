"""Regression tests cho skills/CHANNEL_CONSTANTS.md.

Chặn psychology-first flow drift: constants phải parse được, skill dùng single
source of truth, không còn hard-code storytelling template cũ, và mọi reference
CONSTANTS.* phải resolve.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"
CONTENT_DIR = ROOT / "content"
CONSTANTS_PATH = SKILLS_DIR / "CHANNEL_CONSTANTS.md"

YAML_FENCE_RE = re.compile(r"```yaml\s*\n(.*?)\n?```", re.DOTALL)
KEY_LINE_RE = re.compile(r"^(\s*)([^\s:#]+):(.*)$")
# Lookbehind chặn "CHANNEL_CONSTANTS.md" khớp nhầm thành ref "CONSTANTS.md"
REF_RE = re.compile(r"(?<![A-Za-z0-9_])CONSTANTS\.([\w]+(?:\.[\w]+)*)")
# Không phải reference cụ thể: `CONSTANTS.title_*` là wildcard documentation.

# Số hardcode đã từng tồn tại rải rác — không được quay lại ngoài CHANNEL_CONSTANTS.md.
STALE_PATTERNS = [
    r"10–13",               # focus cũ (seri) — canonical: CONSTANTS.duration_focus
    r"13–17",               # standard cũ (seri) — canonical: CONSTANTS.duration_standard
    r"18–22",               # deep-dive đã REMOVED — CONSTANTS.format_deep_dive
    r"6–12",                # focus cũ (planning/production/full-video/review-rule-v9)
    r"6-12",                # biến thể hyphen của 6–12
    r"8–10 phút",           # trọng tâm cũ — canonical: trọng tâm 9-10
    r"2\.800",              # char target cũ (planning) — CONSTANTS.char_range_target
    r"2\.400",              # char floor — chỉ qua CONSTANTS.char_range_absolute
    r"3\.100",              # char ceiling cũ — CONSTANTS.char_range_absolute
    r"3900",                # số toán cũ trong ví dụ tính ký tự
    r"\[2800[^\]]*3000\]",  # HANDOFF range cũ — CONSTANTS.char_range_target
    r"SPEED_CPM = 340",     # CPM sai — canonical 389 (bug fix review-rule-v9)
    r"5–10 tag",            # tags cũ — canonical: CONSTANTS.tags_count "9-15"
    r"sau 45 giây",         # insight timing cũ — canonical: 35s
]

# Key lõi của channel-level invariants + psychology-first workflow.
# Không kiểm các mandatory 7-part/14-step cũ: chúng đã bị thay thế có chủ đích
# bởi adaptive Psychology Brief + route động.
CORE_KEYS = [
    "duration_focus", "char_range_target", "char_range_absolute", "cpm_measured", "cpm_range",
    "tts_profile", "hook_contract.recognition_by_seconds",
    "hook_contract.first_real_insight_by_seconds", "no_emotion_only_max_seconds",
    "sections_count_range", "first_payoff_before_minutes", "research_min_count",
    "script_spine", "mechanism_count_target", "mechanism_count_hard_max",
    "behavior_signals_range", "psychology_explanation_min_pct", "scene_example_max_pct",
    "micro_example_max_sentences", "consecutive_scene_sentences_max",
    "origin_policy", "practical_shift_policy", "ending_policy", "viewer_is_center",
    "fictional_protagonist", "plot_or_character_arc", "trauma_by_default",
    "diagnosis_of_viewer", "generic_self_help", "each_concept_must_answer_why",
    "psychology_brief_required", "mechanism_explains_behavior_required",
    "inner_process_required", "anti_story_check_required",
    "self_understanding_ending_required", "title_target_chars", "title_hard_max_chars",
    "thumbnail_copy_target_chars", "thumbnail_copy_hard_max_chars",
    "title_thumbnail_overlap_max_pct", "contrast_min_ratio",
]


def _parse_constants(path=CONSTANTS_PATH):
    """Parse mọi ```yaml fence trong CHANNEL_CONSTANTS.md.

    Trả về (keys, values): keys = set dotted path đã normalize (bỏ prefix
    `CHANNEL_CONSTANTS.` của mục 9), values = dict path -> value thô (chỉ các
    dòng có value, lấy lần đầu gặp).
    """
    text = path.read_text(encoding="utf-8")
    keys = set()
    values = {}
    for block in YAML_FENCE_RE.findall(text):
        stack = []  # [(indent, key), ...] — cha gần nhất theo indent
        for line in block.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("-"):
                continue
            m = KEY_LINE_RE.match(line)
            if not m:
                continue
            indent = len(m.group(1))
            key = m.group(2).strip()
            value = m.group(3).strip()
            while stack and indent <= stack[-1][0]:
                stack.pop()
            parent = ".".join(k for _, k in stack)
            path = f"{parent}.{key}" if parent else key
            if path.startswith("CHANNEL_CONSTANTS."):
                path = path[len("CHANNEL_CONSTANTS."):]
            keys.add(path)
            if value:
                values.setdefault(path, value)
            stack.append((indent, key))
    return keys, values


class ChannelConstantsFileTests(unittest.TestCase):
    """Các test chạy trên chính CHANNEL_CONSTANTS.md."""

    @classmethod
    def setUpClass(cls):
        cls.keys, cls.values = _parse_constants()

    def test_yaml_blocks_parse_and_define_core_keys(self):
        self.assertGreaterEqual(len(self.keys), 50, "YAML block có vẻ hỏng — quá ít key parse được")
        missing = [k for k in CORE_KEYS if k not in self.keys]
        self.assertEqual([], missing, f"thiếu key lõi trong CHANNEL_CONSTANTS.md: {missing}")

    def test_canonical_value_anchors(self):
        """Các giá trị mỏ neo quan trọng nhất không được drift âm thầm."""

        def first_token(key):
            self.assertIn(key, self.values, f"key {key} không có value để neo")
            m = re.match(r"(\S+)", self.values[key])
            self.assertIsNotNone(m, f"value của {key} rỗng: {self.values[key]!r}")
            return m.group(1)

        self.assertEqual("389", first_token("cpm_measured"))
        self.assertEqual("35", first_token("hook_contract.first_real_insight_by_seconds"))
        self.assertEqual("45", first_token("no_emotion_only_max_seconds"))
        self.assertEqual('"2-3"', first_token("mechanism_count_target"))

    def test_adaptive_psychology_spine_replaces_14_step_template(self):
        text = CONSTANTS_PATH.read_text(encoding="utf-8")
        self.assertIn("Psychology-First", text)
        self.assertIn("behavior recognition", text)
        self.assertIn("mechanism chain", text)
        self.assertNotIn("KHUÔN 14 BƯỚC", text)


class SkillFileTests(unittest.TestCase):
    """Các test chạy trên skill files + content library."""

    def test_every_skill_has_mandatory_preamble(self):
        skill_files = sorted(SKILLS_DIR.glob("**/SKILL.md"))
        self.assertGreaterEqual(len(skill_files), 10, "không tìm đủ 10 SKILL.md — glob hỏng?")
        for f in skill_files:
            text = f.read_text(encoding="utf-8")
            rel = f.relative_to(ROOT)
            self.assertIn("CHANNEL_CONSTANTS.md", text, f"{rel}: thiếu reference CHANNEL_CONSTANTS.md")
            self.assertIn("BẮT BUỘC", text, f"{rel}: thiếu nhãn BẮT BUỘC")

    def test_no_stale_literals_in_skill_files(self):
        files = [f for f in SKILLS_DIR.glob("**/*.md") if f.name != "CHANNEL_CONSTANTS.md"]
        hits = []
        for pattern in STALE_PATTERNS:
            rx = re.compile(pattern)
            for f in files:
                for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                    if rx.search(line):
                        hits.append(f"{f.relative_to(ROOT)}:{i}: {line.strip()}  [{pattern}]")
        self.assertEqual([], hits, "còn số hardcode stale trong skills/:\n" + "\n".join(hits))

    def test_constants_references_resolve(self):
        files = [f for f in SKILLS_DIR.glob("**/*.md") if f.name != "CHANNEL_CONSTANTS.md"]
        files += sorted(CONTENT_DIR.glob("**/*.md"))
        keys, _ = _parse_constants()
        bad = []
        for f in files:
            for m in REF_RE.finditer(f.read_text(encoding="utf-8")):
                if m.group(1).endswith("_"):
                    continue
                if m.group(1) not in keys:
                    bad.append(f"{f.relative_to(ROOT)}: CONSTANTS.{m.group(1)}")
        self.assertEqual([], bad, "reference không resolve:\n" + "\n".join(bad))

    def test_review_rule_v7_uses_cpm_389(self):
        f = SKILLS_DIR / "skill_tam_ly_hoc_script_production_JP" / "review-rule-v9.md"
        text = f.read_text(encoding="utf-8")
        self.assertIn("CONSTANTS.cpm_measured", text, "review rule phải tham chiếu CPM canonical")
        self.assertNotIn("SPEED_CPM = 340", text, "CPM 340 đã bị sửa — không được quay lại")


if __name__ == "__main__":
    unittest.main()
