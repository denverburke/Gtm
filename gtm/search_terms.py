"""Search term insights and keyword ↔ campaign ↔ landing page alignment.

Inputs (in clients/<client>/data/):
  google_ads_search_terms*.csv   Google Ads > Insights & reports > Search terms
  bing_ads_search_terms*.csv     Microsoft Ads > Reports > Search query
  gsc_queries_current*.csv       (optional) enables paid ↔ organic overlap

Config used (client.yaml): brand_terms, brand_campaign_pattern, campaign_themes,
target_cpa, thresholds.*
"""
from __future__ import annotations

import re
from collections import defaultdict

import pandas as pd

from .common import find_file, fmt_money, is_brand, load_csv, md_table

NUM = ["impressions", "clicks", "cost", "conversions", "conv_value"]
STOP = {"the", "a", "an", "for", "of", "in", "to", "and", "on", "with", "near", "me", "my", "is", "best"}


def load_terms(cfg: dict) -> pd.DataFrame:
    frames = []
    for engine, pat in (("google", "google_ads_search_terms*.csv"), ("bing", "bing_ads_search_terms*.csv")):
        p = find_file(cfg, pat)
        if p:
            d = load_csv(p, NUM)
            d["engine"] = engine
            frames.append(d)
    if not frames:
        raise SystemExit("No search term reports found (google_ads_search_terms*.csv / bing_ads_search_terms*.csv)")
    df = pd.concat(frames, ignore_index=True)
    for c in NUM:
        df[c] = df[c].fillna(0) if c in df.columns else 0.0
    df["query"] = df["query"].astype(str).str.lower().str.strip()
    for c in ("campaign", "ad_group", "keyword", "match_type"):
        if c not in df.columns:
            df[c] = ""
    df["brand_query"] = df["query"].map(lambda q: is_brand(q, cfg))
    pat = cfg.get("brand_campaign_pattern", "brand")
    df["brand_campaign"] = df["campaign"].astype(str).str.contains(pat, case=False, regex=True)
    return df


def ngrams(df: pd.DataFrame, n_max: int = 3) -> pd.DataFrame:
    agg = defaultdict(lambda: [0.0, 0.0, 0.0, 0])  # cost, conv, clicks, terms
    for q, cost, conv, clicks in df[["query", "cost", "conversions", "clicks"]].itertuples(index=False):
        toks = [t for t in re.findall(r"[a-z0-9']+", q)]
        seen = set()
        for n in range(1, n_max + 1):
            for i in range(len(toks) - n + 1):
                g = " ".join(toks[i:i + n])
                if n == 1 and g in STOP or g in seen:
                    continue
                seen.add(g)
                a = agg[g]
                a[0] += cost; a[1] += conv; a[2] += clicks; a[3] += 1
    out = pd.DataFrame([(g, *v) for g, v in agg.items()], columns=["ngram", "cost", "conversions", "clicks", "terms"])
    out["cpa"] = out["cost"] / out["conversions"].where(out["conversions"] > 0)
    return out


def analyse(cfg: dict) -> dict:
    df = load_terms(cfg)
    th = cfg["thresholds"]
    target_cpa = cfg.get("target_cpa") or 100
    waste_floor = th.get("waste_min_spend", target_cpa * 0.5)

    by_q = (df.groupby(["query", "engine", "campaign"], as_index=False)
            .agg(cost=("cost", "sum"), clicks=("clicks", "sum"), conversions=("conversions", "sum"),
                 conv_value=("conv_value", "sum"), keyword=("keyword", "first"), match_type=("match_type", "first"),
                 brand_query=("brand_query", "first"), brand_campaign=("brand_campaign", "first")))
    by_q["cpa"] = by_q["cost"] / by_q["conversions"].where(by_q["conversions"] > 0)

    waste = by_q[(by_q["conversions"] == 0) & (by_q["cost"] >= waste_floor)].sort_values("cost", ascending=False)

    grams = ngrams(df)
    neg_grams = grams[(grams["conversions"] == 0) & (grams["cost"] >= waste_floor) & (grams["terms"] >= 2)] \
        .sort_values("cost", ascending=False)

    kw_set = set(df["keyword"].astype(str).str.lower().str.strip("[]\"+ ").tolist())
    promote = by_q[(by_q["conversions"] >= th.get("promote_min_conversions", 2)) &
                   ~by_q["query"].isin(kw_set)].sort_values("conversions", ascending=False)
    promote = promote[(promote["cpa"] <= target_cpa * 1.2) | promote["cpa"].isna()]

    expensive = by_q[(by_q["conversions"] > 0) & (by_q["cpa"] > target_cpa * th.get("cpa_overrun", 1.5))] \
        .sort_values("cost", ascending=False)

    leakage = pd.concat([
        by_q[by_q["brand_query"] & ~by_q["brand_campaign"]].assign(issue="brand term in non-brand campaign"),
        by_q[~by_q["brand_query"] & by_q["brand_campaign"]].assign(issue="non-brand term in brand campaign"),
    ]).sort_values("cost", ascending=False)

    # Theme routing: query mentions theme X but was served by a campaign mapped to a different theme
    themes: dict = cfg.get("campaign_themes", {}) or {}
    misrouted = []
    if themes:
        for r in by_q.itertuples(index=False):
            if r.brand_query and r.brand_campaign:
                continue  # brand campaign owns brand queries regardless of product theme
            hits = [camp for camp, terms in themes.items() if any(t.lower() in r.query for t in terms)]
            if hits and not any(h.lower() in str(r.campaign).lower() for h in hits):
                misrouted.append({"query": r.query, "served_by": r.campaign, "should_be": " / ".join(hits),
                                  "cost": r.cost, "conversions": r.conversions})
    misrouted = pd.DataFrame(misrouted).sort_values("cost", ascending=False) if misrouted else pd.DataFrame()

    # Cross-engine: converting on Google, not running / not converting on Bing
    eng = df.groupby(["query", "engine"])[["cost", "conversions"]].sum().unstack(fill_value=0)
    gap = pd.DataFrame()
    if "bing" in df["engine"].values and "google" in df["engine"].values:
        eng.columns = [f"{a}_{b}" for a, b in eng.columns]
        gap = eng[(eng["conversions_google"] >= 2) & (eng["cost_bing"] == 0)].sort_values(
            "conversions_google", ascending=False).reset_index()

    overlap = organic_overlap(cfg, by_q)

    totals = {
        "spend": float(df["cost"].sum()), "conversions": float(df["conversions"].sum()),
        "wasted_spend": float(waste["cost"].sum()),
        "brand_spend_share": float(df.loc[df["brand_query"], "cost"].sum() / max(df["cost"].sum(), 1)),
    }
    return {"totals": totals, "waste": waste, "neg_grams": neg_grams, "promote": promote, "expensive": expensive,
            "leakage": leakage, "misrouted": misrouted, "engine_gap": gap, **overlap}


def organic_overlap(cfg: dict, by_q: pd.DataFrame) -> dict:
    p = find_file(cfg, "gsc_queries_current*.csv")
    if not p:
        return {}
    g = load_csv(p, ["clicks", "impressions", "position"])
    g["query"] = g["query"].astype(str).str.lower().str.strip()
    paid = by_q.groupby("query", as_index=False)[["cost", "conversions"]].sum()
    m = paid.merge(g[["query", "position", "clicks"]].rename(columns={"clicks": "organic_clicks",
                                                                      "position": "organic_pos"}), on="query")
    return {
        # Paying for clicks we'd likely win organically → candidates for a holdout test, not auto-pause
        "paid_and_top3": m[(m["organic_pos"] <= 3)].sort_values("cost", ascending=False),
        # Paid proves the term converts, organic is close → SEO brief
        "seo_opportunity": m[(m["conversions"] > 0) & (m["organic_pos"] > 7.5) & (m["organic_pos"] <= 20)]
        .sort_values("conversions", ascending=False),
    }


def report(cfg: dict) -> tuple[str, dict]:
    r = analyse(cfg)
    t = r["totals"]
    money = lambda x: fmt_money(x, cfg)  # noqa: E731
    md = [f"# Search terms & alignment — {cfg['name']}\n",
          f"- Spend {money(t['spend'])}, conversions {t['conversions']:,.0f}, "
          f"blended CPA {money(t['spend'] / t['conversions']) if t['conversions'] else '–'} "
          f"(target {money(cfg.get('target_cpa') or 0)})",
          f"- Zero-conversion spend above threshold: **{money(t['wasted_spend'])}** "
          f"({t['wasted_spend'] / max(t['spend'], 1):.0%} of spend)",
          f"- Brand share of spend: {t['brand_spend_share']:.0%}\n",
          "## Negative keyword candidates — search terms\n", md_table(r["waste"][["query", "engine", "campaign", "cost", "clicks"]], 20),
          "\n## Negative keyword candidates — recurring n-grams\n", md_table(r["neg_grams"][["ngram", "terms", "cost", "clicks"]], 15),
          "\n## Promote to exact-match keywords\n", md_table(r["promote"][["query", "engine", "campaign", "conversions", "cpa", "match_type"]], 15),
          "\n## Converting but over CPA target\n", md_table(r["expensive"][["query", "campaign", "cost", "conversions", "cpa"]], 10),
          "\n## Brand / non-brand leakage\n", md_table(r["leakage"][["query", "campaign", "issue", "cost"]], 10),
          "\n## Theme misrouting (query served by the wrong campaign)\n", md_table(r["misrouted"], 15),
          "\n## Converting on Google, not live on Microsoft Ads\n", md_table(r["engine_gap"], 10)]
    if "paid_and_top3" in r:
        md += ["\n## Paying for terms already ranking top 3 organically (holdout-test candidates)\n",
               md_table(r["paid_and_top3"], 10),
               "\n## Paid-proven terms in organic striking distance (SEO brief candidates)\n",
               md_table(r["seo_opportunity"], 10)]
    summary = {**t, "negatives": len(r["waste"]), "promote": len(r["promote"]), "misrouted": len(r["misrouted"])}
    return "\n".join(md), summary
