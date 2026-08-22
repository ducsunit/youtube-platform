import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_retry_policy_symbols_and_metadata():
    engine = (ROOT / 'youtube_pipeline/core/engine.py').read_text(encoding='utf-8')
    assert 'def _classify_retry' in engine
    assert 'retry_count' in engine
    assert 'failure_categories' in engine
    assert 'deterministic failure (no blind retry)' in engine
    assert 'model_validation' in engine


def test_all_updated_files_parse():
    files = [
        ROOT / 'youtube_pipeline/core/engine.py',
        ROOT / 'youtube_pipeline/resource_analysis.py',
        ROOT / 'youtube_pipeline/resource_pipeline.py',
        ROOT / 'youtube_pipeline/resource_validation.py',
        ROOT / 'youtube_pipeline/resource_prompts.py',
    ]
    for path in files:
        ast.parse(path.read_text(encoding='utf-8'))
