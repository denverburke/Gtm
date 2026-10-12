"""CLI: python -m gtm <analysis> --client <slug> [--out]

Analyses: rank-shifts, search-terms, funnel, paid-media, all
Data pull: python -m gtm fetch --client <slug> [--source google_ads,bing_ads,hubspot,gsc,semrush] [--days 28]
Optional --start/--end YYYY-MM-DD set the HubSpot cohort window.
With --out, writes reports/<client>/<date>-<analysis>.md and a .json summary for the agents.
"""
from __future__ import annotations

import argparse
import importlib
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
    ap.add_argument("analysis", choices=[*ANALYSES, "all", "fetch"])
    ap.add_argument("--client", required=True)
    ap.add_argument("--out", action="store_true", help="write markdown + json into reports/<client>/")
    ap.add_argument("--start", help="cohort start date for the funnel (overrides client.yaml period_start)")
    ap.add_argument("--end", help="cohort end date for the funnel (overrides client.yaml period_end)")
    ap.add_argument("--source", help="fetch: comma-separated sources (default: every source under accounts: "
                                     "in client.yaml). Options: google_ads, bing_ads, hubspot, gsc, semrush")
    ap.add_argument("--days", type=int, default=28, help="fetch: length of current and previous periods")
    args = ap.parse_args(argv)

    cfg = load_client(args.client)
    if args.start:
        cfg["period_start"] = args.start
    if args.end:
        cfg["period_end"] = args.end
    if args.analysis == "fetch":
        sources = args.source.split(",") if args.source else list((cfg.get("accounts") or {}))
        return fetch(cfg, sources, args.days)
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


FETCHERS = {"google_ads": "google_ads", "bing_ads": "microsoft_ads", "hubspot": "hubspot",
            "gsc": "search_console", "semrush": "semrush"}


def fetch(cfg: dict, sources: list[str], days: int) -> int:
    from .fetch import NotReadOnlyError, periods
    p = periods(days)
    print(f"Periods: current {p['current'][0]}..{p['current'][1]}, previous {p['previous'][0]}..{p['previous'][1]}")
    if not sources:
        print("No sources: add an accounts: section to client.yaml or pass --source.", file=sys.stderr)
        return 1
    failures = 0
    for src in (s.strip() for s in sources):
        try:
            if src not in FETCHERS:
                raise SystemExit(f"unknown source {src!r}; options: {', '.join(FETCHERS)}")
            mod = importlib.import_module(f".fetch.{FETCHERS[src]}", __package__)
            for line in mod.fetch(cfg, p):
                print(f"[{src}] wrote {line}")
        except NotReadOnlyError as e:  # never fall through to a pull with write-capable credentials
            print(f"[{src}] BLOCKED: {e}", file=sys.stderr)
            failures += 1
        except SystemExit as e:
            print(f"[{src}] skipped: {e}", file=sys.stderr)
            failures += 1
        except Exception as e:  # one source failing shouldn't stop the others
            print(f"[{src}] failed: {e}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
