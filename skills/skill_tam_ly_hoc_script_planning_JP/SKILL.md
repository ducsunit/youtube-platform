---
name: "skill_tam_ly_hoc_script_planning_JP"
description: "Compatibility guide for deriving movements from the symbolic psychology narrative brief."
version: "6.0.0"
---

# Compatibility Planning

> BẮT BUỘC: đọc `skills/CHANNEL_CONSTANTS.md` và claim ledger của run.

Production no longer makes a separate LLM planning call. The narrative brief carries 5-7 movements, each with one psychological job and one new revelation. Derive section metadata deterministically from it.

Legacy planning follows: `sensory recognition → identity tension → symbolic reframe/core question → source-backed revelation(s) → paradox/implication → reflective landing`.

Do not add a movement for a timestamp, metric, example, CTA, or repeated reframe.
