"""The one place where the LLM is called.

Everything downstream of this module is ordinary deterministic Python. That
separation is deliberate: the probabilistic part of the system has exactly one
entry point and one exit point, so it can be replaced, mocked, or audited on its
own.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import anthropic

from .prompts import PROMPTS, user_message
from .schema import TriageBasic, TriageFull, normalize

#: Sonnet 5 is the deliberate default: this is a high-volume, narrow
#: classification task where Opus-level reasoning is not the constraint.
#: See docs/architecture.md for the cost comparison and the two-tier proposal.
DEFAULT_MODEL = os.environ.get("NEBULA_TRIAGE_MODEL", "claude-sonnet-5")

#: Enough room for adaptive thinking plus a small JSON object. Note there is no
#: `temperature` anywhere in this file — Sonnet 5 rejects sampling parameters
#: with a 400, so run-to-run determinism is not available and must be handled
#: by the eval rather than assumed.
MAX_TOKENS = 4000

_OUTPUT_FORMATS = {"v2": TriageBasic, "v3": TriageFull}

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class Classification:
    """Whatever came back from the model, plus how it got there."""

    version: str
    model: str
    result: dict[str, Any] | None = None
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    #: Tokens written to / served from the prompt cache. Zero when the model's
    #: minimum cacheable prefix is longer than our system prompt — see
    #: docs/cost-and-caching.md.
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    elapsed_ms: int = 0
    raw_text: str | None = None
    schema_violations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.result is not None


def _client() -> anthropic.Anthropic:
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise RuntimeError(
            "No credentials found. Copy .env.example to .env and set ANTHROPIC_API_KEY."
        )
    # The SDK already retries 429/5xx/connection errors with backoff, so this
    # module does not implement a retry loop of its own.
    return anthropic.Anthropic(max_retries=3, timeout=60.0)


def _parse_freeform(text: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Best-effort JSON extraction, used only by V1.

    V1 asks for JSON in prose and gets prose-shaped JSON back. Recovering it by
    hand is the point: it shows what the schema buys us in V2.
    """
    match = _JSON_BLOCK.search(text)
    if not match:
        return None, ["no JSON object found in response"]
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return None, [f"invalid JSON: {exc}"]
    if not isinstance(data, dict):
        return None, ["JSON was not an object"]
    return data, []


def _validate_against_taxonomy(data: dict[str, Any]) -> list[str]:
    """Report values outside the fixed vocabulary — expected for V1, never for V2/V3."""
    from . import taxonomy as tx

    checks = (
        ("category", tx.CATEGORIES),
        ("priority", tx.PRIORITIES),
        ("sentiment", tx.SENTIMENTS),
        ("recommended_action", tx.ACTIONS),
    )
    problems = []
    for key, allowed in checks:
        value = data.get(key)
        if value is not None and value not in allowed:
            problems.append(f"{key}={value!r} is not in the taxonomy")
    return problems


def classify(
    ticket_text: str,
    version: str = "v3",
    model: str | None = None,
    client: anthropic.Anthropic | None = None,
) -> Classification:
    """Classify one ticket with one prompt version."""
    if version not in PROMPTS:
        raise ValueError(f"unknown prompt version {version!r}; have {sorted(PROMPTS)}")

    model = model or DEFAULT_MODEL
    client = client or _client()
    out = Classification(version=version, model=model)

    request: dict[str, Any] = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        # Explicit breakpoint on the system block. The top-level `cache_control`
        # shorthand is not accepted by messages.parse(), only by create().
        # The system prompt and the response schema are byte-identical on every
        # request and together dominate input cost; the ticket text is the only
        # part that varies, and it comes after this breakpoint.
        "system": [
            {
                "type": "text",
                "text": PROMPTS[version],
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": user_message(ticket_text, version)}],
    }

    started = time.monotonic()

    try:
        output_format = _OUTPUT_FORMATS.get(version)
        if output_format is None:
            # V1: no schema, no guarantees.
            response = client.messages.create(**request)
            text = "".join(b.text for b in response.content if b.type == "text")
            out.raw_text = text
            data, problems = _parse_freeform(text)
            out.schema_violations = problems
        else:
            response = client.messages.parse(output_format=output_format, **request)
            data = response.parsed_output.model_dump() if response.parsed_output else None
            if data is None:
                out.schema_violations = ["model returned no parseable structured output"]
    except anthropic.NotFoundError as exc:
        out.error = f"model not found ({model}): {exc}"
        return out
    except anthropic.RateLimitError as exc:
        out.error = f"rate limited after retries: {exc}"
        return out
    except anthropic.APIStatusError as exc:
        out.error = f"API error {exc.status_code} ({exc.type}): {exc}"
        return out
    except anthropic.APIConnectionError as exc:
        # APITimeoutError is a subclass of this — a request that exceeds the
        # client's 60s timeout (after the SDK's own retries) lands here.
        out.error = f"connection failed: {exc}"
        return out
    except Exception as exc:  # noqa: BLE001 — see the contract note below
        # classify() must never raise: runner.run_version maps it over a thread
        # pool, and one escaping exception would abort the whole batch. Anything
        # the four handlers above did not anticipate (a schema validation error,
        # a malformed response object) becomes a value, not a crash.
        out.error = f"unexpected failure: {type(exc).__name__}: {exc}"
        return out
    finally:
        out.elapsed_ms = int((time.monotonic() - started) * 1000)

    out.input_tokens = response.usage.input_tokens
    out.output_tokens = response.usage.output_tokens
    out.cache_write_tokens = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
    out.cache_read_tokens = getattr(response.usage, "cache_read_input_tokens", 0) or 0

    if data is None:
        out.error = "; ".join(out.schema_violations) or "no result"
        return out

    out.schema_violations += _validate_against_taxonomy(data)
    out.result = normalize(data)
    return out
