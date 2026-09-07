"""Stateful AI pipeline for YouTube script production.

Flow production hiện tại: UI/API dùng `resource_pack.pipeline.ResourcePackPipeline`.
`YouTubePipeline`/`FlowState` dưới đây là LEGACY (flow 7-step cũ) — giữ nguyên
chỉ để tương thích import cũ; không thêm feature hoặc gọi nó từ UI/API.
"""

import logging

from .channel_context import ChannelContext
from .domain.models import AuditReport, FlowState, Proposal, ReviewResult
from .pipeline import YouTubePipeline  # LEGACY — xem docstring module


# ChannelContext is the Phase 1 boundary for channel-scoped production flows.

logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = ["AuditReport", "ChannelContext", "FlowState", "Proposal", "ReviewResult", "YouTubePipeline"]
