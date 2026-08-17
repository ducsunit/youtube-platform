from youtube_pipeline.resource_pack.validation import normalize_state_advance


def test_normalize_state_advance_arrow_variants():
    assert normalize_state_advance("BEFORE: A → AFTER: B") == "A -> B"
    assert normalize_state_advance("A -> B") == "A -> B"
    assert normalize_state_advance({"before": "A", "after": "B"}) == "A -> B"


def test_normalize_state_advance_keeps_invalid_unstructured_text():
    assert normalize_state_advance("viewer understands the mechanism") == "viewer understands the mechanism"
