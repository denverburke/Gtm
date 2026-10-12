"""Cross-channel paid media: Google, Microsoft, Meta and LinkedIn campaign performance.

Inputs (in clients/<client>/data/): any of
  google_ads_campaigns*.csv, bing_ads_campaigns*.csv, meta_ads*.csv, linkedin_ads*.csv
Optional *_previous*.csv versions of each enable period-over-period deltas.
"""
from __future__ import annotations

import pandas as pd

from .common import find_file, fmt_money, load_csv, md_table

CHANNELS = ["google_ads", "bing_ads", "meta_ads", "linkedin_ads"]
NUM = ["impressions", "clicks", "cost", "conversions", "conv_value"]


def load_channel(cfg: dict, stem: str, previous: bool) -> pd.DataFrame | None:
    pats = [f"{stem}_campaigns_previous*.csv", f"{stem}_previous*.csv"] if previous else \
        [f"{stem}_campaigns_current*.csv", f"{stem}_campaigns*.csv", f"{stem}*.csv"]
    for pat in pats:
        p = find_file(cfg, pat)
        if p and "search_terms" not in p.name and (previous or "previous" not in p.name):
            d = load_csv(p, NUM)
            if "cost" not in d.columns:
                return None
            for c in NUM:
                d[c] = d[c].fillna(0) if c in d.columns else 0.0
            d["channel"] = stem
            return d
    return None


def _roll(d: pd.DataFrame, keys) -> pd.DataFrame:
    g = d.groupby(keys, as_index=False)[NUM].sum()
    g["ctr"] = g["clicks"] / g["impressions"].where(g["impressions"] > 0)
    g["cpc"] = g["cost"] / g["clicks"].where(g["clicks"] > 0)
    g["cpa"] = g["cost"] / g["conversions"].where(g["conversions"] > 0)
    return g


def report(cfg: dict) -> tuple[str, dict]:
    cur = [d for s in CHANNELS if (d := load_channel(cfg, s, False)) is not None]
    if not cur:
        raise SystemExit("No campaign exports found (google_ads_campaigns*.csv, meta_ads*.csv, linkedin_ads*.csv …)")
    cur = pd.concat(cur, ignore_index=True)
    prev = [d for s in CHANNELS if (d := load_channel(cfg, s, True)) is not None]
    prev = pd.concat(prev, ignore_index=True) if prev else None

    ch = _roll(cur, ["channel"])
    if prev is not None:
        pch = _roll(prev, ["channel"]).set_index("channel")
        ch["cost_Δ%"] = ch.apply(lambda r: (r.cost / pch.cost.get(r.channel, float("nan")) - 1) * 100, axis=1)
        ch["cpa_Δ%"] = ch.apply(lambda r: (r.cpa / pch.cpa.get(r.channel, float("nan")) - 1) * 100, axis=1)

    camp = _roll(cur, ["channel", "campaign"]) if "campaign" in cur.columns else pd.DataFrame()
    targets = cfg.get("channel_targets", {}) or {}
    default_cpa = cfg.get("target_cpa") or float("inf")
    flags = pd.DataFrame()
    if not camp.empty:
        camp["target_cpa"] = camp["channel"].map(lambda c: (targets.get(c) or {}).get("cpa", default_cpa))
        min_spend = cfg["thresholds"].get("campaign_min_spend", 200)
        flags = camp[(camp["cost"] >= min_spend) &
                     ((camp["conversions"] == 0) | (camp["cpa"] > camp["target_cpa"] * 1.3))] \
            .sort_values("cost", ascending=False)[["channel", "campaign", "cost", "conversions", "cpa", "target_cpa"]]
        stars = camp[(camp["conversions"] >= 3) & (camp["cpa"] < camp["target_cpa"] * 0.7)] \
            .sort_values("conversions", ascending=False)[["channel", "campaign", "cost", "conversions", "cpa"]]
    else:
        stars = pd.DataFrame()

    ch["ctr"] = ch["ctr"].map(lambda v: f"{v:.2%}" if pd.notna(v) else "–")
    total = cur[NUM].sum()
    md = [f"# Paid media — {cfg['name']}\n",
          f"Total spend {fmt_money(total.cost, cfg)}, {total.conversions:,.0f} platform conversions, "
          f"blended CPA {fmt_money(total.cost / total.conversions, cfg) if total.conversions else '–'}.\n",
          "## By channel\n", md_table(ch, 10),
          "\n## Campaigns over target CPA or spending without converting\n", md_table(flags, 15),
          "\n## Campaigns beating target by 30%+ (scale candidates — check impression share / frequency first)\n",
          md_table(stars, 10),
          "\n_Platform conversions are self-reported. Cross-check against the funnel report's HubSpot-sourced numbers._\n"]
    return "\n".join(md), {"spend": float(total.cost), "conversions": float(total.conversions),
                           "flagged_campaigns": len(flags), "channels": ch.to_dict("records")}
