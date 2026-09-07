#!/usr/bin/env python3
"""Run one prompt version N times and report where it disagrees with itself.

The classifier runs without `temperature` (Sonnet 5 rejects sampling parameters),
so identical inputs can produce different labels. A single 15-ticket run is
therefore weak evidence. This script turns that from an unknown into a number.
"""

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from nebula_triage import runner  # noqa: E402
from nebula_triage.classifier import DEFAULT_MODEL  # noqa: E402


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="data/tickets.json")
    ap.add_argument("--version", default="v3")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", default="results/stability_v3.md")
    args = ap.parse_args()

    tickets = runner.load_tickets(args.dataset)
    runs = []
    for i in range(args.runs):
        print(f"run {i + 1}/{args.runs} ...", file=sys.stderr)
        runs.append(runner.run_version(tickets, version=args.version, model=args.model))

    lines = [
        f"# Stability — prompt {args.version}, {args.model}, {args.runs} runs",
        "",
        "| id | edge case | category (runs) | priority (runs) | gate (runs) | stable |",
        "|---|---|---|---|---|---|",
    ]
    unstable = 0
    for idx, ticket in enumerate(tickets):
        cats = collections.Counter(r.rows[idx].decision.category for r in runs)
        pris = collections.Counter(r.rows[idx].decision.priority for r in runs)
        gates = collections.Counter(
            "review" if r.rows[idx].decision.requires_review else "auto" for r in runs
        )
        stable = len(cats) == 1 and len(pris) == 1 and len(gates) == 1
        unstable += not stable
        fmt = lambda c: ", ".join(f"{k}×{v}" for k, v in c.most_common())  # noqa: E731
        lines.append(
            f"| {ticket['id']} | {ticket['edge_case'] or ''} | {fmt(cats)} | {fmt(pris)} | "
            f"{fmt(gates)} | {'yes' if stable else '**no**'} |"
        )

    metrics = [r.metrics for r in runs]
    lines += [
        "",
        f"- tickets identical across all {args.runs} runs: "
        f"**{len(tickets) - unstable}/{len(tickets)}**",
        "- category accuracy per run: "
        + ", ".join(f"{m['category_accuracy']:.0%}" for m in metrics),
        "- priority accuracy per run: "
        + ", ".join(f"{m['priority_accuracy']:.0%}" for m in metrics),
        "- safety recall per run: " + ", ".join(f"{m['safety_recall']:.0%}" for m in metrics),
        "- safety tickets missed, any run: "
        + (str([m["safety_missed"] for m in metrics]) or "none"),
        "- injection resisted per run: "
        + ", ".join(str(m["injection_resisted"]) for m in metrics),
        f"- total cost: ${sum(r.cost_usd for r in runs):.4f}",
        "",
    ]
    report = "\n".join(lines)
    print("\n" + report)
    Path(args.out).write_text(report, encoding="utf-8")
    print(f"saved: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
