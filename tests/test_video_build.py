import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from youtube_pipeline.timeline import build_timeline
from youtube_pipeline.video_build import (
    ANIM_MODES,
    build_marks_tsv,
    build_video_script,
    clip_status,
    find_clip,
    images_digest,
    missing_images,
    render_rows,
    render_video,
)

# --- Fixtures nhỏ (compact: 3 section, 9 beat, có reuse liên tiếp B02/B03) -----


def _sections():
    rows = [
        {"index": i, "id": "S%d" % i, "chars": chars, "file": "%02d_section-%02d.txt" % (i, i),
         "text": "本文 %d です。" % i}
        for i, chars in enumerate([120, 110, 130], start=1)
    ]
    return {
        "section_policy": {"cpm_min": 380, "cpm_max": 400, "estimated_min_seconds": 50, "estimated_max_seconds": 60},
        "sections": rows,
        "total_chars": 360,
    }


def _strategy():
    beats = []
    index = 0
    for section_index, count in enumerate([4, 3, 2], start=1):
        for _ in range(count):
            index += 1
            beats.append({"id": "B%02d" % index, "script_section": "S%d" % section_index, "visual_information": "info %d" % index})
    return {"visual_beats": beats}


def _storyboard(strategy):
    rows = []
    image_index = 0
    for index, beat in enumerate(strategy["visual_beats"], start=1):
        new_image = index not in (2, 3)  # B02, B03 reuse liên tiếp
        if new_image:
            image_index += 1
        rows.append({
            "event_id": "E%02d" % index,
            "beat_id": beat["id"],
            "image_id": "IMG-%02d" % image_index,
            "new_image": new_image,
            "motion": "motion %d" % index,
            "visual_information": beat["visual_information"],
        })
    return rows


def _planning():
    return {"sections": [
        {"id": "S1", "segment_function": "recognition"},
        {"id": "S2", "segment_function": "explanation"},
        {"id": "S3", "segment_function": "cta"},
    ]}


def _meta(duration=100.0):
    strategy = _strategy()
    _, meta = build_timeline(
        _storyboard(strategy), strategy, _sections(), _planning(),
        duration=duration, audio_file="merged.mp3",
    )
    return meta


def _load_tool():
    path = build_video_script()
    if not path.is_file():
        raise unittest.SkipTest("youtube_pipeline/build-video.py chưa có — bỏ qua test tích hợp tool")
    spec = importlib.util.spec_from_file_location("youtube_pipeline_build_vb", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RenderRowsTest(unittest.TestCase):
    def test_rows_parseable_contiguous_with_consecutive_reuse(self):
        """prompts-build.py sinh ra phải qua được parse_segments của tool:
        đủ row, cửa sổ liền mạch, reuse liên tiếp không vỡ."""
        meta = _meta()
        content = render_rows(meta["events"], meta["sections"])
        self.assertIn("REUSE_BEATS = {}", content)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "prompts-build.py").write_text(content, encoding="utf-8")
            tool = _load_tool()
            segs, by_beat = tool.parse_segments(root)
            self.assertEqual(len(segs), len(meta["events"]))
            self.assertEqual(set(b for _, b, _, _ in segs), {e["beat_id"] for e in meta["events"]})
            # reuse beat vẫn có segment riêng (không chồng lấn)
            self.assertIn("B02", by_beat)
            self.assertIn("B03", by_beat)
            # tất cả cửa sổ đều giây nguyên (tool sec() chỉ đọc int)
            for _, _, s, e in segs:
                self.assertEqual(s, int(s))
                self.assertEqual(e, int(e))

    def test_rows_window_equals_timeline_section_windows(self):
        """Tổng est theo sections phải ≈ cửa sổ section thật (scale ≈ 1.0)."""
        meta = _meta()
        content = render_rows(meta["events"], meta["sections"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "prompts-build.py").write_text(content, encoding="utf-8")
            tool = _load_tool()
            segs, _ = tool.parse_segments(root)
            bounds = {s["id"]: (s["start_s"], s["end_s"]) for s in meta["sections"]}
            est_by_section = {s["id"]: 0.0 for s in meta["sections"]}
            for _, beat, s, e in segs:
                section = next(s["id"] for s in meta["sections"] for ev in meta["events"]
                               if ev["beat_id"] == beat and ev["section"] == s["id"])
                est_by_section[section] += (e - s)
            for section in bounds:
                span = bounds[section][1] - bounds[section][0]
                # sai số do làm tròn giây: ≤ 1s mỗi event trong section
                events_in_section = sum(1 for ev in meta["events"] if ev["section"] == section)
                self.assertLessEqual(abs(est_by_section[section] - span), events_in_section + 1)


class MarksTsvTest(unittest.TestCase):
    def test_first_sentence_and_count(self):
        sections = [
            {"id": "S1", "file": "01_section-01.txt", "text": "最初の文です。二文目。"},
            {"id": "S2", "file": "02_section-02.txt", "text": "次の段落の最初の文です"},
            {"id": "S3", "file": "03_section-03.txt", "text": "第三セクション。"},
        ]
        tsv = build_marks_tsv(sections)
        lines = [line for line in tsv.splitlines() if line.strip()]
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0], "01_section-01\t最初の文です。")
        self.assertEqual(lines[2], "03_section-03\t第三セクション。")
        # câu không có dấu kết thúc → fallback
        self.assertTrue(lines[1].startswith("02_section-02\t次の段落の最初の文です"))


class RenderVideoTest(unittest.TestCase):
    """render_video: options mới (animation/dry_run/subtitles) → command build-video.py."""

    @staticmethod
    def _run(options, video_exists=False, returncode=0):
        from youtube_pipeline import video_build as vb

        with tempfile.TemporaryDirectory() as tmp:
            build_dir = Path(tmp)
            if video_exists:
                (build_dir / "video-final.mp4").write_bytes(b"x")
            with mock.patch.object(vb.subprocess, "run") as run:
                run.return_value = mock.Mock(returncode=returncode, stdout="out", stderr="")
                ok, output = vb.render_video(build_dir, options)
            return run.call_args.args[0], ok, output

    def test_animation_flag_replaces_motion(self):
        command, ok, _output = self._run(
            {"animation": "zoom-out", "resolution": [1920, 1080]}, video_exists=True
        )
        self.assertIn("--animation", command)
        self.assertIn("zoom-out", command)
        self.assertNotIn("--motion", command)
        self.assertIn("--resolution", command)
        self.assertTrue(ok)

    def test_motion_backward_compat(self):
        command, _ok, _output = self._run({"motion": True}, video_exists=True)
        self.assertIn("--motion", command)
        self.assertNotIn("--animation", command)

    def test_dry_run_ok_without_video_file(self):
        command, ok, _output = self._run({"dry_run": True})
        self.assertIn("--dry-run", command)
        self.assertTrue(ok)  # dry-run không tạo video-final.mp4

    def test_render_fails_without_video_file(self):
        _command, ok, _output = self._run({})
        self.assertFalse(ok)

    def test_subtitles_only_when_rendering(self):
        command, _ok, _output = self._run({"subtitles": True}, video_exists=True)
        self.assertIn("--subtitles", command)
        # GUI: không đốt phụ đề khi xem trước (dry-run)
        command, _ok, _output = self._run({"subtitles": True, "dry_run": True})
        self.assertNotIn("--subtitles", command)
        self.assertIn("--dry-run", command)

    def test_anim_modes_cover_gui_choices(self):
        self.assertEqual(
            ANIM_MODES, ("none", "zoom", "zoom-out", "pan-h", "pan-v", "auto")
        )


class LogoCleanupTest(unittest.TestCase):
    def test_invalid_mode_is_rejected(self):
        from youtube_pipeline.video.logo_cleanup import _filter

        with self.assertRaises(ValueError):
            _filter({"x": 0, "y": 0, "width": 10, "height": 10}, "inpaint")

    def test_filter_contains_fixed_watermark_region(self):
        from youtube_pipeline.video.logo_cleanup import _filter

        value = _filter({"x": 1120, "y": 570, "width": 120, "height": 75}, "delogo")
        self.assertIn("x=1120", value)
        self.assertIn("y=570", value)
        self.assertIn("w=120", value)
        self.assertIn("h=75", value)


class ImagesDigestTest(unittest.TestCase):
    def test_digest_changes_when_images_appear(self):
        with tempfile.TemporaryDirectory() as tmp:
            build_dir = Path(tmp) / "video-build"
            self.assertIsNone(images_digest(build_dir))
            images = build_dir / "images"
            images.mkdir(parents=True)
            (images / "IMG-01.jpg").write_bytes(b"a")
            first = images_digest(build_dir)
            self.assertIsNotNone(first)
            self.assertEqual(images_digest(build_dir), first)  # ổn định
            (build_dir / "import").mkdir()
            (build_dir / "import" / "IMG-02.png").write_bytes(b"b")
            self.assertNotEqual(images_digest(build_dir), first)
            (images / "IMG-01.jpg").write_bytes(b"c")  # thay ảnh (gen lại)
            self.assertNotEqual(images_digest(build_dir), first)

    def test_missing_images_lists_needed_ids(self):
        events = [
            {"image_id": "IMG-01"}, {"image_id": "IMG-01"},
            {"image_id": "IMG-02"}, {"image_id": "IMG-03"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            build_dir = Path(tmp)
            (build_dir / "images").mkdir()
            (build_dir / "images" / "IMG-01.jpg").write_bytes(b"x")
            self.assertEqual(missing_images(build_dir, events), ["IMG-02", "IMG-03"])


class ClipLookupTest(unittest.TestCase):
    """Clip image-to-video: lookup + status — thông tin, không gate."""

    def test_find_clip_resolves_mp4_in_clips_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            build_dir = Path(tmp)
            clips = build_dir / "clips"
            clips.mkdir()
            (clips / "IMG-01.mp4").write_bytes(b"fake")
            self.assertEqual(find_clip(build_dir, "IMG-01"), clips / "IMG-01.mp4")
            self.assertIsNone(find_clip(build_dir, "IMG-99"))

    def test_clip_status_present_missing_dedupe_first_appearance(self):
        events = [
            {"image_id": "IMG-01"}, {"image_id": "IMG-01"},
            {"image_id": "IMG-02"}, {"image_id": "IMG-03"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            build_dir = Path(tmp)
            clips = build_dir / "clips"
            clips.mkdir()
            (clips / "IMG-01.mp4").write_bytes(b"x")
            (clips / "IMG-03.webm").write_bytes(b"x")
            status = clip_status(build_dir, events)
            self.assertEqual(status["present"], ["IMG-01", "IMG-03"])
            self.assertEqual(status["missing"], ["IMG-02"])

    def test_clip_status_empty_when_no_clips_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            status = clip_status(Path(tmp), [{"image_id": "IMG-01"}])
            self.assertEqual(status, {"present": [], "missing": ["IMG-01"]})


class EngineClipTest(unittest.TestCase):
    """Engine (build-video.py): render_segment_clip dùng -stream_loop/-an, không
    zoompan; dry-run ưu tiên tên clip."""

    def test_render_segment_clip_flags(self):
        tool = _load_tool()
        with mock.patch.object(tool.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0)
            tool.render_segment_clip("clip.mp4", "out.mp4", 3.0, (1280, 720))
        args = run.call_args.args[0]
        self.assertIn("-stream_loop", args)
        self.assertIn("-1", args)
        self.assertIn("-an", args)
        self.assertIn("-t", args)
        self.assertIn("-i", args)
        self.assertNotIn("-loop", args)
        self.assertNotIn("zoompan", args)
        self.assertEqual(args[args.index("-i") + 1], "clip.mp4")

    def test_find_clip_preferred_in_dry_run_table(self):
        tool = _load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "clips").mkdir()
            (root / "clips" / "IMG-01.mp4").write_bytes(b"x")
            self.assertEqual(tool.find_clip(root, "IMG-01"), str(root / "clips" / "IMG-01.mp4"))
            self.assertIsNone(tool.find_clip(root, "IMG-99"))


class EngineLegacyRemovedTest(unittest.TestCase):
    """Engine trong package: quote-mode/IMG-MAPPING (video 4/5 cũ) đã bị dọn —
    flow mới map beat->chunk theo thời gian, không đọc script.txt."""

    def test_legacy_mapping_helpers_removed(self):
        tool = _load_tool()
        for name in ("parse_beat_quotes", "map_beats_to_chunks",
                     "import_images_from_mapping", "norm"):
            self.assertFalse(hasattr(tool, name), "%s còn sót trong engine" % name)
        # helpers flow mới web vẫn dùng
        self.assertTrue(hasattr(tool, "map_beats_to_chunks_by_time"))
        self.assertTrue(hasattr(tool, "import_images"))
        self.assertTrue(hasattr(tool, "srt_to_ass_offset"))
        self.assertTrue(hasattr(tool, "render_segment"))


class TimelineMetaRegressionTest(unittest.TestCase):
    """Meta mới (sections/events) — nguồn duy nhất cho video_build."""

    def test_meta_has_sections_and_events_with_real_windows(self):
        meta = _meta(duration=100.0)
        self.assertEqual(len(meta["sections"]), 3)
        self.assertEqual(len(meta["events"]), 9)
        self.assertEqual(meta["sections"][0]["id"], "S1")
        self.assertAlmostEqual(meta["sections"][2]["end_s"], 100.0, places=2)
        first = meta["events"][0]
        self.assertEqual(first["event_id"], "E01")
        self.assertEqual(first["section"], "S1")
        self.assertAlmostEqual(first["start_s"], 0.0, places=2)
        # cửa sổ event trong section phải liền mạch
        for section in meta["sections"]:
            events = [ev for ev in meta["events"] if ev["section"] == section["id"]]
            for previous, current in zip(events, events[1:]):
                self.assertAlmostEqual(previous["end_s"], current["start_s"], places=2)


class BuildServicePackTest(unittest.TestCase):
    """build_service.build_pack (Flow 3) — tái sinh pack, dọn di sản lần dựng cũ."""

    @staticmethod
    def _make_run(root: Path, meta: dict) -> Path:
        """Cây artifact nguồn + audio ghép + ảnh đủ — trả run_dir (layout API)."""
        import json

        run_dir = root / "runs" / "test-run"
        (run_dir / "script").mkdir(parents=True)
        (run_dir / "visuals").mkdir(parents=True)
        strategy = _strategy()
        (run_dir / "script" / "planning.json").write_text(
            json.dumps(_planning(), ensure_ascii=False), encoding="utf-8")
        (run_dir / "script" / "script.txt").write_text("本文です。", encoding="utf-8")
        (run_dir / "script" / "sections.json").write_text(
            json.dumps(_sections(), ensure_ascii=False), encoding="utf-8")
        (run_dir / "visuals" / "strategy.json").write_text(
            json.dumps(strategy, ensure_ascii=False), encoding="utf-8")
        (run_dir / "visuals" / "storyboard.json").write_text(
            json.dumps(_storyboard(strategy), ensure_ascii=False), encoding="utf-8")
        audio = run_dir / "audio"
        audio.mkdir()
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
             "-i", "anullsrc=r=44100:cl=mono", "-t", "100",
             "-c:a", "libmp3lame", "-b:a", "32k", str(audio / "merged.mp3")],
            check=True, capture_output=True, text=True, timeout=60,
        )
        images = run_dir / "video-build" / "images"
        images.mkdir(parents=True)
        for image_id in sorted({e["image_id"] for e in meta["events"]}):
            (images / (image_id + ".jpg")).write_bytes(b"fake")
        return run_dir

    def test_stale_audio_in_pack_cleaned_before_split(self):
        """File audio thừa trong pack audio/ (di sản) phải bị dọn — nếu không
        build-video.py đếm audio != section và FAIL ngay."""
        from youtube_pipeline import build_service

        if not shutil.which("ffmpeg"):
            raise unittest.SkipTest("ffmpeg chưa có — bỏ qua test cắt audio")
        with tempfile.TemporaryDirectory() as tmp:
            meta = _meta(duration=100.0)
            run_dir = self._make_run(Path(tmp), meta)
            stale = run_dir / "video-build" / "audio" / "merged.mp3"
            stale.parent.mkdir(parents=True)
            stale.write_bytes(b"legacy copy from old stage")
            report = build_service.build_pack(run_dir, {"render": False})
            self.assertEqual(report["status"], "PACK_READY")
            remaining = sorted(p.name for p in (run_dir / "video-build" / "audio").glob("*.mp3"))
            self.assertNotIn("merged.mp3", remaining)
            self.assertEqual(len(remaining), meta["section_count"])

    def test_build_pack_does_not_write_script_txt(self):
        """script.txt không còn nằm trong pack — video quyết định qua pipeline,
        không qua file chép tay (fallback kịch bản cũ đã bị bỏ)."""
        from youtube_pipeline import build_service

        if not shutil.which("ffmpeg"):
            raise unittest.SkipTest("ffmpeg chưa có — bỏ qua test cắt audio")
        with tempfile.TemporaryDirectory() as tmp:
            meta = _meta(duration=100.0)
            run_dir = self._make_run(Path(tmp), meta)
            report = build_service.build_pack(run_dir, {"render": False})
            self.assertEqual(report["status"], "PACK_READY")
            self.assertFalse((run_dir / "video-build" / "script.txt").exists())
            self.assertNotIn("script.txt", report["resources"])
            self.assertIn("prompts-build.py", report["resources"])

    def test_build_pack_works_without_script_txt_artifact(self):
        """Thiếu artifact script/script.txt không chặn Dựng — nó không còn là input."""
        from youtube_pipeline import build_service

        if not shutil.which("ffmpeg"):
            raise unittest.SkipTest("ffmpeg chưa có — bỏ qua test cắt audio")
        with tempfile.TemporaryDirectory() as tmp:
            meta = _meta(duration=100.0)
            run_dir = self._make_run(Path(tmp), meta)
            (run_dir / "script" / "script.txt").unlink()
            report = build_service.build_pack(run_dir, {"render": False})
            self.assertEqual(report["status"], "PACK_READY")
            self.assertFalse((run_dir / "video-build" / "script.txt").exists())

    def test_clip_status_reported_but_never_blocks_pack(self):
        """Clip image-to-video là lớp ưu tiên: clip thiếu → vẫn PACK_READY; có
        clip → present + dòng 'clips/ (N file)' trong resources (thông tin)."""
        from youtube_pipeline import build_service

        if not shutil.which("ffmpeg"):
            raise unittest.SkipTest("ffmpeg chưa có — bỏ qua test cắt audio")
        with tempfile.TemporaryDirectory() as tmp:
            meta = _meta(duration=100.0)
            run_dir = self._make_run(Path(tmp), meta)
            report = build_service.build_pack(run_dir, {"render": False})
            self.assertEqual(report["status"], "PACK_READY")
            self.assertEqual(report["clips"]["present"], [])
            self.assertEqual(len(report["clips"]["missing"]), meta["unique_images"])
            self.assertNotIn("clips/ (1 file)", report["resources"])

            clips = run_dir / "video-build" / "clips"
            clips.mkdir(exist_ok=True)
            (clips / "IMG-01.mp4").write_bytes(b"fake")
            report = build_service.build_pack(run_dir, {"render": False})
            self.assertEqual(report["status"], "PACK_READY")
            self.assertEqual(report["clips"]["present"], ["IMG-01"])
            self.assertNotIn("IMG-01", report["clips"]["missing"])
            self.assertIn("clips/ (1 file)", report["resources"])

    def test_check_assets_reports_clips_without_gating(self):
        from youtube_pipeline import build_service

        if not shutil.which("ffmpeg"):
            raise unittest.SkipTest("ffmpeg chưa có — fixture _make_run cần tạo audio")
        with tempfile.TemporaryDirectory() as tmp:
            meta = _meta(duration=100.0)
            run_dir = self._make_run(Path(tmp), meta)
            clips = run_dir / "video-build" / "clips"
            clips.mkdir()
            (clips / "IMG-02.mp4").write_bytes(b"fake")
            assets = build_service.check_assets(run_dir)
            self.assertTrue(assets["images_ready"])
            self.assertEqual(assets["clips"]["present"], ["IMG-02"])
            self.assertTrue(assets["clips"]["missing"])  # IMG còn lại chưa có clip
            self.assertEqual(set(assets["pack_files"]), {"prompts_build", "marks_tsv"})

    def test_check_assets_pack_files_has_no_script_txt(self):
        from youtube_pipeline import build_service

        if not shutil.which("ffmpeg"):
            raise unittest.SkipTest("ffmpeg chưa có — fixture _make_run cần tạo audio")
        with tempfile.TemporaryDirectory() as tmp:
            meta = _meta(duration=100.0)
            run_dir = self._make_run(Path(tmp), meta)
            (run_dir / "script" / "script.txt").unlink()
            assets = build_service.check_assets(run_dir)
            self.assertTrue(assets["pipeline_ready"])
            self.assertEqual(set(assets["pack_files"]), {"prompts_build", "marks_tsv"})
            self.assertNotIn("script/script.txt", assets["missing_artifacts"])


class ImportWithoutAudioTest(unittest.TestCase):
    """Đổi tên ảnh phải chạy được TRƯỚC khi có audio.

    Thứ tự IMG chỉ phụ thuộc storyboard; chỉ mốc thời gian mới cần thời lượng
    audio. Trước đây import đọc prompts-build.py (chỉ sinh ra khi đã có audio)
    nên gen ảnh xong vẫn phải chờ TTS mới đổi tên được. Không cần ffmpeg.
    """

    @staticmethod
    def _make_run_no_audio(root: Path) -> Path:
        """Artifact nguồn đủ cho timeline, KHÔNG audio, KHÔNG prompts-build.py."""
        import json

        run_dir = root / "runs" / "no-audio"
        (run_dir / "script").mkdir(parents=True)
        (run_dir / "visuals").mkdir(parents=True)
        strategy = _strategy()
        (run_dir / "script" / "planning.json").write_text(
            json.dumps(_planning(), ensure_ascii=False), encoding="utf-8")
        (run_dir / "script" / "script.txt").write_text("本文です。", encoding="utf-8")
        (run_dir / "script" / "sections.json").write_text(
            json.dumps(_sections(), ensure_ascii=False), encoding="utf-8")
        (run_dir / "visuals" / "strategy.json").write_text(
            json.dumps(strategy, ensure_ascii=False), encoding="utf-8")
        (run_dir / "visuals" / "storyboard.json").write_text(
            json.dumps(_storyboard(strategy), ensure_ascii=False), encoding="utf-8")
        return run_dir

    @staticmethod
    def _fake_images(folder: Path, count: int) -> None:
        """Ảnh giả đặt tên có số thứ tự (đường map chính xác nhất)."""
        folder.mkdir(parents=True, exist_ok=True)
        for i in range(1, count + 1):
            (folder / ("gen_%02d_clean.png" % i)).write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 40)

    def test_img_order_computed_without_audio(self):
        from youtube_pipeline import build_service

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._make_run_no_audio(Path(tmp))
            self.assertIsNone(build_service.find_audio_file(run_dir / "audio"))
            order = build_service._img_order_for_import(run_dir)
            # fixture: 9 beat, B02/B03 reuse -> 7 ảnh cần gen
            self.assertEqual(order, ["IMG-0%d" % i for i in range(1, 8)])

    def test_order_matches_canonical_from_prompts_build(self):
        """Thứ tự tính khi chưa có audio phải TRÙNG canonical_img_order — lệch là
        ảnh bị gán sai IMG."""
        from youtube_pipeline import build_service

        tool = _load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._make_run_no_audio(Path(tmp))
            order_no_audio = build_service._img_order_for_import(run_dir)
            build_dir = run_dir / "video-build"
            build_dir.mkdir(parents=True, exist_ok=True)
            meta = _meta(duration=137.5)  # thời lượng lẻ: chỉ ảnh hưởng mốc thời gian
            (build_dir / "prompts-build.py").write_text(
                render_rows(meta["events"], meta["sections"]), encoding="utf-8")
            self.assertEqual(order_no_audio, tool.canonical_img_order(str(build_dir)))

    def test_preview_then_apply_without_audio(self):
        from youtube_pipeline import build_service

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._make_run_no_audio(Path(tmp))
            source = Path(tmp) / "downloads"
            self._fake_images(source, 7)

            preview = build_service.import_pack_images(run_dir, str(source), apply=False)
            self.assertTrue(preview["ok"], preview.get("error"))
            self.assertEqual(len(preview["mapping"]), 7)
            self.assertEqual(preview["mapping"][0]["img"], "IMG-01")
            self.assertEqual(preview["mapping"][0]["file"], "gen_01_clean.png")
            # preview không được di chuyển ảnh (manifest khung được ghi thêm)
            self.assertEqual(len(list(source.glob("*.png"))), 7)
            self.assertFalse((run_dir / "video-build" / "images").exists())

            applied = build_service.import_pack_images(run_dir, str(source), apply=True)
            self.assertTrue(applied["ok"], applied.get("error"))
            got = sorted(p.name for p in (run_dir / "video-build" / "images").iterdir())
            self.assertEqual(got, ["IMG-0%d.png" % i for i in range(1, 8)])
            self.assertEqual(list(source.glob("*.png")), [])  # move, không copy

    def test_apply_still_blocked_when_images_dir_not_empty(self):
        """Bảo vệ ghi đè ảnh cũ vẫn còn nguyên khi đi đường không-audio."""
        from youtube_pipeline import build_service

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._make_run_no_audio(Path(tmp))
            images = run_dir / "video-build" / "images"
            images.mkdir(parents=True)
            (images / "IMG-01.png").write_bytes(b"anh cu")
            source = Path(tmp) / "downloads"
            self._fake_images(source, 7)
            result = build_service.import_pack_images(run_dir, str(source), apply=True)
            self.assertFalse(result["ok"])
            self.assertIn("da co", (result.get("error") or "").lower())
            self.assertEqual((images / "IMG-01.png").read_bytes(), b"anh cu")

    def test_missing_artifacts_falls_back_to_prompts_build_error(self):
        """Run chưa qua pipeline: không tính được thứ tự -> vẫn báo lỗi cũ, không crash."""
        from youtube_pipeline import build_service

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "runs" / "empty"
            run_dir.mkdir(parents=True)
            self.assertEqual(build_service._img_order_for_import(run_dir), [])
            source = Path(tmp) / "downloads"
            self._fake_images(source, 3)
            result = build_service.import_pack_images(run_dir, str(source), apply=False)
            self.assertFalse(result["ok"])
            self.assertIn("prompts-build.py", result.get("error") or "")

    def test_img_order_flag_rejects_bad_values(self):
        """--img-order phải validate: id sai định dạng / trùng lặp -> exit != 0."""
        from youtube_pipeline import build_service

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._make_run_no_audio(Path(tmp))
            build_dir = run_dir / "video-build"
            build_dir.mkdir(parents=True, exist_ok=True)
            source = Path(tmp) / "downloads"
            self._fake_images(source, 3)
            base = [build_service.tool_python(), str(build_video_script()), str(build_dir),
                    "--import-images", str(source), "--img-order"]
            for bad in ("IMG-01,NOPE-02", "IMG-01,IMG-01,IMG-02", "01,02"):
                result = subprocess.run(base + [bad], capture_output=True, text=True, timeout=60)
                self.assertNotEqual(result.returncode, 0, "phải từ chối: %s" % bad)


if __name__ == "__main__":
    unittest.main()
