import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    ROOT / 'youtube_pipeline/core/engine.py',
    ROOT / 'youtube_pipeline/resource_analysis.py',
    ROOT / 'youtube_pipeline/resource_pipeline.py',
    ROOT / 'youtube_pipeline/resource_validation.py',
    ROOT / 'youtube_pipeline/resource_prompts.py',
]


def test_all_updated_files_parse():
    for path in FILES:
        ast.parse(path.read_text(encoding='utf-8'))


def test_expected_new_symbols_exist():
    analysis = (ROOT / 'youtube_pipeline/resource_analysis.py').read_text(encoding='utf-8')
    validation = (ROOT / 'youtube_pipeline/resource_validation.py').read_text(encoding='utf-8')
    engine = (ROOT / 'youtube_pipeline/core/engine.py').read_text(encoding='utf-8')
    assert 'def pre_rank_topic_candidates' in analysis
    assert 'def psychology_quality_findings' in validation
    assert 'elapsed_seconds' in engine
