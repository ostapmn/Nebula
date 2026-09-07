#!/usr/bin/env python3
"""Run the whole ticket set through one prompt version and save the report."""

import argparse
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
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()

    tickets = runner.load_tickets(args.dataset)
    run = runner.run_version(tickets, version=args.version, model=args.model)
    print(runner.render_markdown(run))
    json_path, md_path = runner.save(run)
    print(f"saved: {json_path}\n       {md_path}")
    return 0 if run.metrics["api_errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
