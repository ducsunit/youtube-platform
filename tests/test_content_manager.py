"""tests/test_content_manager.py — Unit tests for content_manager.py.

All tests use monkeypatching or temporary files — no real content/ files required.
"""
from __future__ import annotations

import textwrap
from unittest.mock import patch

import pytest

from youtube_pipeline import content_manager


# ---------------------------------------------------------------------------
# Fixtures — raw markdown strings
# ---------------------------------------------------------------------------

QUEUE_MD = textwrap.dedent("""\
    # Video Queue

    | # | Working title | Mechanism | Status |
    |---|---|---|---|
    | 1 | 返信の罪悪感 | 感情労働 | queued |
    | 2 | 人の期待に疲れた夜 | 反芻思考 | queued |

    ### 1. 返信の罪悪感
    - **working_title_jp:** 返信できない夜、なぜ心だけが疲れる？
    - **mechanism:** 感情労働
    - **backup_mechanism:** 認知的不協和
    - **cultural_frame:** 建前/本音
    - **central_emotion:** 罪悪感

    ### 2. 人の期待に疲れた夜
    - **working_title_jp:** 人の期待に応え続けると、なぜ疲れる？
    - **mechanism:** 反芻思考
    - **backup_mechanism:** 愛着スタイル
    - **cultural_frame:** 甘え
    - **central_emotion:** 疲弊

    ## Nhật ký dùng
    | Ngày đăng | Topic | Cơ chế dùng | Cultural frame | Video ID |
    |---|---|---|---|---|
    | 2026-07-01 | 課題の分離の話 | 課題の分離 | 侘寂 | abc123 |
    | 2026-07-15 | 感情労働の話 | 感情労働 | 建前/本音 | def456 |
""")

MECHANISMS_MD = textwrap.dedent("""\
    # Mechanisms

    ## 1. 課題の分離 — ⛔ (tạm ngừng: đã dùng 3 video liên tiếp)
    - **Tác giả + năm:** 岸見一郎 (1999)
    - **Nguồn:** 嫌われる勇気
    - **Góc hook:** Ai chịu trách nhiệm?
    - **Ý tưởng lõi:** Phân tách bài toán của bạn và bài toán của người khác

    ## 2. 感情労働
    - **Tác giả + năm:** Arlie Hochschild (1983)
    - **Nguồn:** The Managed Heart
    - **Góc hook:** Quản lý cảm xúc như một công việc?
    - **Ý tưởng lõi:** Lao động cảm xúc trong các mối quan hệ hàng ngày

    ## 3. 反芻思考
    - **Tác giả + năm:** Susan Nolen-Hoeksema (1991)
    - **Nguồn:** Responses to Depression
    - **Góc hook:** Vòng lặp suy nghĩ tiêu cực
    - **Ý tưởng lõi:** Tập trung lặp đi lặp lại vào cảm xúc tiêu cực
""")

CULTURAL_FRAMES_MD = textwrap.dedent("""\
    # Cultural Frames JP

    ## 1. 侘寂
    - **Khái niệm:** Vẻ đẹp trong sự không hoàn hảo và vô thường
    - **Dùng ở bước nào:** Writing — closing validation
    - **Pair tốt với cơ chế:** 反芻思考, 感情労働

    ## 2. 建前/本音
    - **Khái niệm:** Bề ngoài công khai vs cảm xúc thật bên trong
    - **Dùng ở bước nào:** Writing — mechanism deep dive
    - **Pair tốt với cơ chế:** 感情労働, 愛着スタイル
""")


def _patch_read(queue="", mechanisms="", cultural_frames=""):
    """Return a side_effect function that dispatches by filename."""
    def _read(filename: str) -> str:
        if filename == "video-queue.md":
            return queue
        if filename == "mechanisms.md":
            return mechanisms
        if filename == "cultural-frames-jp.md":
            return cultural_frames
        return ""
    return _read


# ---------------------------------------------------------------------------
# queue_inject_text
# ---------------------------------------------------------------------------

class TestQueueInjectText:
    def test_with_queued_topics(self):
        with patch.object(content_manager, "_read", side_effect=_patch_read(queue=QUEUE_MD, mechanisms=MECHANISMS_MD)):
            result = content_manager.queue_inject_text()
        assert "返信の罪悪感" in result
        assert "感情労働" in result
        assert "建前/本音" in result

    def test_includes_recently_used(self):
        with patch.object(content_manager, "_read", side_effect=_patch_read(queue=QUEUE_MD, mechanisms=MECHANISMS_MD)):
            result = content_manager.queue_inject_text()
        assert "課題の分離" in result or "感情労働" in result  # from diary

    def test_includes_paused_warning(self):
        with patch.object(content_manager, "_read", side_effect=_patch_read(queue=QUEUE_MD, mechanisms=MECHANISMS_MD)):
            result = content_manager.queue_inject_text()
        assert "課題の分離" in result  # appears as paused mechanism

    def test_empty_when_no_file(self):
        with patch.object(content_manager, "_read", return_value=""):
            result = content_manager.queue_inject_text()
        assert result == ""


# ---------------------------------------------------------------------------
# mechanism_citation_text
# ---------------------------------------------------------------------------

class TestMechanismCitationText:
    def test_returns_citation_for_active_mechanism(self):
        with patch.object(content_manager, "_read", side_effect=_patch_read(mechanisms=MECHANISMS_MD)):
            result = content_manager.mechanism_citation_text("感情労働")
        assert "Arlie Hochschild" in result
        assert "The Managed Heart" in result
        assert "感情労働" in result

    def test_returns_empty_for_paused_mechanism(self):
        with patch.object(content_manager, "_read", side_effect=_patch_read(mechanisms=MECHANISMS_MD)):
            result = content_manager.mechanism_citation_text("課題の分離")
        assert result == ""

    def test_returns_empty_for_unknown_mechanism(self):
        with patch.object(content_manager, "_read", side_effect=_patch_read(mechanisms=MECHANISMS_MD)):
            result = content_manager.mechanism_citation_text("存在しないメカニズム")
        assert result == ""

    def test_fuzzy_match_partial_name(self):
        with patch.object(content_manager, "_read", side_effect=_patch_read(mechanisms=MECHANISMS_MD)):
            result = content_manager.mechanism_citation_text("反芻")
        assert "Nolen-Hoeksema" in result


# ---------------------------------------------------------------------------
# mechanism_diversity_ok
# ---------------------------------------------------------------------------

class TestMechanismDiversityOk:
    def test_blocks_paused_mechanism(self):
        with patch.object(content_manager, "_read", side_effect=_patch_read(queue=QUEUE_MD, mechanisms=MECHANISMS_MD)):
            assert content_manager.mechanism_diversity_ok("課題の分離") is False

    def test_blocks_recently_used(self):
        # 感情労働 is in the diary (last 3)
        with patch.object(content_manager, "_read", side_effect=_patch_read(queue=QUEUE_MD, mechanisms=MECHANISMS_MD)):
            assert content_manager.mechanism_diversity_ok("感情労働") is False

    def test_allows_unused_mechanism(self):
        with patch.object(content_manager, "_read", side_effect=_patch_read(queue=QUEUE_MD, mechanisms=MECHANISMS_MD)):
            assert content_manager.mechanism_diversity_ok("反芻思考") is True

    def test_ok_when_no_data(self):
        with patch.object(content_manager, "_read", return_value=""):
            assert content_manager.mechanism_diversity_ok("何でも") is True


# ---------------------------------------------------------------------------
# cultural_frame_text
# ---------------------------------------------------------------------------

class TestCulturalFrameText:
    def test_returns_block_for_known_frame(self):
        with patch.object(content_manager, "_read", side_effect=_patch_read(cultural_frames=CULTURAL_FRAMES_MD)):
            result = content_manager.cultural_frame_text("建前/本音")
        assert "建前/本音" in result
        assert "感情労働" in result
        assert "Quy tắc" in result

    def test_fuzzy_match(self):
        with patch.object(content_manager, "_read", side_effect=_patch_read(cultural_frames=CULTURAL_FRAMES_MD)):
            result = content_manager.cultural_frame_text("侘寂")
        assert "侘寂" in result
        assert "反芻思考" in result

    def test_returns_empty_for_unknown_frame(self):
        with patch.object(content_manager, "_read", side_effect=_patch_read(cultural_frames=CULTURAL_FRAMES_MD)):
            result = content_manager.cultural_frame_text("存在しないframe")
        assert result == ""


# ---------------------------------------------------------------------------
# Fallback when content files missing
# ---------------------------------------------------------------------------

class TestFallbackWhenMissing:
    def test_load_queued_topics_empty(self):
        with patch.object(content_manager, "_read", return_value=""):
            assert content_manager.load_queued_topics() == []

    def test_load_mechanisms_empty(self):
        with patch.object(content_manager, "_read", return_value=""):
            assert content_manager.load_mechanisms() == {}

    def test_load_cultural_frames_empty(self):
        with patch.object(content_manager, "_read", return_value=""):
            assert content_manager.load_cultural_frames() == {}

    def test_recently_used_mechanisms_empty(self):
        with patch.object(content_manager, "_read", return_value=""):
            assert content_manager.recently_used_mechanisms() == []


# ---------------------------------------------------------------------------
# mark_topic_in_progress (checklist A3)
# ---------------------------------------------------------------------------

class TestMarkTopicInProgress:
    def test_queued_to_in_progress(self):
        with patch.object(content_manager, "_read", side_effect=_patch_read(queue=QUEUE_MD)), \
                patch.object(content_manager, "_write") as write_mock:
            result = content_manager.mark_topic_in_progress("返信の罪悪感")
        assert result == 1
        written = write_mock.call_args[0][1]
        assert "| 1 | 返信の罪悪感 | 感情労働 | in_progress |" in written
        assert "| 2 | 人の期待に疲れた夜 | 反芻思考 | queued |" in written

    def test_fuzzy_match_detail_title(self):
        # "Im lặng..." khớp title_vn của detail block dù không phải cột Hiện tượng
        with patch.object(content_manager, "_read", side_effect=_patch_read(queue=QUEUE_MD)), \
                patch.object(content_manager, "_write") as write_mock:
            result = content_manager.mark_topic_in_progress("人の期待に疲れた夜")
        assert result == 2

    def test_no_match_returns_none(self):
        with patch.object(content_manager, "_read", side_effect=_patch_read(queue=QUEUE_MD)), \
                patch.object(content_manager, "_write") as write_mock:
            result = content_manager.mark_topic_in_progress("Chủ đề hoàn toàn ngoài queue")
        assert result is None
        write_mock.assert_not_called()

    def test_already_in_progress_is_noop(self):
        queue = QUEUE_MD.replace(
            "| 1 | 返信の罪悪感 | 感情労働 | queued |",
            "| 1 | 返信の罪悪感 | 感情労働 | in_progress |",
        )
        with patch.object(content_manager, "_read", side_effect=_patch_read(queue=queue)), \
                patch.object(content_manager, "_write") as write_mock:
            result = content_manager.mark_topic_in_progress("返信の罪悪感")
        assert result is None
        write_mock.assert_not_called()

    def test_missing_file_is_silent(self):
        with patch.object(content_manager, "_read", return_value=""), \
                patch.object(content_manager, "_write") as write_mock:
            result = content_manager.mark_topic_in_progress("返信の罪悪感")
        assert result is None
        write_mock.assert_not_called()


# ---------------------------------------------------------------------------
# mark_topic_published (checklist E1/E2/E4)
# ---------------------------------------------------------------------------

EMPTY_DIARY_QUEUE_MD = textwrap.dedent("""\
    # Video Queue

    | # | Working title | Mechanism | Status |
    |---|---|---|---|
    | 1 | 返信の罪悪感 | 感情労働 | in_progress |

    ### 1. 返信の罪悪感
    - **working_title_jp:** 返信できない夜、なぜ心だけが疲れる？
    - **mechanism:** 感情労働
    - **cultural_frame:** 建前/本音

    ## Nhật ký dùng (cập nhật sau mỗi lần đăng)

    | Ngày đăng | Video (queue #) | Cơ chế đã dùng | Frame đã dùng | Video ID |
    |---|---|---|---|---|
    | — | (chưa có video queue nào đăng) | — | — | — |
""")


class TestMarkTopicPublished:
    def test_publish_updates_diary_and_status(self):
        with patch.object(content_manager, "_read", side_effect=_patch_read(queue=QUEUE_MD)), \
                patch.object(content_manager, "_write") as write_mock:
            result = content_manager.mark_topic_published(
                "返信の罪悪感", video_id="xyz789", mechanism="感情労働", frame="建前/本音"
            )
        assert result == 1
        written = write_mock.call_args[0][1]
        # status overview row 1 → published, row 2 untouched
        assert "| 1 | 返信の罪悪感 | 感情労働 | published |" in written
        assert "| 2 | 人の期待に疲れた夜 | 反芻思考 | queued |" in written
        # diary: new row + old rows preserved + header chuẩn 5 cột
        assert "| Video ID |" in written
        assert "#1 — 返信の罪悪感" in written
        assert "xyz789" in written
        assert "課題の分離の話" in written
        assert "abc123" in written

    def test_publish_drops_placeholder_and_writes_dash_for_missing_fields(self):
        with patch.object(content_manager, "_read", side_effect=_patch_read(queue=EMPTY_DIARY_QUEUE_MD)), \
                patch.object(content_manager, "_write") as write_mock:
            result = content_manager.mark_topic_published(
                "返信の罪悪感", video_id="", mechanism="感情労働", frame=""
            )
        assert result == 1
        written = write_mock.call_args[0][1]
        assert "(chưa có" not in written  # placeholder row bị bỏ khi có entry thật
        assert "| 感情労働 | — | — |" in written
        assert "| 1 | 返信の罪悪感 | 感情労働 | published |" in written

    def test_off_queue_topic_skipped(self):
        with patch.object(content_manager, "_read", side_effect=_patch_read(queue=QUEUE_MD)), \
                patch.object(content_manager, "_write") as write_mock:
            result = content_manager.mark_topic_published(
                "Chủ đề ngoài queue", video_id="abc", mechanism="X", frame="Y"
            )
        assert result is None
        write_mock.assert_not_called()

    def test_missing_file_is_silent(self):
        with patch.object(content_manager, "_read", return_value=""), \
                patch.object(content_manager, "_write") as write_mock:
            result = content_manager.mark_topic_published("返信の罪悪感")
        assert result is None
        write_mock.assert_not_called()


# ---------------------------------------------------------------------------
# cultural frame book not counted as research (checklist C3/C4)
# ---------------------------------------------------------------------------

class TestCulturalFrameNotCountedAsResearch:
    def test_cultural_frame_book_not_counted_as_research(self):
        with patch.object(content_manager, "_read", side_effect=_patch_read(cultural_frames=CULTURAL_FRAMES_MD)):
            result = content_manager.cultural_frame_text("建前/本音")
        assert "type: cultural_frame" in result
        assert "KHÔNG tính vào research_min_count" in result
        assert "1 frame chính" in result
