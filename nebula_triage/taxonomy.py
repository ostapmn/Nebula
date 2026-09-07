"""Single source of truth for the triage vocabulary.

Every enum here is a `Literal` type, so the exact same tuple of strings feeds
three consumers at once: the Pydantic response schema, the prompt text, and the
deterministic policy layer. There is no second place to keep in sync — if a
category is added here, the schema and the prompt both pick it up automatically.
"""

from typing import Literal, get_args

# --------------------------------------------------------------------------- #
# Categories
#
# Design rule: a category is *the team that owns the queue*, not the topic of
# the text. That is why refunds are split from billing, and why complaints about
# an expert are split from operational failures involving an expert — those go
# to different teams with different SLAs and different authority.
# --------------------------------------------------------------------------- #

Category = Literal[
    "billing_subscription",
    "refund_request",
    "technical_bug",
    "expert_complaint",
    "expert_service_ops",
    "account_access",
    "product_question",
    "feedback_praise",
    "trust_safety",
    "unclear_other",
]

CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "billing_subscription": (
        "Questions or problems about payment, plan, price, auto-renewal, "
        "cancelling a subscription. The user is NOT explicitly demanding money back."
    ),
    "refund_request": (
        "The user explicitly asks for money back, disputes a charge, or threatens "
        "a chargeback. Separate from billing because it has its own SLA and owner."
    ),
    "technical_bug": (
        "The product misbehaves: crash, blank screen, feature not working, "
        "notifications not arriving, payment screen failing to load."
    ),
    "expert_complaint": (
        "Complaint about an expert's quality, attitude, rudeness, or accuracy of "
        "the reading. Routes to the expert quality team."
    ),
    "expert_service_ops": (
        "Operational failure around an expert: no reply, chat abandoned mid-session, "
        "excessive waiting, expert unavailable after payment. No judgement about quality."
    ),
    "account_access": (
        "Login, password reset, lost account, wrong account, account deletion, "
        "data export and other GDPR-style access requests."
    ),
    "product_question": (
        "'How does this work' questions about the product or its content. "
        "The only category that is genuinely eligible for an automated reply."
    ),
    "feedback_praise": (
        "Positive feedback, thanks, or an unsolicited feature idea. No action needed."
    ),
    "trust_safety": (
        "Any signal of self-harm, suicidal ideation, severe emotional distress, "
        "threats to others, a minor using the service, or abuse. Always a human."
    ),
    "unclear_other": (
        "Not enough information to classify, empty or meaningless text, spam. "
        "This category exists so the model can abstain instead of guessing."
    ),
}

# --------------------------------------------------------------------------- #
# Priority
#
# Priority answers one question only: how fast must a human see this. It is
# deliberately decoupled from tone — see `Sentiment` below.
# --------------------------------------------------------------------------- #

Priority = Literal["P0", "P1", "P2", "P3"]

PRIORITY_DESCRIPTIONS: dict[str, str] = {
    "P0": (
        "Critical, react within the hour. Risk to a person's safety; money lost or "
        "stuck with no access; an outage affecting many users."
    ),
    "P1": (
        "Urgent, react the same day. The user is blocked from a core flow, or paid "
        "money and did not get the service, or is about to churn / file a chargeback."
    ),
    "P2": (
        "Normal, react within 1-2 business days. A real problem that has a workaround."
    ),
    "P3": (
        "Low. Nothing is blocked: cosmetic issues, how-to questions, praise, ideas."
    ),
}

# --------------------------------------------------------------------------- #
# Sentiment
#
# Separate axis on purpose. Tone is useful for choosing *who* replies and in what
# register, but it must not drive priority — otherwise the system teaches users
# that shouting is the way to get served first.
# --------------------------------------------------------------------------- #

Sentiment = Literal["calm", "frustrated", "angry", "abusive", "distressed"]

SENTIMENT_DESCRIPTIONS: dict[str, str] = {
    "calm": "Neutral or polite.",
    "frustrated": "Clearly annoyed, but still constructive.",
    "angry": "Hostile, shouting, all-caps, accusations.",
    "abusive": "Insults, slurs or threats aimed at staff or an expert.",
    "distressed": (
        "Emotional distress, hopelessness, despair. Not the same as angry — this is "
        "a person who may need help rather than a fix."
    ),
}

# --------------------------------------------------------------------------- #
# Recommended action — a routing decision, never customer-facing text
# --------------------------------------------------------------------------- #

Action = Literal[
    "auto_reply_kb",
    "route_to_billing",
    "route_to_refunds_review",
    "route_to_engineering",
    "route_to_expert_quality",
    "route_to_expert_ops",
    "route_to_account_support",
    "route_to_general_support",
    "escalate_trust_safety_human",
    "request_more_info",
    "no_action_needed",
]

ACTION_DESCRIPTIONS: dict[str, str] = {
    "auto_reply_kb": (
        "Send an existing knowledge-base article automatically. Only for simple, "
        "unambiguous how-to questions."
    ),
    "route_to_billing": "Billing queue.",
    "route_to_refunds_review": "Refunds queue — a human decides on the money.",
    "route_to_engineering": "Engineering / bug triage queue.",
    "route_to_expert_quality": "Expert quality team (behaviour, accuracy, conduct).",
    "route_to_expert_ops": "Expert operations team (availability, no-shows, waiting).",
    "route_to_account_support": "Account and identity support, incl. GDPR requests.",
    "route_to_general_support": (
        "Tier-1 support queue: a person answers. Use when the request is understood but is not eligible for an automated reply."
    ),
    "escalate_trust_safety_human": (
        "Immediate hand-off to a trained human on the trust & safety rota."
    ),
    "request_more_info": "Ask the user a clarifying question before routing.",
    "no_action_needed": "Acknowledge only; nothing to do.",
}

# --------------------------------------------------------------------------- #

CATEGORIES: tuple[str, ...] = get_args(Category)
PRIORITIES: tuple[str, ...] = get_args(Priority)
SENTIMENTS: tuple[str, ...] = get_args(Sentiment)
ACTIONS: tuple[str, ...] = get_args(Action)


def render_options(values: tuple[str, ...], descriptions: dict[str, str]) -> str:
    """Render an enum as a prompt-ready bullet list.

    The prompt is generated from the same tuples the schema validates against,
    so the two can never drift apart.
    """
    return "\n".join(f"- {v}: {descriptions[v]}" for v in values)


def _check_complete() -> None:
    for values, descriptions, name in (
        (CATEGORIES, CATEGORY_DESCRIPTIONS, "CATEGORY"),
        (PRIORITIES, PRIORITY_DESCRIPTIONS, "PRIORITY"),
        (SENTIMENTS, SENTIMENT_DESCRIPTIONS, "SENTIMENT"),
        (ACTIONS, ACTION_DESCRIPTIONS, "ACTION"),
    ):
        missing = set(values) - set(descriptions)
        extra = set(descriptions) - set(values)
        if missing or extra:
            raise RuntimeError(
                f"{name}_DESCRIPTIONS out of sync: missing={missing}, extra={extra}"
            )


_check_complete()
