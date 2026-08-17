# PsychToons-Inspired Psychology-First Production Guide

## Purpose

This document is the **format reference** for the Japanese psychology channel. It is not a mandatory
story template and must not be interpreted as a 7-part screenplay.

The target is:

> **Psychology is the content spine. Behavioral examples are recognition/evidence devices.**

PsychToons is used as a reference for **recognition, reframe, pacing, and packaging**, not as a reason
to copy wording, childhood scenes, or a fixed section count.

## Core Viewer Journey

```text
Behavior recognition
      ↓
Misconception
      ↓
Early reframe
      ↓
Core WHY question
      ↓
Mechanism
      ↓
Inner process
      ↓
Function / contradiction / cost
      ↓
Integration
      ↓
Self-understanding
```

The route may compress or expand these jobs. There is **no mandatory origin story, childhood montage,
triple denial, exact 7-part structure, or fixed number of solutions**.

## Hook Standard

Target timing from `skills/CHANNEL_CONSTANTS.md`:

- 0–8s: recognizable behavior/type.
- 8–18s: misconception or tension.
- 18–35s: first real reframe/insight.
- 35–55s: core psychological question.

A short situation is allowed, but it must pivot quickly:

```text
recognition → psychological meaning → WHY
```

Bad:

```text
夜、LINEを送る
→ 既読がつかない
→ スマホを見る
→ また確認する
→ 眠れない
→ 朝になる
→ psychology explanation
```

Good:

```text
「返信が少し遅いだけで、嫌われたと思ってしまう人がいます。」
→ 「問題は返信を待つことではありません。」
→ 「なぜ、相手の反応を自分の価値として読んでしまうのでしょうか。」
```

## Section Rule

Every section must have one psychological job:

- `recognition`
- `misconception_reframe`
- `mechanism`
- `inner_world`
- `contradiction`
- `origin_development` — optional only
- `strength_cost`
- `integration`
- `practical_shift` — optional only
- `insight_landing`

A section is invalid when its main purpose is to continue a story.

## Example Rule

A micro-example may:

- identify a behavior;
- make an abstract mechanism concrete;
- show a recognizable thought/response;
- create a brief contrast.

It must normally return to analysis within 1–2 sentences and never carry the next section.

**Independence test:**

> Delete every example. If the psychological argument collapses, the outline/script is too story-dependent.

## PsychToons Reframe Signature

Use the underlying device rather than copying wording:

```text
「あなたはXなのではありません。」
→ 「実際に起きているのはYです。」
→ 「この違いが重要です。」
```

At least two meaningful reframe landings are preferred:

1. early after misconception;
2. near the ending.

The reframe must explain a real psychological distinction. Do not use empty reassurance or identity
flattery.

## Semantic Review Gate

The `review` stage is the main semantic format gate.

| Dimension | Target |
|---|---:|
| Psychology spine | ≥ 7/10 |
| Mechanism depth | ≥ 7/10 |
| Insight density | ≥ 6/10 |
| Recognition | ≥ 6/10 |
| Story dominance | ≤ 3/10 |
| Example dependency | ≤ 3/10 |
| Reframe signature | ≥ 2 |

`structure_check` is complementary. It catches deterministic patterns such as sequential scene markers
and dialogue chains, but marker counts alone cannot determine whether psychology is the spine.

## Anti-Story Rules

Forbidden as structural spine:

- fictional protagonist;
- chronological plot;
- character arc;
- scene-to-scene progression;
- flashback montage;
- repeated locations/props as continuity;
- dialogue exchange;
- cinematic opening that delays the psychological point.

When found, rewrite:

```text
scene/action/emotion
        ↓
recognizable behavior
        ↓
interpretation
        ↓
inner process
        ↓
mechanism
        ↓
WHY
        ↓
implication
```

## Optional Branches

Use only when the Psychology Brief and source pack justify them:

- origin/development;
- adaptive strength;
- contradiction/paradox;
- dark side/cost;
- relational dynamic;
- practical shift.

Never add childhood/trauma merely because it makes a script feel deeper.

## Quality Definition

A production-ready script should make the viewer think:

> 「自分の中で、こういう心理プロセスが起きていたのか。」

Not:

> 「こんな人の物語だった。」

The final emotional landing is **self-understanding**, not generic motivation.

## Pipeline References

- Psychology model: `youtube_pipeline/resource_prompts.py`
- Semantic review gate: `youtube_pipeline/resource_pipeline.py`
- Deterministic validation: `youtube_pipeline/resource_validation.py`
- Global constants: `skills/CHANNEL_CONSTANTS.md`
- Planning skill: `skills/skill_tam_ly_hoc_script_planning_JP/SKILL.md`
- Production skill: `skills/skill_tam_ly_hoc_script_production_JP/SKILL.md`
- Competitor research notes: `PSYCHTOONS_COMPETITOR_ANALYSIS.md`

## Quick Check

```text
[ ] Psychology is the spine
[ ] Recognition is short
[ ] WHY appears early
[ ] Mechanism explains behavior
[ ] Inner process is explicit
[ ] Examples are removable
[ ] At least 2 meaningful reframes
[ ] No chronological story
[ ] No generic self-help
[ ] Ending creates self-understanding
```

---

**Updated:** 2026-08-17
**Status:** Psychology-first production reference
