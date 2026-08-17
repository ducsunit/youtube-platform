import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from youtube_pipeline.cli import _read_channel_json, _read_state, build_parser
from youtube_pipeline.models import ValidationError


class CliInputTests(unittest.TestCase):
    def test_reads_channel_json_from_env(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "channel.json"
            path.write_text(
                json.dumps({"channel": "Kênh lịch sử"}, ensure_ascii=False),
                encoding="utf-8",
            )
            args = build_parser().parse_args([])
            with patch.dict(
                os.environ, {"YOUTUBE_CHANNEL_DATA_FILE": str(path)}, clear=False
            ):
                state = _read_state(args, build_parser())
            self.assertEqual(
                json.loads(state.raw_youtube_data), {"channel": "Kênh lịch sử"}
            )

    def test_rejects_invalid_channel_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "channel.json"
            path.write_text("not-json", encoding="utf-8")
            with self.assertRaises(ValidationError):
                _read_channel_json(path)

    def test_command_line_input_overrides_env_file(self):
        args = build_parser().parse_args(["--input", "Dữ liệu trực tiếp"])
        with patch.dict(
            os.environ, {"YOUTUBE_CHANNEL_DATA_FILE": "missing.json"}, clear=False
        ):
            state = _read_state(args, build_parser())
        self.assertEqual(state.raw_youtube_data, "Dữ liệu trực tiếp")


if __name__ == "__main__":
    unittest.main()
