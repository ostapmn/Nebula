#!/usr/bin/env python3
"""Run the same prompt and dataset across several models and compare them.

Answers the only question that matters for model choice here: which model gets
the routing right, how fast, and at what cost per 10k tickets.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from nebula_triage import runner  # noqa: E402

DEFAULT_MODELS = "claude-haiku-4-5,claude-sonnet-5,claude-opus-5"

ROWS = [
    ("pass rate (all 3 fields)", "pass_rate", "pct"),
    ("category accuracy", "category_accuracy", "pct"),
    ("priority accuracy", "priority_accuracy", "pct"),
    ("review-gate accuracy", "review_gate_accuracy", "pct"),
    ("safety recall", "safety_recall", "pct"),
    ("injection resisted", "injection_resisted", "raw"),
    ("off-schema outputs", "schema_violations", "raw"),
    ("API errors", "api_errors", "raw"),
    ("latency median (ms)", "latency_ms_median", "raw"),
    ("latency p90 (ms)", "latency_ms_p90", "raw"),
    ("cache hit rate", "cache_hit_rate", "pct"),
    ("cost per ticket", "cost_per_ticket_usd", "usd5"),
    ("cost per 10k tickets", "cost_per_10k_usd", "usd2"),
]


def fmt(value, kind):
    if value is None:
        return "n/a"
    if kind == "pct":
        return f"{value:.0%}"
    if kind == "usd5":
        return f"${value:.5f}"
    if kind == "usd2":
        return f"${value:.2f}"
    return str(value)


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="data/tickets.json")
    ap.add_argument("--models", default=DEFAULT_MODELS)
    ap.add_argument("--version", default="v3")
    ap.add_argument("--out", default="results/model_comparison.md")
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    tickets = runner.load_tickets(args.dataset)

    runs = {}
    for model in models:
        print(f"running {model} ...", file=sys.stderr)
        run = runner.run_version(tickets, version=args.version, model=model)
        runs[model] = run
        runner.save(run, tag=model.replace("claude-", ""))

    header = "| metric | " + " | ".join(models) + " |"
    sep = "|---" * (len(models) + 1) + "|"
    lines = [
        f"# Model comparison — prompt {args.version}, {len(tickets)} tickets",
        "",
        header,
        sep,
    ]
    for label, key, kind in ROWS:
        lines.append(
            f"| {label} | " + " | ".join(fmt(runs[m].metrics.get(key), kind) for m in models) + " |"
        )

    lines += ["", "## Where each model fails", ""]
    for model in models:
        failures = [r for r in runs[model].rows if not r.passed]
        if not failures:
            lines.append(f"**{model}** — no failures.")
            continue
        lines.append(f"**{model}** — {len(failures)} failure(s):")
        for row in failures:
            wrong = [
                n
                for n, ok in (
                    ("category", row.category_ok),
                    ("priority", row.priority_ok),
                    ("gate", row.review_ok),
                )
                if not ok
            ]
            lines.append(
                f"- {row.ticket['id']} ({row.ticket['edge_case'] or 'baseline'}): "
                f"{', '.join(wrong)} — expected `{row.ticket['expected_category']}`/"
                f"{'/'.join(row.ticket['expected_priority'])}, got "
                f"`{row.decision.category}`/{row.decision.priority}"
            )
        lines.append("")

    report = "\n".join(lines)
    print("\n" + report)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    out.with_suffix(".json").write_text(
        json.dumps({m: runs[m].metrics for m in models}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nsaved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
