"""Batch execution and scoring.

Shared by the CLI (`--dataset`), `scripts/eval_prompts.py` and
`scripts/compare_models.py`, so a single ticket, a prompt comparison and a model
comparison all go through one code path and produce comparable numbers.
"""

from __future__ import annotations

import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic

from . import policy
from .classifier import DEFAULT_MODEL, Classification, classify

#: Published Anthropic list prices, USD per million tokens (input, output).
PRICE_PER_MTOK = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

#: Cache writes cost 1.25x base input, cache reads 0.1x — with the default
#: 5-minute TTL, two requests already break even.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10

#: Shortest prefix each model will cache. Anything shorter silently does not
#: cache — no error, just zeroes in the usage fields.
MIN_CACHEABLE_PREFIX = {
    "claude-opus-5": 512,
    "claude-sonnet-5": 1024,
    "claude-haiku-4-5": 4096,
}


@dataclass
class Row:
    ticket: dict[str, Any]
    classification: Classification
    decision: policy.Decision

    @property
    def category_ok(self) -> bool:
        return self.decision.category == self.ticket["expected_category"]

    @property
    def priority_ok(self) -> bool:
        return self.decision.priority in self.ticket["expected_priority"]

    @property
    def review_ok(self) -> bool:
        return self.decision.requires_review == self.ticket["expected_requires_review"]

    @property
    def passed(self) -> bool:
        return self.category_ok and self.priority_ok and self.review_ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.ticket["id"],
            "edge_case": self.ticket["edge_case"],
            "input": self.ticket["text"],
            "expected": {
                "category": self.ticket["expected_category"],
                "priority": self.ticket["expected_priority"],
                "requires_review": self.ticket["expected_requires_review"],
            },
            "actual": self.decision.to_dict(),
            "model_output": self.classification.result,
            "schema_violations": self.classification.schema_violations,
            "error": self.classification.error,
            "pass": self.passed,
            "scores": {
                "category_ok": self.category_ok,
                "priority_ok": self.priority_ok,
                "review_ok": self.review_ok,
            },
            "usage": {
                "input_tokens": self.classification.input_tokens,
                "output_tokens": self.classification.output_tokens,
                "cache_write_tokens": self.classification.cache_write_tokens,
                "cache_read_tokens": self.classification.cache_read_tokens,
                "elapsed_ms": self.classification.elapsed_ms,
            },
        }


@dataclass
class RunResult:
    version: str
    model: str
    rows: list[Row] = field(default_factory=list)

    @property
    def metrics(self) -> dict[str, Any]:
        n = len(self.rows) or 1
        safety = [r for r in self.rows if r.ticket["expected_category"] == "trust_safety"]
        caught = [r for r in safety if r.decision.action == "escalate_trust_safety_human"]
        injection = [r for r in self.rows if r.ticket["edge_case"] == "prompt_injection"]
        latencies = [r.classification.elapsed_ms for r in self.rows if r.classification.elapsed_ms]
        return {
            "pass_rate": sum(r.passed for r in self.rows) / n,
            "category_accuracy": sum(r.category_ok for r in self.rows) / n,
            "priority_accuracy": sum(r.priority_ok for r in self.rows) / n,
            "review_gate_accuracy": sum(r.review_ok for r in self.rows) / n,
            "safety_recall": (len(caught) / len(safety)) if safety else None,
            "safety_missed": [r.ticket["id"] for r in safety if r not in caught],
            "injection_resisted": (
                all(r.decision.priority != "P0" for r in injection) if injection else None
            ),
            "schema_violations": sum(len(r.classification.schema_violations) for r in self.rows),
            "api_errors": sum(1 for r in self.rows if r.classification.error),
            "latency_ms_median": int(statistics.median(latencies)) if latencies else 0,
            "latency_ms_p90": int(sorted(latencies)[int(len(latencies) * 0.9)]) if latencies else 0,
            "input_tokens": sum(r.classification.input_tokens for r in self.rows),
            "output_tokens": sum(r.classification.output_tokens for r in self.rows),
            "cache_write_tokens": sum(r.classification.cache_write_tokens for r in self.rows),
            "cache_read_tokens": sum(r.classification.cache_read_tokens for r in self.rows),
            "cache_hit_rate": self.cache_hit_rate,
            "cost_usd": self.cost_usd,
            "cost_per_ticket_usd": self.cost_usd / n,
            "cost_per_10k_usd": self.cost_usd / n * 10_000,
        }

    @property
    def cache_hit_rate(self) -> float:
        """Share of prompt tokens served from cache rather than charged in full."""
        read = sum(r.classification.cache_read_tokens for r in self.rows)
        billed = sum(
            r.classification.input_tokens + r.classification.cache_write_tokens
            for r in self.rows
        )
        total = read + billed
        return read / total if total else 0.0

    @property
    def cost_usd(self) -> float:
        price_in, price_out = PRICE_PER_MTOK.get(self.model, (0.0, 0.0))
        cost = 0.0
        for r in self.rows:
            c = r.classification
            cost += c.input_tokens * price_in
            cost += c.cache_write_tokens * price_in * CACHE_WRITE_MULTIPLIER
            cost += c.cache_read_tokens * price_in * CACHE_READ_MULTIPLIER
            cost += c.output_tokens * price_out
        return cost / 1_000_000


def load_tickets(path: str | Path) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["tickets"]


def run_version(
    tickets: list[dict[str, Any]],
    version: str,
    model: str | None = None,
    workers: int = 5,
) -> RunResult:
    """Classify every ticket with one prompt version, then apply the policy layer."""
    model = model or DEFAULT_MODEL
    client = anthropic.Anthropic(max_retries=3, timeout=60.0)

    def one(ticket: dict[str, Any]) -> Row:
        cls = classify(ticket["text"], version=version, model=model, client=client)
        # A failed classification still produces a routing decision — the ticket
        # goes to a person rather than nowhere. See policy.fallback_decision.
        decision = (
            policy.apply(cls.result, cls.schema_violations)
            if cls.result is not None
            else policy.fallback_decision(cls.error or "no result")
        )
        return Row(ticket=ticket, classification=cls, decision=decision)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(one, tickets))

    return RunResult(version=version, model=model, rows=rows)


def _trim(text: str, limit: int = 78) -> str:
    text = " ".join(text.split()).replace("|", "/")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_markdown(run: RunResult) -> str:
    """input -> expected -> actual -> pass/fail, one row per ticket."""
    m = run.metrics
    minimum = MIN_CACHEABLE_PREFIX.get(run.model)
    cache_note = ""
    if m["cache_read_tokens"] == 0 and m["cache_write_tokens"] == 0 and minimum:
        cache_note = f" (prompt is shorter than this model's {minimum}-token minimum)"

    lines = [
        f"# Triage run — prompt {run.version}, model {run.model}",
        "",
        f"- **pass rate (all three fields correct): {m['pass_rate']:.0%}**",
        f"- category {m['category_accuracy']:.0%} · priority {m['priority_accuracy']:.0%} · "
        f"review gate {m['review_gate_accuracy']:.0%}",
    ]
    if m["safety_recall"] is not None:
        lines.append(
            f"- safety recall {m['safety_recall']:.0%}"
            + (f", missed: {m['safety_missed']}" if m["safety_missed"] else "")
        )
    lines += [
        f"- prompt injection resisted: {m['injection_resisted']}",
        f"- off-schema outputs: {m['schema_violations']} · API errors: {m['api_errors']}",
        f"- latency: median {m['latency_ms_median']} ms, p90 {m['latency_ms_p90']} ms",
        f"- cache hit rate: {m['cache_hit_rate']:.0%}{cache_note}",
        f"- cost: ${m['cost_per_ticket_usd']:.5f}/ticket → "
        f"**${m['cost_per_10k_usd']:.2f} per 10k tickets**",
        "",
        "| # | input | expected | actual | result |",
        "|---|---|---|---|---|",
    ]
    for row in run.rows:
        e, a = row.ticket, row.decision
        gate_e = "review" if e["expected_requires_review"] else "auto"
        gate_a = "review" if a.requires_review else "auto"
        expected = f"{e['expected_category']}<br>{'/'.join(e['expected_priority'])} · {gate_e}"
        actual = f"{a.category}<br>{a.priority} · {gate_a}"
        if row.passed:
            result = "PASS"
        else:
            wrong = [
                name
                for name, ok in (
                    ("category", row.category_ok),
                    ("priority", row.priority_ok),
                    ("gate", row.review_ok),
                )
                if not ok
            ]
            result = "**FAIL** — " + ", ".join(wrong)
        tag = f"`{row.ticket['edge_case']}`<br>" if row.ticket["edge_case"] else ""
        lines.append(
            f"| {e['id']} | {tag}{_trim(e['text'])} | {expected} | {actual} | {result} |"
        )

    failures = [r for r in run.rows if not r.passed]
    if failures:
        lines += ["", "## Failures", ""]
        for row in failures:
            reason = (row.classification.result or {}).get(
                "reasoning", row.classification.error or ""
            )
            lines.append(
                f"- **{row.ticket['id']}** — expected "
                f"`{row.ticket['expected_category']}` / "
                f"{'/'.join(row.ticket['expected_priority'])}, got "
                f"`{row.decision.category}` / {row.decision.priority}. "
                f"Model said: {_trim(str(reason), 160)}"
            )
    return "\n".join(lines) + "\n"


def save(run: RunResult, out_dir: str | Path = "results", tag: str = "") -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = f"run_{run.version}{('_' + tag) if tag else ''}_{stamp}"
    json_path, md_path = out_dir / f"{base}.json", out_dir / f"{base}.md"
    json_path.write_text(
        json.dumps(
            {
                "version": run.version,
                "model": run.model,
                "metrics": run.metrics,
                "rows": [r.to_dict() for r in run.rows],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(run), encoding="utf-8")
    return json_path, md_path
