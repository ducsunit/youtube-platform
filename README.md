# V17 Dynamic Visual Budget Update

Apply this patch over the current project baseline.

Updated:
- `youtube_pipeline/resource_pack/validation.py`
- `youtube_pipeline/resource_pack/prompts.py`
- `tests/test_image_strategy_reuse_balance.py`

Behavior change:
- Unique-image ratio is now dynamic and is NOT a hard quota.
- 70–90% is only a soft target range.
- 100% unique images are allowed when content genuinely needs distinct visuals.
- Low/high ratios generate warnings instead of failing `image_strategy`.
- The validator no longer rewrites AI visual decisions automatically just to hit an 85% quota.
- `minimum_visual_events` remains a hard coverage floor.

This prevents `image_strategy failed after 3 attempts` solely because the model generated too many unique images.
