"""Command line entry point: `gcp-finops sample` and `gcp-finops report`."""

from __future__ import annotations

import argparse
from pathlib import Path

from .report import build_report
from .sample import write_sample
from .schema import load_csv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gcp-finops", description="Google Cloud cost analysis from billing export data.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sample = sub.add_parser("sample", help="Write a synthetic billing export CSV to try the tool.")
    p_sample.add_argument("--out", default="data/sample_billing.csv")
    p_sample.add_argument("--seed", type=int, default=42)

    p_report = sub.add_parser("report", help="Analyze a billing CSV and write a Markdown report.")
    p_report.add_argument("--input", default="data/sample_billing.csv")
    p_report.add_argument("--out", default="reports/cost_report.md")
    p_report.add_argument("--labels", default="team,env", help="Comma-separated labels every resource must carry.")
    p_report.add_argument("--top", type=int, default=10, help="How many SKUs to list.")

    args = parser.parse_args(argv)

    if args.command == "sample":
        n = write_sample(args.out, seed=args.seed)
        print(f"Wrote {n} rows to {args.out}")
    elif args.command == "report":
        df = load_csv(args.input)
        labels = tuple(l.strip() for l in args.labels.split(",") if l.strip())
        text = build_report(df, required_labels=labels, top=args.top)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        print(f"Wrote report to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
