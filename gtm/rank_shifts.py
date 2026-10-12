"""Ranking shifts from Semrush and/or Google Search Console.

Inputs (in clients/<client>/data/):
  semrush_positions*.csv   Semrush Organic Research > Positions export
                           (Keyword, Position, Previous position, Search Volume, URL)
  gsc_queries_current*.csv GSC Performance > Queries export for the current period
  gsc_queries_previous*.csv  … and the comparison period
  gsc_pages_current*.csv / gsc_pages_previous*.csv  (optional) Pages exports

Produces volume-weighted winners/losers, threshold crossings (top 3 / top 10),
page-level roll-ups and "CTR erosion" — position held but CTR fell, the usual
footprint of an AI Overview or new SERP feature landing on the query.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .common import find_file, is_brand, load_csv, md_table

SEMRUSH_NUM = ["position", "previous_position", "volume", "traffic"]
GSC_NUM = ["clicks", "impressions", "ctr", "position"]


def _bucket(p: float) -> str:
    if pd.isna(p) or p <= 0:
        return "not ranking"
    if p <= 3:
        return "top 3"
    if p <= 10:
        return "page 1"
    if p <= 20:
        return "page 2"
    return "20+"


def semrush_shifts(cfg: dict) -> dict:
    path = find_file(cfg, "semrush_positions*.csv")
    if not path:
        return {}
    df = load_csv(path, SEMRUSH_NUM, prefer={"keyword": "query"})
    df["previous_position"] = df.get("previous_position", pd.Series(np.nan, index=df.index))
    # Semrush uses 0 for "was not ranking"
    df.loc[df["previous_position"] == 0, "previous_position"] = np.nan
    df["volume"] = df["volume"].fillna(0) if "volume" in df.columns else 0.0
    df["delta"] = df["previous_position"] - df["position"]  # +ve = improved
    df["weighted"] = df["delta"].fillna(0) * np.log1p(df["volume"])
    df["brand"] = df["query"].map(lambda q: is_brand(q, cfg))
    df["was"] = df["previous_position"].map(_bucket)
    df["now"] = df["position"].map(_bucket)

    min_vol = cfg["thresholds"].get("rank_min_volume", 50)
    sig = df[(df["volume"] >= min_vol) & df["delta"].abs().ge(cfg["thresholds"].get("rank_min_delta", 3))]
    cols = ["query", "volume", "previous_position", "position", "delta", "url"]
    cols = [c for c in cols if c in df.columns]

    crossings = df[(df["was"] != df["now"]) & df["now"].isin(["top 3", "page 1"]) |
                   (df["was"].isin(["top 3", "page 1"]) & ~df["now"].isin(["top 3", "page 1"]))]
    crossings = crossings[cols + ["was", "now"]].sort_values("volume", ascending=False)

    new_kw = df[df["previous_position"].isna()].sort_values("volume", ascending=False)

    page = pd.DataFrame()
    if "url" in df.columns:
        page = (df.groupby("url")
                .agg(keywords=("query", "count"), net_weighted=("weighted", "sum"),
                     improved=("delta", lambda s: (s > 0).sum()), declined=("delta", lambda s: (s < 0).sum()))
                .sort_values("net_weighted").reset_index())

    return {
        "source": path.name,
        "tracked": len(df),
        "improved": int((df["delta"] > 0).sum()),
        "declined": int((df["delta"] < 0).sum()),
        "winners": sig[sig["delta"] > 0].sort_values("weighted", ascending=False)[cols],
        "losers": sig[sig["delta"] < 0].sort_values("weighted")[cols],
        "crossings": crossings,
        "new": new_kw[cols],
        "pages_declining": page[page["net_weighted"] < 0].head(10) if not page.empty else page,
        "pages_improving": page[page["net_weighted"] > 0].sort_values("net_weighted", ascending=False).head(10)
        if not page.empty else page,
    }


def _gsc_pair(cfg: dict, kind: str):
    cur = find_file(cfg, f"gsc_{kind}_current*.csv")
    prev = find_file(cfg, f"gsc_{kind}_previous*.csv")
    if not (cur and prev):
        return None
    key = "query" if kind == "queries" else "url"
    a = load_csv(cur, GSC_NUM)
    b = load_csv(prev, GSC_NUM)
    m = a.merge(b, on=key, how="outer", suffixes=("", "_prev")).fillna(
        {"clicks": 0, "impressions": 0, "clicks_prev": 0, "impressions_prev": 0})
    for c in ("ctr", "ctr_prev"):
        if c in m.columns and m[c].max() > 1:  # GSC exports CTR as "4.2%"
            m[c] = m[c] / 100
    m["click_delta"] = m["clicks"] - m["clicks_prev"]
    m["impr_delta"] = m["impressions"] - m["impressions_prev"]
    m["pos_delta"] = m["position_prev"] - m["position"]  # +ve = improved
    m["ctr_delta_pts"] = (m["ctr"] - m["ctr_prev"]) * 100
    return m, key, cur.name, prev.name


def gsc_shifts(cfg: dict) -> dict:
    pair = _gsc_pair(cfg, "queries")
    if not pair:
        return {}
    m, key, cur, prev = pair
    m["brand"] = m[key].map(lambda q: is_brand(q, cfg))
    min_impr = cfg["thresholds"].get("gsc_min_impressions", 100)
    sig = m[(m["impressions"] + m["impressions_prev"]) >= min_impr]
    cols = [key, "clicks_prev", "clicks", "click_delta", "position_prev", "position", "ctr_delta_pts"]

    # Position roughly held (±1) on page 1, impressions held, CTR down hard → SERP/AI Overview suspicion
    erosion = sig[(sig["pos_delta"].abs() <= 1) & (sig["position"] <= 10) &
                  (sig["impressions"] >= 0.8 * sig["impressions_prev"]) &
                  (sig["ctr_delta_pts"] <= -cfg["thresholds"].get("ctr_erosion_pts", 1.5))]

    # Striking distance: positions 8–20 with real impressions → cheapest SEO wins
    striking = sig[(sig["position"] > 7.5) & (sig["position"] <= 20) & ~sig["brand"]].sort_values(
        "impressions", ascending=False)

    totals = {}
    for seg, d in (("brand", m[m["brand"]]), ("non_brand", m[~m["brand"]])):
        totals[seg] = {"clicks": float(d["clicks"].sum()), "clicks_prev": float(d["clicks_prev"].sum()),
                       "impressions": float(d["impressions"].sum()),
                       "impressions_prev": float(d["impressions_prev"].sum())}

    out = {
        "source": f"{cur} vs {prev}",
        "totals": totals,
        "click_losers": sig.sort_values("click_delta")[cols].head(20),
        "click_winners": sig.sort_values("click_delta", ascending=False)[cols].head(20),
        "ctr_erosion": erosion.sort_values("ctr_delta_pts")[cols + ["impressions"]],
        "striking_distance": striking[[key, "impressions", "clicks", "position"]],
        "_merged": m,
    }
    pages = _gsc_pair(cfg, "pages")
    if pages:
        pm, pkey, _, _ = pages
        out["page_losers"] = pm.sort_values("click_delta")[[pkey, "clicks_prev", "clicks", "click_delta",
                                                            "position_prev", "position"]].head(15)
    return out


def _pct(a, b):
    return f"{(a - b) / b * 100:+.1f}%" if b else "n/a"


def report(cfg: dict) -> tuple[str, dict]:
    sem, gsc = semrush_shifts(cfg), gsc_shifts(cfg)
    if not sem and not gsc:
        raise SystemExit("No ranking data found. Add semrush_positions*.csv and/or gsc_queries_current/previous*.csv")
    md = [f"# Ranking shifts — {cfg['name']}\n"]
    summary = {}
    if gsc:
        md.append(f"## Search Console ({gsc['source']})\n")
        for seg, t in gsc["totals"].items():
            md.append(f"- **{seg.replace('_', '-')}**: clicks {t['clicks_prev']:,.0f} → {t['clicks']:,.0f} "
                      f"({_pct(t['clicks'], t['clicks_prev'])}), impressions {_pct(t['impressions'], t['impressions_prev'])}")
        md += ["\n### Biggest click losses\n", md_table(gsc["click_losers"], 10),
               "\n### Biggest click gains\n", md_table(gsc["click_winners"], 10),
               "\n### CTR erosion (position held, CTR fell — check for AI Overviews / SERP features)\n",
               md_table(gsc["ctr_erosion"], 15),
               "\n### Striking distance (non-brand, pos 8–20, by impressions)\n",
               md_table(gsc["striking_distance"], 15)]
        if "page_losers" in gsc:
            md += ["\n### Pages losing most clicks\n", md_table(gsc["page_losers"], 10)]
        summary["gsc"] = {"totals": gsc["totals"], "ctr_erosion_count": len(gsc["ctr_erosion"]),
                          "striking_distance_count": len(gsc["striking_distance"])}
    if sem:
        md += [f"\n## Semrush ({sem['source']})\n",
               f"{sem['tracked']} keywords: {sem['improved']} improved, {sem['declined']} declined.\n",
               "\n### Top losers (volume-weighted)\n", md_table(sem["losers"], 15),
               "\n### Top winners (volume-weighted)\n", md_table(sem["winners"], 15),
               "\n### Threshold crossings (entered/left page 1 or top 3)\n", md_table(sem["crossings"], 20),
               "\n### Pages with net decline\n", md_table(sem["pages_declining"], 10),
               "\n### New ranking keywords\n", md_table(sem["new"], 10)]
        summary["semrush"] = {k: sem[k] for k in ("tracked", "improved", "declined")}
        summary["semrush"]["losers"] = sem["losers"].head(10).to_dict("records")
    return "\n".join(md), summary
