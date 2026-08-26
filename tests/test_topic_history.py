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


class UsedTopicHistoryTests(unittest.TestCase):
    """Guard trùng chủ đề phải chặn cả run hoàn tất CHƯA đăng (drafted)."""

    def test_drafted_rows_block_duplicates(self):
        from youtube_pipeline.resource_pack.pipeline import _used_topic_history

        history = [
            {"run_id": "video-09", "topic": "旧友", "status": "published"},
            {"run_id": "video-10", "topic": "大丈夫", "status": "drafted"},
            {"run_id": "video-11", "topic": "始められない", "status": None},
            {"run_id": "video-12", "topic": "断れる", "status": "archived"},
        ]
        used = _used_topic_history(history)
        run_ids = {row["run_id"] for row in used}
        # published + drafted + legacy (None) đều chặn
        self.assertIn("video-09", run_ids)
        self.assertIn("video-10", run_ids)
        self.assertIn("video-11", run_ids)
        # archived là chủ ý rút khỏi xuất bản → cho phép tái sử dụng
        self.assertNotIn("video-12", run_ids)

    def test_duplicate_reason_matches_drafted_topic(self):
        from youtube_pipeline.topic_history import duplicate_reason

        history = [{"run_id": "video-10", "topic": "「大丈夫」と言ってしまう心理", "status": "drafted"}]
        candidate = {"topic": "「大丈夫」と言ってしまう心理――シャドウの話", "source_concept": "シャドウ"}
        self.assertIsNotNone(duplicate_reason(candidate, history))
