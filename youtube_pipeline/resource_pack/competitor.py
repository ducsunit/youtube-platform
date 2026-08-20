"""Canonical competitor context shared by the resource-pack flow."""
from __future__ import annotations

from ..competitor_context import PSYCHTOONS_PATTERNS, PSYCHTOONS_WRITING_DNA


def competitor_inject_text() -> str:
    """Return the competitor context block for injection into prompts."""
    return PSYCHTOONS_PATTERNS + "\n" + PSYCHTOONS_WRITING_DNA
