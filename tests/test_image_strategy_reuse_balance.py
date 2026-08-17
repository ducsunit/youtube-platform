from youtube_pipeline.resource_pack.validation import validate_image_strategy


def _strategy(events=49, unique=None):
    unique = events if unique is None else unique
    beats = []
    for i in range(events):
        is_new = i < unique
        beats.append({
            "id": f"B{i:02d}",
            "script_section": f"S{(i // 7) + 1}",
            "visual_information": f"visual {i}",
            "mode": "literal",
            "new_image": is_new,
            "reuse_image_id": None if is_new else "B00",
        })
    return {
        "estimated_unique_images": unique,
        "estimated_total_visual_events": events,
        "density_check": True,
        "no_filler_check": True,
        "opening_visual_contract": {},
        "visual_beats": beats,
    }


def test_high_unique_ratio_is_warning_not_failure():
    value = _strategy(events=49, unique=49)
    contract = {"target_duration_minutes": [9, 11]}
    plan = {"sections": [{}] * 8}
    validate_image_strategy(value, contract, plan)

    assert value["estimated_unique_images"] == 49
    assert value["estimated_total_visual_events"] == 49
    assert value["unique_image_ratio"] == 1.0
    assert any("Unique-image ratio" in w for w in value.get("qa_warnings", []))
    assert value["visual_cost_policy"]["unique_ratio_hard_fail"] is False


def test_lower_unique_ratio_is_allowed_with_warning():
    value = _strategy(events=49, unique=30)
    contract = {"target_duration_minutes": [9, 11]}
    plan = {"sections": [{}] * 8}
    validate_image_strategy(value, contract, plan)

    assert value["estimated_unique_images"] == 30
    assert value["unique_image_ratio"] < 0.65
    assert any("continuity" in w for w in value.get("qa_warnings", []))
