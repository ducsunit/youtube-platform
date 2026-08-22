"""Canonical competitor context shared by the resource-pack flow."""
from __future__ import annotations

from ..competitor_context import COMPETITOR_PATTERNS, COMPETITOR_WRITING_DNA


def competitor_inject_text() -> str:
    """Return the competitor context block for injection into prompts."""
    return COMPETITOR_PATTERNS + "\n" + COMPETITOR_WRITING_DNA
