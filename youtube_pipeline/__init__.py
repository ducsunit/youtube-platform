"""Stateful AI pipeline for YouTube script production.

Flow hiện tại: psychology-first 22-stage `resource_pipeline.ResourcePackPipeline`.
`YouTubePipeline`/`FlowState` dưới đây là LEGACY (flow 7-step cũ) — giữ nguyên
vì CLI entrypoint `youtube-pipeline` (pyproject.toml → cli.py) còn dùng.
"""

import logging

from .domain.models import AuditReport, FlowState, Proposal, ReviewResult
from .pipeline import YouTubePipeline  # LEGACY — xem docstring module

logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = ["AuditReport", "FlowState", "Proposal", "ReviewResult", "YouTubePipeline"]
