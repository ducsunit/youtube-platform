# LONG-FORM BEHAVIORAL SCRIPT ENGINE

## Production specification v5 — Psychology Direct, source-locked

This document replaces the original v4.5 five-act/self-help specification. It
is the single long-form editorial policy for the production pipeline.

The desired viewer experience is:

```text
I do that.
→ I misunderstood what it meant.
→ Now I understand the mechanism behind it.
→ I can see the cost without being judged.
→ I can observe one condition differently.
→ End.
```

The system makes Japanese psychology videos. It is not a neuroscience lecture,
a diagnostic tool, a fictional story, or a productivity listicle.

## 1. Non-negotiable authority order

```text
verified source pack + claim ledger
→ script contract
→ adaptive plan
→ reviewer findings
→ style preference / retention idea
```

The source pack is the authority for every psychological, biological,
developmental, causal, or practical claim. A compelling hook never grants
permission to add an unsupported mechanism.

Do not introduce dopamine, cortisol, amygdala, prefrontal cortex, trauma,
childhood causes, named therapies/frameworks, diagnostic labels, reinforcement
loops, or personality types unless the current run's verified sources explicitly
support them. `editorial_application` is a bounded interpretive lens, not a new
proven mechanism.

## 2. Editorial spine

Use 3-7 meaningful movements; normally 5-6. The actual number and duration are
derived from the argument, not from a five-act template.

```text
1. cold-open behavior recognition
2. pain contradiction
3. misconception and one early reframe
4. one core psychological question / big open loop
5. one or two source-locked mechanisms
6. new implication or observable cost
7. one practical principle
8. self-observation
9. quiet landing
```

Movements may combine when the topic is simple. Do not add a movement merely to
fill time.

### Cold open

Within the first six sentences, the narration must contain:

```text
observable behavior
→ pain contradiction
→ one open loop
```

Example:

```text
休みの日なのに、座った瞬間から落ち着かない。
本当は疲れているのに、通知も来ていない画面を開いてしまう。
なぜ、何も起きていない時間ほど、人は自分で用事を探し始めるのでしょうか。
```

The open loop asks about the source-locked mechanism. It must not promise a
cure, threaten a negative future, invent a brain explanation, or preview an
unsupported list of types.

### Mechanism and depth

Choose only the one or two mechanisms required by the contract. For each one,
explain once:

```text
what happens
→ why it can happen within the source support
→ what it changes in observable behavior
```

An everyday example is recognition/evidence only. It never becomes a
chronological character story.

### Consequence and practical shift

The consequence is an implication or an observable cost. Do not turn it into a
relief-maintains-behavior loop unless the verified source supports that exact
causal claim.

Use one practical principle, with at most two or three short examples. A
principle can adjust a source-supported behavioral condition; it must not become
a “three pillar protocol” by default.

### Ending

End in two or three sentences:

```text
self-blame
→ more accurate observation
→ quiet realization
→ stop
```

A comment prompt or next-video CTA is optional, one sentence maximum, and must
not damage the landing. End-screen routing belongs to publish/UI metadata, not
to a required final script act.

## 3. Long-form continuity without template filler

Long-form retention is an information-progression problem, not a bridge-count
problem. The planner may emit an optional `continuity_map`:

```json
{
  "big_open_loop": "Why does the reaction begin before the stated intention?",
  "payoff_path": [
    "The source-backed mechanism explains the first reaction.",
    "The observable cost explains why the pattern matters.",
    "The practical principle changes the condition at the start."
  ],
  "retention_turns": [
    {
      "after_section": "S3",
      "new_information": "Attention has moved from rest to a response target.",
      "why_continue": "The viewer now needs to see the cost of that shift."
    }
  ]
}
```

Rules:

- It has one big open loop, not nested artificial mysteries.
- It has at most three retention turns.
- Every turn introduces a source-backed mechanism, a deeper implication, or an
  observable cost.
- It never uses fixed minute markers or mandatory bridge wording.
- It never creates a new psychological type, mechanism, or action protocol just
  to keep the viewer watching.
- The writer resolves the open loop naturally; the reviewer checks the payoff,
  but does not force extra lines to make the map look complete.

## 4. Duration and drafting

Target duration is usually 6-12 minutes. Up to 15 minutes is allowed only when
the source-backed argument has genuinely more to reveal.

Japanese narration is estimated using 380-400 characters per minute. The
2300-6000 character range is advisory, never a filler quota. Actual timing is
derived from the final script and later from real audio.

Write the full narration in one call for normal 6-12 minute videos. Do not split
it into fixed acts/chunks. If a provider output limit forces chunking, every
chunk must receive:

```text
the immutable claim ledger
the contract and adaptive plan
the previous chunk's resolved claims
the next chunk's intended information gain
```

Then run one whole-script source and continuity audit after assembly.

## 5. Automation stages

```text
topic/source lock
→ claim ledger
→ psychology brief
→ script contract
→ adaptive planning + optional continuity map
→ one natural script draft
→ one targeted editorial polish
→ source/consistency audit
→ deterministic QA and structure check
→ derive sections, timing, visuals, TTS prompt, and publish metadata
```

The planning artifact is an argument map, not a timed screenplay. Each section
contains:

```text
purpose
psychological_job
behavior_link
relative_weight
new_information
viewer_question_answered
state_advance
mechanisms_used
```

The final script determines timing, sections, visual beats, and audio mapping.

## 6. Review policy

Review detects the single biggest real defect, makes at most one targeted
revision, then stops. Valid reasons to revise:

- the hook has no concrete behavior, pain contradiction, or open loop;
- the mechanism is absent or unclear;
- the open loop is not paid off by a supported explanation;
- sections repeat the same insight;
- examples become story spine;
- source boundaries are violated;
- the ending recaps, lectures, motivates, or runs too long.

Review must not rewrite merely because a score is low, a duration target is not
met, there are fewer than five sections, no archetype was used, or a CTA is
missing.

## 7. Forbidden legacy requirements

The following are explicitly not production requirements:

- a fixed five-act structure;
- exact timestamps such as 3:30 and 6:00;
- mandatory retention bridge sentences;
- one named university/scientist in every video;
- dopamine/cortisol/glucose/amygdala or other neuroscience by default;
- three psychological archetypes or self-diagnosis categories;
- a guilt/reinforcement loop without an explicit verified source;
- a three-pillar action protocol;
- multi-chunk drafting for ordinary-length scripts;
- fixed word counts as a pass/fail gate;
- mandatory subscribe, comment, or next-video CTA.

## 8. Pre-publish checklist

- [ ] Source pack and claim ledger support every non-obvious claim.
- [ ] The first six sentences contain behavior, pain contradiction, and one
      open loop.
- [ ] The reframe appears early and is not paraphrased more than twice.
- [ ] There is exactly one core question.
- [ ] One or two selected mechanisms are named/explained.
- [ ] Every movement adds a fact, deeper mechanism, or implication.
- [ ] Any long-form retention turn adds information rather than a template
      promise.
- [ ] The practical part is one principle, not a listicle.
- [ ] The ending is quiet and short.
- [ ] Script QA, source audit, structure check, derived timeline, image strategy,
      thumbnail contract, dynamic routing, telemetry, and Run Live remain intact.
