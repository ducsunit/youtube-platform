"""Stateful AI pipeline for YouTube script production.

Flow production hiện tại: UI/API dùng `resource_pack.pipeline.ResourcePackPipeline`.
`YouTubePipeline`/`FlowState` dưới đây là LEGACY (flow 7-step cũ) — giữ nguyên
chỉ để tương thích import cũ; không thêm feature hoặc gọi nó từ UI/API.
"""

import logging

from .domain.models import AuditReport, FlowState, Proposal, ReviewResult
from .pipeline import YouTubePipeline  # LEGACY — xem docstring module

logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = ["AuditReport", "FlowState", "Proposal", "ReviewResult", "YouTubePipeline"]
