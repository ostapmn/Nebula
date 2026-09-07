"""Command line entry point.

    python -m nebula_triage.cli "my subscription renewed and I want my money back"
    python -m nebula_triage.cli --dataset data/tickets.json
    python -m nebula_triage.cli --show-prompt --version v3
"""

from __future__ import annotations

import argparse
import json
import sys

from dotenv import load_dotenv

from . import policy, runner
from .classifier import DEFAULT_MODEL, classify
from .prompts import PROMPTS, VERSIONS


def _print_single(text: str, version: str, model: str, as_json: bool) -> int:
    cls = classify(text, version=version, model=model)
    if cls.error:
        print(f"error: {cls.error}", file=sys.stderr)
        return 1

    decision = policy.apply(cls.result, cls.schema_violations)
    payload = {
        "model_output": cls.result,
        "decision": decision.to_dict(),
        "schema_violations": cls.schema_violations,
        "usage": {"input_tokens": cls.input_tokens, "output_tokens": cls.output_tokens},
    }

    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    r = cls.result
    print(f"category      : {decision.category}")
    if r.get("secondary_categories"):
        print(f"  also        : {', '.join(r['secondary_categories'])}")
    print(f"priority      : {decision.priority}")
    print(f"next step     : {decision.action}")
    print(f"handling      : {'HUMAN REVIEW REQUIRED' if decision.requires_review else 'auto-route'}")
    print(f"sentiment     : {r.get('sentiment')}   confidence: {r.get('confidence'):.2f}"
          f"   language: {r.get('detected_language')}")
    print(f"reasoning     : {r.get('reasoning')}")
    if decision.applied_rules:
        print(f"policy rules  : {', '.join(decision.applied_rules)}")
    for reason in decision.review_reasons:
        print(f"  -> {reason}")
    if cls.schema_violations:
        print(f"schema issues : {'; '.join(cls.schema_violations)}")
    return 0


def _print_dataset(path: str, version: str, model: str) -> int:
    tickets = runner.load_tickets(path)
    print(f"Running {len(tickets)} tickets through prompt {version} on {model} ...\n")
    run = runner.run_version(tickets, version=version, model=model)
    print(runner.render_markdown(run))
    json_path, md_path = runner.save(run)
    print(f"saved: {json_path}\n       {md_path}")
    return 0 if run.metrics["api_errors"] == 0 else 1


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        prog="nebula-triage", description="Classify a Nebula support ticket."
    )
    parser.add_argument("text", nargs="?", help="ticket text to classify")
    parser.add_argument("--dataset", help="path to a tickets JSON file; runs the whole set")
    parser.add_argument("--version", default="v3", choices=VERSIONS, help="prompt version")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--json", action="store_true", help="raw JSON output")
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="print the fully rendered system prompt for --version and exit",
    )
    args = parser.parse_args(argv)

    # The V2/V3 prompts are assembled from taxonomy.py at import time, so the
    # source file shows a template rather than the text the model actually sees.
    if args.show_prompt:
        print(PROMPTS[args.version])
        return 0

    if args.dataset:
        return _print_dataset(args.dataset, args.version, args.model)
    if not args.text:
        parser.error("give a ticket text, or --dataset PATH")
    return _print_single(args.text, args.version, args.model, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
