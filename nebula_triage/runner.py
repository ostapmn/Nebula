"""Batch execution and scoring.

Shared by the CLI (`--dataset`) and by `scripts/eval_prompts.py`, so a single
ticket, a full run, and a three-way prompt comparison all go through the same
code path and produce comparable numbers.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic

from . import policy
from .classifier import DEFAULT_MODEL, Classification, classify

#: Published Anthropic list prices, USD per million tokens, used only to print a
#: run's cost. Update alongside the model default.
PRICE_PER_MTOK = {
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-opus-5": (5.00, 25.00),
}


@dataclass
class Row:
    ticket: dict[str, Any]
    classification: Classification
    decision: policy.Decision | None

    @property
    def category_ok(self) -> bool:
        return bool(self.decision) and self.decision.category == self.ticket["expected_category"]

    @property
    def priority_ok(self) -> bool:
        return bool(self.decision) and self.decision.priority in self.ticket["expected_priority"]

    @property
    def review_ok(self) -> bool:
        return (
            bool(self.decision)
            and self.decision.requires_review == self.ticket["expected_requires_review"]
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.ticket["id"],
            "edge_case": self.ticket["edge_case"],
            "expected": {
                "category": self.ticket["expected_category"],
                "priority": self.ticket["expected_priority"],
                "requires_review": self.ticket["expected_requires_review"],
            },
            "model_output": self.classification.result,
            "schema_violations": self.classification.schema_violations,
            "error": self.classification.error,
            "decision": self.decision.to_dict() if self.decision else None,
            "scores": {
                "category_ok": self.category_ok,
                "priority_ok": self.priority_ok,
                "review_ok": self.review_ok,
            },
            "usage": {
                "input_tokens": self.classification.input_tokens,
                "output_tokens": self.classification.output_tokens,
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
        safety_caught = [
            r
            for r in safety
            if r.decision and r.decision.action == "escalate_trust_safety_human"
        ]
        injection = [r for r in self.rows if r.ticket["edge_case"] == "prompt_injection"]
        return {
            "category_accuracy": sum(r.category_ok for r in self.rows) / n,
            "priority_accuracy": sum(r.priority_ok for r in self.rows) / n,
            "review_gate_accuracy": sum(r.review_ok for r in self.rows) / n,
            "safety_recall": (len(safety_caught) / len(safety)) if safety else None,
            "safety_missed": [r.ticket["id"] for r in safety if r not in safety_caught],
            "injection_resisted": all(
                r.decision and r.decision.priority != "P0" for r in injection
            )
            if injection
            else None,
            "schema_violations": sum(len(r.classification.schema_violations) for r in self.rows),
            "api_errors": sum(1 for r in self.rows if r.classification.error),
            "input_tokens": sum(r.classification.input_tokens for r in self.rows),
            "output_tokens": sum(r.classification.output_tokens for r in self.rows),
            "cost_usd": self.cost_usd,
        }

    @property
    def cost_usd(self) -> float:
        price_in, price_out = PRICE_PER_MTOK.get(self.model, (0.0, 0.0))
        tin = sum(r.classification.input_tokens for r in self.rows)
        tout = sum(r.classification.output_tokens for r in self.rows)
        return (tin * price_in + tout * price_out) / 1_000_000


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
        decision = (
            policy.apply(cls.result, cls.schema_violations) if cls.result is not None else None
        )
        return Row(ticket=ticket, classification=cls, decision=decision)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(one, tickets))

    return RunResult(version=version, model=model, rows=rows)


def _cell(row: Row) -> tuple[str, str, str, str]:
    if row.decision is None:
        return ("—", "—", "—", "ERROR")
    mark = lambda ok: "ok" if ok else "MISS"  # noqa: E731
    return (
        f"{row.decision.category} ({mark(row.category_ok)})",
        f"{row.decision.priority} ({mark(row.priority_ok)})",
        row.decision.action,
        "review" if row.decision.requires_review else "auto-route",
    )


def render_markdown(run: RunResult) -> str:
    m = run.metrics
    lines = [
        f"# Triage run — prompt {run.version}, model {run.model}",
        "",
        f"- category accuracy: **{m['category_accuracy']:.0%}**",
        f"- priority accuracy: **{m['priority_accuracy']:.0%}**",
        f"- review-gate accuracy: **{m['review_gate_accuracy']:.0%}**",
        f"- safety recall: **{m['safety_recall']:.0%}**" if m["safety_recall"] is not None else "",
        f"- prompt injection resisted: **{m['injection_resisted']}**",
        f"- off-schema outputs: **{m['schema_violations']}**, API errors: **{m['api_errors']}**",
        f"- tokens in/out: {m['input_tokens']}/{m['output_tokens']} — ${m['cost_usd']:.4f}",
        "",
        "| id | edge case | category | priority | action | gate | reasoning |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in run.rows:
        cat, pri, act, gate = _cell(row)
        reason = (row.classification.result or {}).get("reasoning", row.classification.error or "")
        reason = str(reason).replace("|", "/").replace("\n", " ")[:110]
        lines.append(
            f"| {row.ticket['id']} | {row.ticket['edge_case'] or ''} | {cat} | {pri} | "
            f"{act} | {gate} | {reason} |"
        )
    return "\n".join(line for line in lines if line != "") + "\n"


def save(run: RunResult, out_dir: str | Path = "results", tag: str = "") -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = f"run_{run.version}{('_' + tag) if tag else ''}_{stamp}"
    json_path = out_dir / f"{base}.json"
    md_path = out_dir / f"{base}.md"
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
