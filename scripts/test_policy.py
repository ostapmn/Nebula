#!/usr/bin/env python3
"""Offline checks for the deterministic layer. No API key, no network.

The policy layer is the part of the system that must hold even when the model is
wrong, so it is the part that gets tested directly.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nebula_triage.policy import apply  # noqa: E402
from nebula_triage.schema import normalize  # noqa: E402


def model_said(**overrides):
    base = {
        "category": "product_question",
        "priority": "P3",
        "recommended_action": "auto_reply_kb",
        "sentiment": "calm",
        "confidence": 0.95,
        "secondary_categories": [],
        "is_multi_topic": False,
        "contains_safety_signal": False,
        "reasoning": "",
    }
    base.update(overrides)
    return normalize(base)


CASES = [
    (
        "a clean how-to question is the one thing that may be automated",
        model_said(),
        lambda d: d.action == "auto_reply_kb" and not d.requires_review,
    ),
    (
        "a safety signal overrides a confident, cheerful classification",
        model_said(contains_safety_signal=True),
        lambda d: d.category == "trust_safety"
        and d.priority == "P0"
        and d.action == "escalate_trust_safety_human"
        and d.requires_review,
    ),
    (
        "distress alone is enough, even without the safety flag",
        model_said(sentiment="distressed"),
        lambda d: d.action == "escalate_trust_safety_human" and d.priority == "P0",
    ),
    (
        "a refund is never settled automatically and never sits below P1",
        model_said(category="refund_request", priority="P3", recommended_action="auto_reply_kb"),
        lambda d: d.action == "route_to_refunds_review"
        and d.priority == "P1"
        and d.requires_review,
    ),
    (
        "a refund hiding in the secondary categories still triggers the money rule",
        model_said(category="technical_bug", recommended_action="route_to_engineering",
                   secondary_categories=["refund_request"]),
        lambda d: d.action == "route_to_refunds_review" and d.requires_review,
    ),
    (
        "low confidence sends the ticket to review instead of a queue",
        model_said(confidence=0.4),
        lambda d: d.requires_review and "low_confidence" in d.applied_rules,
    ),
    (
        "a multi-topic ticket is never routed on one label alone",
        model_said(is_multi_topic=True, secondary_categories=["expert_complaint"]),
        lambda d: d.requires_review and "multi_topic" in d.applied_rules,
    ),
    (
        "a secondary aspect is not the same as a second request",
        model_said(category="account_access", recommended_action="route_to_account_support",
                   secondary_categories=["technical_bug"], is_multi_topic=False),
        lambda d: "multi_topic" not in d.applied_rules and not d.requires_review,
    ),
    (
        "nobody gets a template while they are shouting",
        model_said(sentiment="abusive"),
        lambda d: d.action != "auto_reply_kb" and d.requires_review,
    ),
    (
        "an angry tone on a cosmetic bug does not become P0",
        model_said(category="technical_bug", priority="P3",
                   recommended_action="route_to_engineering", sentiment="abusive"),
        lambda d: d.priority == "P3",
    ),
    (
        "off-schema output from the model is not silently repaired",
        model_said(category="urgent_refund_thing", priority="CRITICAL"),
        lambda d: d.requires_review and d.category == "unclear_other",
    ),
    (
        "a confident non-product question cannot claim the auto-reply slot",
        model_said(category="billing_subscription"),
        lambda d: d.action == "route_to_billing" and d.requires_review,
    ),
]


def main() -> int:
    failures = 0
    for name, result, check in CASES:
        violations = (
            ["off-schema"] if result["category"] == "urgent_refund_thing" else []
        )
        decision = apply(result, violations)
        ok = check(decision)
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            failures += 1
            print(f"      got: {decision.to_dict()}")
    print(f"\n{len(CASES) - failures}/{len(CASES)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
