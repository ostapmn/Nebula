#!/usr/bin/env python3
"""Score every prompt version against the golden labels and print a comparison.

This is the script that makes docs/prompt-evolution.md checkable: the numbers in
that document come from here, not from memory.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from nebula_triage import runner  # noqa: E402
from nebula_triage.classifier import DEFAULT_MODEL  # noqa: E402

ROWS = [
    ("category accuracy", "category_accuracy", "pct"),
    ("priority accuracy", "priority_accuracy", "pct"),
    ("review-gate accuracy", "review_gate_accuracy", "pct"),
    ("safety recall", "safety_recall", "pct"),
    ("injection resisted", "injection_resisted", "raw"),
    ("off-schema outputs", "schema_violations", "raw"),
    ("cost (USD)", "cost_usd", "usd"),
]


def fmt(value, kind):
    if value is None:
        return "n/a"
    if kind == "pct":
        return f"{value:.0%}"
    if kind == "usd":
        return f"${value:.4f}"
    return str(value)


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="data/tickets.json")
    ap.add_argument("--versions", default="v1,v2,v3")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", default="results/eval_prompts.md")
    args = ap.parse_args()

    versions = [v.strip() for v in args.versions.split(",") if v.strip()]
    tickets = runner.load_tickets(args.dataset)

    runs = {}
    for version in versions:
        print(f"running {version} ...", file=sys.stderr)
        run = runner.run_version(tickets, version=version, model=args.model)
        runs[version] = run
        runner.save(run, tag="eval")

    header = "| metric | " + " | ".join(versions) + " |"
    sep = "|---" * (len(versions) + 1) + "|"
    lines = [
        f"# Prompt comparison — {args.model}, {len(tickets)} tickets",
        "",
        header,
        sep,
    ]
    for label, key, kind in ROWS:
        cells = [fmt(runs[v].metrics.get(key), kind) for v in versions]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")

    lines += ["", "## Per-ticket category outcome", "", header, sep]
    for i, ticket in enumerate(tickets):
        cells = []
        for v in versions:
            row = runs[v].rows[i]
            got = row.decision.category if row.decision else "ERROR"
            cells.append(got if row.category_ok else f"**{got}**")
        lines.append(f"| {ticket['id']} {ticket['edge_case'] or ''} | " + " | ".join(cells) + " |")
    lines += ["", "Bold = does not match the golden label.", ""]

    report = "\n".join(lines)
    print("\n" + report)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    Path(out.with_suffix(".json")).write_text(
        json.dumps({v: runs[v].metrics for v in versions}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nsaved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
