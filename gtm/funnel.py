"""HubSpot funnel analysis by source, joined to paid media spend.

Inputs (in clients/<client>/data/):
  hubspot_contacts*.csv   Contacts export with: Original Source, Original Source Drill-Down 1,
                          Lifecycle Stage, Create Date, Became a MQL/SQL/Opportunity/Customer Date,
                          (optional) Recent Deal Amount / Total Revenue
  google_ads_campaigns*.csv, bing_ads_campaigns*.csv, meta_ads*.csv, linkedin_ads*.csv  (optional)
                          Campaign-level exports → cost per MQL / SQL / customer by channel

Stage reach is "ever reached" (has a stage date), not current lifecycle, so contacts who
went MQL → customer still count as MQLs. Cohort = contacts created in the period.
"""
from __future__ import annotations

import pandas as pd

from . import paid_media
from .common import load_csv, md_table, require_file

STAGES = ["lead_date", "mql_date", "sql_date", "opp_date", "customer_date"]
STAGE_LABEL = {"lead_date": "Leads", "mql_date": "MQL", "sql_date": "SQL", "opp_date": "Opp", "customer_date": "Customer"}
LIFECYCLE_ORDER = ["subscriber", "lead", "marketingqualifiedlead", "salesqualifiedlead", "opportunity", "customer"]

# Which spend file feeds which HubSpot (source, drill-down) bucket. Override in client.yaml: spend_mapping
DEFAULT_SPEND_MAP = {
    "google_ads": ("PAID_SEARCH", "google"),
    "bing_ads": ("PAID_SEARCH", "bing"),
    "meta_ads": ("PAID_SOCIAL", "facebook"),
    "linkedin_ads": ("PAID_SOCIAL", "linkedin"),
}


def _src_key(s: str) -> str:
    return str(s).strip().upper().replace(" ", "_")


def load_contacts(cfg: dict) -> pd.DataFrame:
    df = load_csv(require_file(cfg, "hubspot_contacts*.csv", "HubSpot contacts export"), ["deal_amount"])
    df["source"] = df.get("source", "UNKNOWN").map(_src_key) if "source" in df.columns else "UNKNOWN"
    df["source_drilldown"] = df["source_drilldown"].astype(str).str.lower() if "source_drilldown" in df.columns else ""
    for c in ["create_date", *STAGES]:
        df[c] = pd.to_datetime(df[c], errors="coerce", dayfirst=cfg.get("dayfirst_dates", True)) \
            if c in df.columns else pd.NaT
    # Backfill missing stage dates from current lifecycle stage (ever-reached semantics)
    if "lifecycle_stage" in df.columns:
        lc = df["lifecycle_stage"].astype(str).str.lower().str.replace(r"[^a-z]", "", regex=True)
        rank = lc.map({s: i for i, s in enumerate(LIFECYCLE_ORDER)}).fillna(-1)
        for i, st in enumerate(STAGES, start=1):
            df.loc[df[st].isna() & (rank >= i), st] = df["create_date"]
    df.loc[df["lead_date"].isna(), "lead_date"] = df["create_date"]
    if "deal_amount" not in df.columns:
        df["deal_amount"] = 0.0
    return df


def period_filter(df: pd.DataFrame, cfg: dict, start=None, end=None) -> pd.DataFrame:
    start = pd.to_datetime(start or cfg.get("period_start")) if (start or cfg.get("period_start")) else None
    end = pd.to_datetime(end or cfg.get("period_end")) if (end or cfg.get("period_end")) else None
    m = pd.Series(True, index=df.index)
    if start is not None:
        m &= df["create_date"] >= start
    if end is not None:
        m &= df["create_date"] <= end
    return df[m]


def funnel_by(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    g = df.groupby(keys)
    out = pd.DataFrame({STAGE_LABEL[s]: g[s].count() for s in STAGES})
    out["Revenue"] = df[df["customer_date"].notna()].groupby(keys)["deal_amount"].sum()
    out = out.fillna(0)
    out["Lead→MQL"] = out["MQL"] / out["Leads"].where(out["Leads"] > 0)
    out["MQL→SQL"] = out["SQL"] / out["MQL"].where(out["MQL"] > 0)
    out["SQL→Opp"] = out["Opp"] / out["SQL"].where(out["SQL"] > 0)
    out["Opp→Won"] = out["Customer"] / out["Opp"].where(out["Opp"] > 0)
    out["Lead→Won"] = out["Customer"] / out["Leads"].where(out["Leads"] > 0)
    return out.sort_values("Leads", ascending=False).reset_index()


def velocity(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["days_to_mql"] = (d["mql_date"] - d["create_date"]).dt.days
    d["days_mql_to_sql"] = (d["sql_date"] - d["mql_date"]).dt.days
    d["days_sql_to_won"] = (d["customer_date"] - d["sql_date"]).dt.days
    return d.groupby("source")[["days_to_mql", "days_mql_to_sql", "days_sql_to_won"]].median().round(1).reset_index()


def load_spend(cfg: dict) -> pd.DataFrame:
    mapping = {**DEFAULT_SPEND_MAP, **{k: tuple(v) for k, v in (cfg.get("spend_mapping") or {}).items()}}
    rows = []
    for stem, (src, drill) in mapping.items():
        d = paid_media.load_channel(cfg, stem, previous=False)
        if d is None:
            continue
        rows.append({"channel": stem, "source": _src_key(src), "source_drilldown": drill,
                     "cost": d["cost"].sum(), "platform_conversions": d["conversions"].sum()})
    return pd.DataFrame(rows)


def cost_per_stage(df: pd.DataFrame, spend: pd.DataFrame) -> pd.DataFrame:
    if spend.empty:
        return pd.DataFrame()
    rows = []
    for r in spend.itertuples(index=False):
        sub = df[(df["source"] == r.source) & df["source_drilldown"].str.contains(r.source_drilldown, na=False)]
        n = {STAGE_LABEL[s]: sub[s].notna().sum() for s in STAGES}
        rev = sub.loc[sub["customer_date"].notna(), "deal_amount"].sum()
        rows.append({"channel": r.channel, "spend": r.cost, "platform_conv": r.platform_conversions,
                     "hs_leads": n["Leads"], "MQL": n["MQL"], "SQL": n["SQL"], "Customer": n["Customer"],
                     "CPL": r.cost / n["Leads"] if n["Leads"] else None,
                     "Cost/SQL": r.cost / n["SQL"] if n["SQL"] else None,
                     "CAC": r.cost / n["Customer"] if n["Customer"] else None,
                     "ROAS": rev / r.cost if r.cost else None,
                     # >1.5 means the ad platform claims far more conversions than HubSpot sees: tracking/dedup issue
                     "platform_vs_hs": r.platform_conversions / n["Leads"] if n["Leads"] else None})
    return pd.DataFrame(rows)


def report(cfg: dict, start=None, end=None) -> tuple[str, dict]:
    df = period_filter(load_contacts(cfg), cfg, start, end)
    if df.empty:
        raise SystemExit("No contacts in the selected period.")
    by_src = funnel_by(df, ["source"])
    by_drill = funnel_by(df, ["source", "source_drilldown"])
    spend = cost_per_stage(df, load_spend(cfg))
    vel = velocity(df)

    overall = funnel_by(df.assign(all="all"), ["all"]).iloc[0]
    # Flag sources whose MQL→SQL is materially below the account average (lead quality problem)
    avg = overall["MQL→SQL"]
    weak = by_src[(by_src["MQL"] >= cfg["thresholds"].get("funnel_min_mql", 10)) &
                  (by_src["MQL→SQL"] < avg * 0.7)]

    rate_cols = ["Lead→MQL", "MQL→SQL", "SQL→Opp", "Opp→Won", "Lead→Won"]
    fmt = by_src.copy()
    for c in rate_cols:
        fmt[c] = fmt[c].map(lambda v: f"{v:.0%}" if pd.notna(v) else "–")
    md = [f"# HubSpot funnel by source — {cfg['name']}\n",
          f"Cohort: {len(df):,} contacts created {df['create_date'].min():%d %b %Y} – {df['create_date'].max():%d %b %Y}. "
          f"Overall Lead→MQL {overall['Lead→MQL']:.0%}, MQL→SQL {overall['MQL→SQL']:.0%}, "
          f"Lead→Won {overall['Lead→Won']:.1%}.\n",
          "## Funnel by original source\n", md_table(fmt, 20),
          "\n## Sources under-converting MQL→SQL (<70% of account average)\n",
          md_table(weak[["source", "MQL", "SQL", "MQL→SQL"]], 10),
          "\n## Paid channels: spend vs HubSpot outcomes\n", md_table(spend, 10),
          "\n_`platform_vs_hs` > 1.5 = ad platform reports far more conversions than HubSpot received — check tracking._\n",
          "\n## Median days between stages by source\n", md_table(vel, 15),
          "\n## Drill-down (top 20 by leads)\n", md_table(by_drill[["source", "source_drilldown", "Leads", "MQL", "SQL", "Customer", "Revenue"]], 20)]
    summary = {"contacts": len(df), "overall": {k: float(overall[k]) for k in rate_cols if pd.notna(overall[k])},
               "weak_sources": weak["source"].tolist(),
               "paid": spend.to_dict("records") if not spend.empty else []}
    return "\n".join(md), summary
