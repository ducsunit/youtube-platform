"""Review v2 - Hook, mechanism, tools, repetition check for problem-solving format."""
from youtube_pipeline.resource_pack.prompts import review_v2_prompt
from youtube_pipeline.resource_pack.validation import (
    normalize_review_list, title_hook_alignment, psychology_hook_findings,
    direct_address_findings, psychology_review_gate_verdict,
    unsupported_source_claims, causal_capability_violations, policy_violations
)
from youtube_pipeline.core import StageResult, RunContext
from youtube_pipeline.unified_router import get_router

import logging
logger = logging.getLogger(__name__)

router = get_router()

def _review_v2(context: RunContext) -> StageResult:
    """Review problem-solving script: hook, 1 mechanism, 3 tools, repetition."""
    contract = context.store.read_json("script_contract", context.state)
    plan = context.store.read_json("planning", context.state)
    source_pack = context.store.read_json("source_pack", context.state)
    draft = context.store.read_text("script_draft", context.state)
    
    review = router.generate_json("review", review_v2_prompt(contract, plan, source_pack, draft))
    
    # Validate review structure
    review["issues"] = normalize_review_list(review.get("issues"))
    review["required_changes"] = normalize_review_list(review.get("required_changes"))
    
    decision = str(review.get("decision", "")).strip().lower()
    if decision not in ("pass", "revise"):
        raise ValueError("Reviewer decision must be 'pass' or 'revise'")
    
    if not review.get("optimization_report", "").strip():
        raise ValueError("Reviewer missing optimization_report")
    
    # Title-hook alignment
    title_alignment = title_hook_alignment(draft, contract)
    review["title_hook_alignment"] = title_alignment
    if not title_alignment["passed"]:
        decision = "revise"
        review["decision"] = "revise"
        review["required_changes"].append(
            f"TITLE-TO-HOOK ALIGNMENT: Hook must deliver title promise in 20s. Use anchors: {', '.join(title_alignment['anchors'])}"
        )
    
    # Repetition check
    repetition = _script_repetition_findings(draft)
    review["deterministic_repetition"] = {
        "pair_count": len(repetition),
        "pairs": repetition[:10],
        "passed": len(repetition) < 2
    }
    if len(repetition) >= 2:
        decision = "revise"
        review["decision"] = "revise"
        review.setdefault("required_changes", []).append(
            "DETERMINISTIC REPETITION: Merge or delete repeated propositions. Keep clearest version."
        )
    
    # Hook format gate
    hook_findings = psychology_hook_findings(draft) + direct_address_findings(draft)
    if hook_findings:
        decision = "revise"
        review["decision"] = "revise"
        review.setdefault("required_changes", []).extend(
            f"HOOK FORMAT GATE: {f} — Keep specific behavior, name pain contradiction, one WHY/open loop." for f in hook_findings
        )
    
    # Format alignment (A/B only)
    format_alignment = review.get("format_alignment")
    if isinstance(format_alignment, dict):
        classification = str(format_alignment.get("classification", "")).strip().upper()
        if classification in ("D", "E") and decision == "pass":
            decision = "revise"
            review["decision"] = "revise"
            review["required_changes"].append(
                f"FORMAT {classification}: Convert to psychological observation/mechanism. No chronological story."
            )
    
    # Psychology gate (diagnostic only)
    review["psychology_gate_diagnostic"] = {
        "passed": psychology_review_gate_verdict(review)[0],
        "failed": psychology_review_gate_verdict(review)[1],
        "blocking": False
    }
    
    # Source claims check
    review["unsupported_claims"] = unsupported_source_claims(draft, source_pack)
    review["causal_violations"] = causal_capability_violations(draft, source_pack)
    review["policy_violations"] = policy_violations(draft, context.store.read_json("claim_ledger", context.state))
    
    # Apply review if revise
    if decision == "revise":
        revised = router.generate_text("apply_review", review.get("apply_review_prompt", ""))
    else:
        revised = draft
    
    # Char count verification
    verified_chars = non_whitespace_chars(revised)
    target_min = contract.get("target_char_min", 4500)
    review["char_report"] = {
        "verified_chars_by_code": verified_chars,
        "target_min_chars": target_min,
        "status": "ok" if verified_chars >= target_min else "short",
        "shortfall": max(0, target_min - verified_chars)
    }
    
    # Save artifacts
    refs = [
        context.store.put_json("review_report", "script/review-report.json", review, "review_v2"),
        context.store.put_text("reviewed_script", "script/script-reviewed.txt", revised, "review_v2"),
    ]
    
    return StageResult(refs, {
        "review_decision": decision,
        "editor_revision": decision == "revise",
        "verified_chars": verified_chars
    })


def _script_repetition_findings(script: str) -> list:
    """Find repeated long propositions."""
    import re
    def normalize(value: str) -> str:
        return re.sub(r"[^一-龿ぁ-んァ-ンA-Za-z0-9]", "", value).lower()
    def grams(value: str):
        compact = normalize(value)
        return {compact[i:i+3] for i in range(max(0, len(compact)-2))}
    
    sentences = [s.strip() for s in re.split(r"(?<=[。！？!?])\s*", script or "") if s.strip()]
    seen = []
    repeated = []
    for i, sent in enumerate(sentences):
        if len(sent) < 24:
            continue
        sent_grams = grams(sent)
        if not sent_grams:
            continue
        for prev_i, prev_grams in seen[-24:]:
            union = len(sent_grams | prev_grams)
            sim = len(sent_grams & prev_grams) / union if union else 0
            if sim >= 0.62:
                repeated.append({"first": prev_i, "second": i, "similarity": round(sim, 2)})
                break
        seen.append((i, sent_grams))
    return repeated