"""Response schemas.

Two shapes, one per prompt generation:

* `TriageBasic`  — what prompt V2 asks for: category, priority, action.
* `TriageFull`   — what prompt V3 asks for: adds the axes that V2's failures
                   forced us to add (sentiment, confidence, multi-topic,
                   language, explicit safety flag).

Both are Pydantic models so the SDK can validate the model's answer against them
directly (`client.messages.parse(..., output_format=...)`). Field types come from
`taxonomy.py`, so an invalid category is a schema violation, not a bug we have to
notice at runtime.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .taxonomy import Action, Category, Priority, Sentiment


class TriageBasic(BaseModel):
    """Prompt V2 output."""

    model_config = ConfigDict(extra="forbid")

    category: Category
    priority: Priority
    recommended_action: Action
    reasoning: str = Field(description="One or two sentences, internal use only.")


class TriageFull(BaseModel):
    """Prompt V3 output."""

    model_config = ConfigDict(extra="forbid")

    category: Category
    secondary_categories: list[Category] = Field(
        description="Other categories genuinely present in the ticket. Empty if only one."
    )
    is_multi_topic: bool = Field(
        description="True when the ticket contains more than one actionable request."
    )
    priority: Priority
    sentiment: Sentiment
    contains_safety_signal: bool = Field(
        description="True on any hint of self-harm, despair, threats, or a minor user."
    )
    confidence: float = Field(
        description="0.0-1.0. How certain the primary category is. Be honest; low is fine."
    )
    detected_language: str = Field(description="ISO 639-1 code of the ticket text, e.g. 'uk'.")
    recommended_action: Action
    reasoning: str = Field(description="One or two sentences, internal use only.")


#: Fields the rest of the pipeline relies on, with the values assumed when an
#: older prompt version does not produce them.
_DEFAULTS: dict[str, Any] = {
    "secondary_categories": [],
    "is_multi_topic": False,
    "sentiment": "calm",
    "contains_safety_signal": False,
    "confidence": 1.0,
    "detected_language": "und",
}


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Bring any prompt version's output to one shape the policy layer can read.

    V1 is free-form and may be missing or mis-spell anything, so unknown enum
    values are preserved verbatim — `policy.py` treats them as invalid rather
    than silently repairing them.
    """
    out = dict(_DEFAULTS)
    out.update(raw)
    try:
        out["confidence"] = min(1.0, max(0.0, float(out["confidence"])))
    except (TypeError, ValueError):
        out["confidence"] = 0.0
    return out
