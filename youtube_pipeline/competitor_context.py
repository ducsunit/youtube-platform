"""competitor_context.py — Baked competitor analysis for 思考の深淵.

Refresh manually every 5-10 videos. Update `_LAST_UPDATED` when you do.
"""
from __future__ import annotations

# Last updated: 2026-08-22 (yt-dlp channel pull: UCIjZpNXE1He_l5Al-6lvOjg,
# 10 newest uploads — full titles, durations, views, Japanese subtitle scripts,
# thumbnails; supersedes the 2026-08-21 vidIQ snapshot).
# This is editorial grammar only, never a source of claims.
_LAST_UPDATED = "2026-08-22"

COMPETITOR_PATTERNS = """## Competitor: 思考の深淵 (Japanese Jungian深層心理 long-form reference)

- Observed positioning: Japanese long-form Jungian / depth-psychology essays. Every upload frames a life or identity question through Carl Jung's lens (個性化 individuation, シャドウ shadow, 無意識 the unconscious, 自己統合 self-integration, 魂の覚醒 awakening). Topics blend Knowledge + Religion/spirituality.
- Observed format: Japanese long-form uploads run 33–50 minutes, current uploads extend to about 55 minutes. Default production target is 35–45 minutes; length is earned by a revelation ladder, not filler or repeated reassurance.
- Title grammar (two observed variants): (a) a bracket tag (【完全版】 or 【ユング心理学】) + a provocative identity/awakening question + a compact string of theory terms it will use (個性化・シャドウ・無意識・自己統合); (b) numbered-list packaging (7つの静かなサイン / 5つの秘密 / 8つの覚醒サイン), which is the channel's highest-reach format — list uploads reach 25K–59K views while pure question uploads sit in the low thousands. It names the theorist (カール・ユング) openly. Use either grammar; never reuse exact wording.
- Opening rhythm: current uploads address the viewer directly in the first breath with a hypothetical or recognition question (もし〜だとしたら、どう思うでしょうか / なぜ〜不思議に思ったことはありませんか), then move through sensory recognition around an ordinary object, room, ritual or social moment and pivot into the Jungian question within the first minute. A scene-first opening is acceptable only when direct viewer address comes first or immediately follows.
- Narrative rhythm: concrete symbol → Jungian reframe → named-concept mechanism (shadow/individuation/unconscious) → a distinct implication → return to the symbol with a changed meaning. A vignette is editorial illustration, never a case study, proof, chronology, or invented biography.
- Depth: sustain 3–5 genuinely separate revelations around one central psychological tension. A named Jungian concept may be revisited only when its implication changes.
- Tone: intimate, calm, poetic, reflective, quietly spiritual. Reflective spiritual language (魂/覚醒/目覚め) is allowed as an interpretive register. Do NOT promise cure/healing, diagnose, assert childhood trauma causes about real viewers, or state neuroscience facts as proven.
- Ending: return once to the central image and leave a quiet identity-level or awakening observation. Do not recap every section or add a long CTA.
- Thumbnail: high-contrast charcoal/blackboard background, white chalk or off-white ink linework, one emotionally charged symbolic metaphor, sparse anonymous stick/silhouette figures, and one restrained warm-gold light/accent. A short Japanese headline is integrated cleanly, never a banner, half-frame, collage or hard split.
- Visual sequence: dark-background chalk/ink line art, metaphoric transformations, simple figures and objects, continuous morph-like callbacks.
- Japan localization: use natural Japanese emotional and reflective-spiritual wording. Keep the Jungian concept names in Japanese (個性化・シャドウ・無意識); do not import foreign clinical diagnoses.
"""


# Editorial DNA abstracted from public 思考の深淵 metadata and visual walkthroughs.
# This captures structure/rhythm only; it does not copy wording, examples, or proprietary text.
COMPETITOR_WRITING_DNA = """
- Open with a sensory image and identity tension, then pivot to the central Jungian question before the opening becomes a detached cinematic scene.
- Hold one core question, one or two named Jungian concepts (shadow / individuation / unconscious), and three to five different implications/revelations. The theory is a lens, named openly, not a lecture or a proven scientific claim.
- Return an ordinary object, room or symbol two to four times only when its meaning advances: recognition → interpretation → implication → closing image.
- Use a vignette as an editorial illustration, never as an anecdote, case study, proof of a claim, or a protagonist's life story.
- Each movement must reveal a new interpretation, implication or self-understanding. Long duration must come from the revelation ladder, not disclaimers, tips, generic reassurance, or paraphrase.
- End with a reflective, quietly spiritual landing rather than a recap, motivational speech or extended CTA.
- For Japan, localize the emotional and reflective-spiritual wording; keep Jungian concept names in Japanese and never present them as clinical diagnosis.
"""


def competitor_inject_text() -> str:
    """Return the competitor context block for injection into prompts."""
    return COMPETITOR_PATTERNS + "\n" + COMPETITOR_WRITING_DNA
