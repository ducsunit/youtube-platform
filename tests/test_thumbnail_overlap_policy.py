from youtube_pipeline.resource_pack.validation import title_overlap_percent, thumbnail_text_duplication, validate_thumbnail


def test_short_japanese_keyword_overlap_is_not_a_hard_failure():
    title = "なぜ返信が遅いだけで嫌われたと思うのか"
    thumb = "嫌われた？"
    assert title_overlap_percent(title, thumb) > 35
    duplicated, _ = thumbnail_text_duplication(title, thumb)
    assert duplicated is False


def test_long_title_copy_is_hard_failure():
    title = "返信が遅いだけで嫌われたと思う人へ"
    thumb = "返信が遅いだけで嫌われた"
    duplicated, reason = thumbnail_text_duplication(title, thumb)
    assert duplicated is True
    assert reason


def test_validate_thumbnail_returns_overlap_warning_not_issue():
    value = {
        "concepts": [{"mode": "SELF_RECOGNITION", "text": "嫌われた？"}],
        "chosen_mode": "SELF_RECOGNITION",
        "thumbnail_text": "嫌われた？",
        "text_color": "#FFD700",
        "background_color": "#1A2332",
        "image_prompt": "16:9 flat illustrated cartoon, thick black outline, navy background, no text, fictional character",
        "negative_prompt": "watermark",
        "overlay_spec": {"lines": 1},
    }
    qa = validate_thumbnail(value, "なぜ返信が遅いだけで嫌われたと思うのか")
    assert qa["passed"] is True
    assert qa["warnings"]
    assert not qa["issues"]
