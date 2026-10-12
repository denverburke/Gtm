"""CLI: python -m gtm <analysis> --client <slug> [--out]

Analyses: rank-shifts, search-terms, funnel, paid-media, all
Optional --start/--end YYYY-MM-DD set the HubSpot cohort window.
With --out, writes reports/<client>/<date>-<analysis>.md and a .json summary for the agents.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from . import funnel, paid_media, rank_shifts, search_terms
from .common import REPORTS_DIR, load_client

ANALYSES = {
    "rank-shifts": rank_shifts.report,
    "search-terms": search_terms.report,
    "funnel": funnel.report,
    "paid-media": paid_media.report,
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="gtm")
    ap.add_argument("analysis", choices=[*ANALYSES, "all"])
    ap.add_argument("--client", required=True)
    ap.add_argument("--out", action="store_true", help="write markdown + json into reports/<client>/")
    ap.add_argument("--start", help="cohort start date for the funnel (overrides client.yaml period_start)")
    ap.add_argument("--end", help="cohort end date for the funnel (overrides client.yaml period_end)")
    args = ap.parse_args(argv)

    cfg = load_client(args.client)
    if args.start:
        cfg["period_start"] = args.start
    if args.end:
        cfg["period_end"] = args.end
    todo = list(ANALYSES) if args.analysis == "all" else [args.analysis]
    today = dt.date.today().isoformat()
    failures = 0
    for name in todo:
        try:
            md, summary = ANALYSES[name](cfg)
        except SystemExit as e:  # missing inputs: report and carry on with the rest
            print(f"[{name}] skipped: {e}", file=sys.stderr)
            failures += 1
            continue
        print(md)
        print()
        if args.out:
            d = REPORTS_DIR / args.client
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{today}-{name}.md").write_text(md)
            (d / f"{today}-{name}.json").write_text(json.dumps(summary, indent=2, default=str))
    return 1 if failures == len(todo) else 0


if __name__ == "__main__":
    sys.exit(main())
