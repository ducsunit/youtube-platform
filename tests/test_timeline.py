import tempfile
import unittest
from pathlib import Path

from youtube_pipeline.core import (
    ArtifactStore,
    FunctionStage,
    PipelineEngine,
    RunContext,
    RunState,
    StageResult,
)
from youtube_pipeline.timeline import build_timeline, find_audio_file, probe_duration

SECTION_CHARS = (349, 273, 354, 294, 320, 290, 259, 305)


def _sections(estimated_max_seconds=386):
    rows = [
        {
            "index": index,
            "id": "S%d" % index,
            "chars": chars,
            "file": "%02d_section-%02d.txt" % (index, index),
            "text": "本文 %d です。" % index,
        }
        for index, chars in enumerate(SECTION_CHARS, start=1)
    ]
    return {
        "section_policy": {
            "script_chars": sum(SECTION_CHARS),
            "cpm_min": 380,
            "cpm_max": 400,
            "estimated_min_seconds": 367,
            "estimated_max_seconds": estimated_max_seconds,
        },
        "sections": rows,
        "total_chars": sum(SECTION_CHARS),
    }


def _strategy(section_counts=None):
    section_counts = section_counts or [9, 9, 9, 8, 11, 5, 3, 0]
    beats = []
    index = 0
    for section_index, count in enumerate(section_counts, start=1):
        for offset in range(count):
            index += 1
            beats.append(
                {
                    "id": "B%02d" % index,
                    "script_section": "S%d" % section_index,
                    "visual_information": "info %d" % index,
                }
            )
    return {"visual_beats": beats}


def _storyboard(strategy):
    rows = []
    for index, beat in enumerate(strategy["visual_beats"], start=1):
        rows.append(
            {
                "event_id": "E%02d" % index,
                "beat_id": beat["id"],
                "image_id": "IMG-%02d" % (index // 2 + 1),
                "new_image": index % 2 == 1,
                "motion": "motion %d" % index,
                "visual_information": beat["visual_information"],
            }
        )
    return rows


def _planning():
    functions = ["recognition", "contradiction", "explanation", "application", "reinforcement", "action", "summary_cta", "cta"]
    return {
        "sections": [{"id": "S%d" % i, "segment_function": functions[i - 1]} for i in range(1, 9)]
    }


class BuildTimelineTest(unittest.TestCase):
    def test_draft_mode_uses_estimated_total(self):
        markdown, meta = build_timeline(
            _storyboard(_strategy()),
            _strategy(),
            _sections(estimated_max_seconds=386),
            _planning(),
            duration=None,
        )
        self.assertEqual(meta["status"], "DRAFT_TIMING")
        self.assertEqual(meta["estimated_seconds"], 386)
        self.assertNotIn("measured_cpm", meta)
        self.assertIn("DRAFT_TIMING", markdown)
        # 386s = 6:26.0 — tổng dự kiến xuất hiện trong bảng.
        self.assertIn("6:26", markdown)

    def test_draft_marks_cannot_claim_precision(self):
        markdown, _ = build_timeline(
            _storyboard(_strategy()),
            _strategy(),
            _sections(),
            _planning(),
            duration=None,
        )
        self.assertIn("chưa có audio", markdown)
        self.assertIn("audio/", markdown)

    def test_final_mode_computes_real_cpm(self):
        strategy = _strategy()
        storyboard = _storyboard(strategy)
        markdown, meta = build_timeline(
            storyboard,
            strategy,
            _sections(),
            _planning(),
            duration=505.124,
            audio_file="video5-new.mp3",
        )
        self.assertEqual(meta["status"], "FINAL_TIMING")
        self.assertEqual(meta["audio_file"], "video5-new.mp3")
        self.assertAlmostEqual(meta["duration_seconds"], 505.124, places=3)
        self.assertAlmostEqual(meta["measured_cpm"], 2444 / 505.124 * 60, places=1)
        self.assertIn("FINAL_TIMING", markdown)
        # CPM thật ngoài dải 380–400 phải cảnh báo.
        self.assertTrue(any("CPM thật" in w for w in meta["warnings"]))

    def test_final_within_band_no_cpm_warning(self):
        duration = 2444 / 390 * 60
        _, meta = build_timeline(
            _storyboard(_strategy()),
            _strategy(),
            _sections(),
            _planning(),
            duration=duration,
            audio_file="audio.mp3",
        )
        self.assertFalse(any("CPM thật" in w for w in meta["warnings"]))

    def test_all_events_covered_within_section_windows(self):
        strategy = _strategy()
        storyboard = _storyboard(strategy)
        markdown, meta = build_timeline(
            storyboard,
            strategy,
            _sections(),
            _planning(),
            duration=100.0,
            audio_file="a.mp3",
        )
        self.assertEqual(meta["event_count"], len(storyboard))
        self.assertEqual(meta["unique_images"], len({row["image_id"] for row in storyboard}))
        # Event đầu của S1 bắt đầu tại 0.
        self.assertIn("| E01 | 0:00.0–", markdown)

    def test_section_without_events_gets_warning(self):
        _, meta = build_timeline(
            _storyboard(_strategy([9, 9, 9, 8, 11, 5, 3, 0])),
            _strategy([9, 9, 9, 8, 11, 5, 3, 0]),
            _sections(),
            _planning(),
            duration=100.0,
            audio_file="a.mp3",
        )
        self.assertTrue(any("S8" in w for w in meta["warnings"]))

    def test_reuse_rows_marked(self):
        markdown, _ = build_timeline(
            _storyboard(_strategy()),
            _strategy(),
            _sections(),
            _planning(),
            duration=100.0,
            audio_file="a.mp3",
        )
        self.assertIn("♻️", markdown)


class StageFingerprintTest(unittest.TestCase):
    """Hồi quy cho fix quan trọng: config của stage tham gia fingerprint.

    Nếu không, stage timeline bị reuse mãi khi bỏ audio vào audio/ rồi resume
    (file audio không nằm trong artifact_index nên requires không đổi).
    """

    def _context(self, directory):
        store = ArtifactStore(directory)
        state = RunState(run_id="fingerprint-test", profile="resource_pack", topic="", config_snapshot={})
        return RunContext(state=state, store=store, provider=None, raw_data="", topic="", config={})

    def test_stage_config_changes_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = self._context(Path(tmp))
            base = FunctionStage("timeline", lambda c: StageResult(), version="1")
            with_audio = FunctionStage("timeline", lambda c: StageResult(), version="1", config={"audio_digest": "abc"})
            self.assertNotEqual(
                PipelineEngine._fingerprint(base, context),
                PipelineEngine._fingerprint(with_audio, context),
            )

    def test_same_config_gives_same_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = self._context(Path(tmp))
            first = FunctionStage("timeline", lambda c: StageResult(), version="1", config={"audio_digest": "abc"})
            second = FunctionStage("timeline", lambda c: StageResult(), version="1", config={"audio_digest": "abc"})
            self.assertEqual(
                PipelineEngine._fingerprint(first, context),
                PipelineEngine._fingerprint(second, context),
            )


class FindAudioFileTest(unittest.TestCase):
    def test_finds_largest_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "small.mp3").write_bytes(b"a" * 10)
            (directory / "merged.mp3").write_bytes(b"b" * 100)
            (directory / "notes.txt").write_text("noise", encoding="utf-8")
            self.assertEqual(find_audio_file(directory).name, "merged.mp3")

    def test_missing_dir_returns_none(self):
        self.assertIsNone(find_audio_file(Path("/nonexistent/audio")))

    def test_no_audio_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(find_audio_file(Path(tmp)))

    def test_probe_duration_unknown_file_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = probe_duration(Path(tmp) / "missing.mp3")
            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
