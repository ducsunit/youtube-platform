import json
import tempfile
import unittest
from pathlib import Path

from youtube_pipeline.topic_history import duplicate_reason, load_history, record_completed


class TopicHistoryTests(unittest.TestCase):
    def test_completed_topic_is_persisted_at_project_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            run_dir = project / "runs" / "video-01"
            run_dir.mkdir(parents=True)
            record_completed(run_dir, "video-01", {
                "selected_topic": "帰宅後にスマホを開いてしまう",
                "source_concept": "習慣",
                "chosen_title": "帰宅後に動けない理由",
            })
            history = load_history(project)
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["run_id"], "video-01")
            self.assertTrue((project / "data/topic-history.json").is_file())

    def test_exact_and_near_duplicate_are_detected(self):
        history = [{
            "status": "completed",
            "topic": "帰宅後にスマホを開いてしまう",
            "selected_topic": "帰宅後にスマホを開いてしまう",
            "source_concept": "習慣",
            "audience_moment": "帰宅後",
        }]
        self.assertIsNotNone(duplicate_reason({"topic": "帰宅後にスマホを開いてしまう"}, history))
        self.assertIsNotNone(duplicate_reason({"topic": "帰宅後にスマホを開いてしまう心理"}, history))

    def test_old_completed_run_is_migrated_when_catalog_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            run_dir = project / "runs" / "old-run"
            (run_dir / "research").mkdir(parents=True)
            (run_dir / "script").mkdir()
            (run_dir / "run_state.json").write_text(json.dumps({"status": "complete"}), encoding="utf-8")
            (run_dir / "research/topic-selection.json").write_text(json.dumps({"selected_topic": "古いテーマ"}), encoding="utf-8")
            self.assertEqual(load_history(project)[0]["selected_topic"], "古いテーマ")


if __name__ == "__main__":
    unittest.main()
