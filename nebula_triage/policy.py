"""Deterministic routing policy applied on top of the model's answer.

This layer exists because the classifier is probabilistic and some mistakes are
not affordable. Every rule here can only make the outcome *more* cautious: raise
the priority, move the ticket to a human, or take away the right to auto-reply.
No rule ever downgrades a ticket the model flagged, and no rule invents a route
the model was not offered.

Pure functions, no I/O, no API — so the whole policy is testable without a key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import taxonomy as tx

#: Below this, the model's primary category is not trusted on its own.
CONFIDENCE_REVIEW_THRESHOLD = 0.75

#: An automated reply needs a higher bar than a human route.
CONFIDENCE_AUTO_REPLY_THRESHOLD = 0.85

#: Where each category goes when the model's chosen action is not usable.
ROUTE_BY_CATEGORY: dict[str, str] = {
    "billing_subscription": "route_to_billing",
    "refund_request": "route_to_refunds_review",
    "technical_bug": "route_to_engineering",
    "expert_complaint": "route_to_expert_quality",
    "expert_service_ops": "route_to_expert_ops",
    "account_access": "route_to_account_support",
    # Deliberately NOT auto_reply_kb: this map is the fallback used when the
    # auto-reply gate has just been closed, so it must lead to a person.
    "product_question": "route_to_general_support",
    "feedback_praise": "no_action_needed",
    "trust_safety": "escalate_trust_safety_human",
    "unclear_other": "request_more_info",
}

_PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


@dataclass
class Decision:
    """The routing decision actually acted on, and why."""

    category: str
    priority: str
    action: str
    #: True when the routing decision must be confirmed by a person before
    #: anything is sent — the human-in-the-loop gate, not "a human will work it".
    requires_review: bool = False
    review_reasons: list[str] = field(default_factory=list)
    applied_rules: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "priority": self.priority,
            "action": self.action,
            "requires_review": self.requires_review,
            "review_reasons": self.review_reasons,
            "applied_rules": self.applied_rules,
        }


def _at_least(current: str, floor: str) -> str:
    """Return whichever priority is more urgent (P0 is the most urgent)."""
    if current not in _PRIORITY_RANK:
        return floor
    return current if _PRIORITY_RANK[current] <= _PRIORITY_RANK[floor] else floor


def apply(result: dict[str, Any], schema_violations: list[str] | None = None) -> Decision:
    """Turn a model result into the decision the system will act on."""
    violations = list(schema_violations or [])

    category = result.get("category")
    priority = result.get("priority")
    action = result.get("recommended_action")
    sentiment = result.get("sentiment", "calm")
    confidence = float(result.get("confidence", 0.0))
    secondary = list(result.get("secondary_categories") or [])
    # Trust the model's own `is_multi_topic` judgement rather than inferring it
    # from a non-empty `secondary_categories`. The two fields mean different
    # things by design: "another category is present in the text" is not the same
    # as "there is a second actionable request". Deriving one from the other sent
    # every ticket with a secondary aspect to review — see docs/model-comparison.md.
    multi_topic = bool(result.get("is_multi_topic"))
    safety_signal = bool(result.get("contains_safety_signal"))

    # Two separate jobs, both keyed off the raw value the model returned.
    # Sanitising: put something usable in the Decision, so the routing tables
    # below cannot be indexed with an invented key.
    category_invalid = category not in tx.CATEGORIES
    decision = Decision(
        category="unclear_other" if category_invalid else category,
        priority=priority if priority in tx.PRIORITIES else "P2",
        action=action if action in tx.ACTIONS else "request_more_info",
    )

    def flag(rule: str, reason: str) -> None:
        decision.applied_rules.append(rule)
        decision.review_reasons.append(reason)
        decision.requires_review = True

    # 1. The model did not answer inside its own vocabulary. Nothing that follows
    #    can be trusted, so a human looks at it.
    # Judging: record that the model broke its contract. This reads `category_invalid`
    # rather than `decision.category` on purpose — a ticket the model honestly and
    # correctly labelled `unclear_other` is not the same thing as garbage output.
    # The redundancy with `violations` is deliberate: `apply()` is callable without
    # them (see scripts/test_policy.py), and then this is the only check left.
    if violations or category_invalid:
        flag("invalid_model_output", f"model output was off-schema: {violations or category!r}")

    # 2. Safety wins over everything, unconditionally. This rule is the reason the
    #    policy layer exists at all: it must not depend on the model being right.
    if safety_signal or decision.category == "trust_safety" or sentiment == "distressed":
        decision.applied_rules.append("safety_override")
        decision.category = "trust_safety"
        decision.priority = "P0"
        decision.action = "escalate_trust_safety_human"
        decision.requires_review = True
        decision.review_reasons.append("possible risk to the user — trained human only")
        return decision  # No later rule may soften this.

    # 3. Money is never settled automatically.
    if decision.category == "refund_request" or "refund_request" in secondary:
        decision.action = "route_to_refunds_review"
        decision.priority = _at_least(decision.priority, "P1")
        flag("refund_needs_human", "refund decisions are made by a person, never by the model")

    # 4. More than one request in one ticket: single-route triage would drop part of it.
    if multi_topic:
        flag("multi_topic", f"ticket contains several requests: {secondary or 'see text'}")

    # 5. The model is not sure enough to route unattended.
    if confidence < CONFIDENCE_REVIEW_THRESHOLD:
        flag("low_confidence", f"confidence {confidence:.2f} < {CONFIDENCE_REVIEW_THRESHOLD}")

    # 6. Tone does not change priority, but it does change who replies. Nobody is
    #    answered by a template while they are shouting.
    if sentiment in ("angry", "abusive") and decision.action == "auto_reply_kb":
        decision.action = ROUTE_BY_CATEGORY.get(decision.category, "route_to_general_support")
        flag("no_template_for_hostile_tone", f"tone is {sentiment}; a person should reply")

    # 7. The auto-reply gate. Everything above may already have removed the right
    #    to auto-reply; this is the positive check that has to pass on its own.
    if decision.action == "auto_reply_kb":
        eligible = (
            decision.category == "product_question"
            and confidence >= CONFIDENCE_AUTO_REPLY_THRESHOLD
            and not multi_topic
            and sentiment == "calm"
            and decision.priority in ("P2", "P3")
        )
        if not eligible:
            decision.action = ROUTE_BY_CATEGORY.get(decision.category, "route_to_general_support")
            flag("auto_reply_gate_failed", "did not meet the bar for an automated reply")

    return decision


def fallback_decision(reason: str) -> Decision:
    """The routing decision used when the classifier produced nothing usable.

    A ticket that could not be classified must not disappear, and must not be
    guessed at. It goes to tier-1 support at P2 — the level that assumes neither
    an emergency nor something ignorable — flagged for review with the reason
    the classifier gave. This is what the system does on a timeout, a rate limit
    that survived every retry, or a response that failed its schema.
    """
    return Decision(
        category="unclear_other",
        priority="P2",
        action="route_to_general_support",
        requires_review=True,
        review_reasons=[f"automatic classification failed: {reason}"],
        applied_rules=["classification_failed"],
    )
