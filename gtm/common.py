"""Shared loaders: client config, CSV ingestion with header normalisation, number cleaning.

Every platform exports slightly different column names (and they change them).
We map known aliases onto one canonical schema so the analysis modules never
care whether a file came from Google Ads, Microsoft Ads, Semrush or GSC.
"""
from __future__ import annotations

import glob
import os
import re
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
CLIENTS_DIR = ROOT / "clients"
REPORTS_DIR = ROOT / "reports"

# canonical name -> accepted export headers (compared lower-cased, punctuation-stripped)
ALIASES: dict[str, list[str]] = {
    # search / keyword
    "query": ["query", "top queries", "search term", "search query", "searchterm"],
    "keyword": ["keyword", "keyword text", "targeted keyword", "keywordtext"],
    "match_type": ["match type", "search term match type", "keyword match type", "delivered match type"],
    "campaign": ["campaign", "campaign name", "campaignname"],
    "ad_group": ["ad group", "ad group name", "adgroup", "ad set name", "ad set"],
    "url": ["url", "page", "top pages", "landing page", "final url", "landing page url"],
    "position": ["position", "avg position", "average position", "pos", "current position"],
    "previous_position": ["previous position", "prev position", "position previous", "last position"],
    "volume": ["search volume", "volume", "monthly volume", "avg monthly searches"],
    # performance
    "impressions": ["impressions", "impr", "impr.", "imps"],
    "clicks": ["clicks", "link clicks", "clicks (all)"],
    "cost": ["cost", "spend", "amount spent", "total spent", "amount spent (gbp)", "amount spent (usd)",
             "amount spent (eur)", "cost (gbp)", "cost (usd)", "spend (gbp)", "spend (usd)"],
    "conversions": ["conversions", "conv", "conv.", "all conv.", "results", "leads", "conversion"],
    "conv_value": ["conv. value", "conversion value", "conv value", "revenue", "purchase conversion value"],
    "ctr": ["ctr", "click-through rate"],
    "date": ["date", "day", "week", "reporting starts"],
    # hubspot
    "source": ["original source", "original traffic source", "hs_analytics_source", "source"],
    "source_drilldown": ["original source drill-down 1", "original traffic source drill-down 1",
                         "hs_analytics_source_data_1", "original source drill down 1"],
    "lifecycle_stage": ["lifecycle stage", "lifecyclestage"],
    "create_date": ["create date", "createdate", "created date"],
    "lead_date": ["became a lead date", "hs_lifecyclestage_lead_date"],
    "mql_date": ["became a marketing qualified lead date", "hs_lifecyclestage_marketingqualifiedlead_date", "mql date"],
    "sql_date": ["became a sales qualified lead date", "hs_lifecyclestage_salesqualifiedlead_date", "sql date"],
    "opp_date": ["became an opportunity date", "hs_lifecyclestage_opportunity_date", "opportunity date"],
    "customer_date": ["became a customer date", "hs_lifecyclestage_customer_date", "customer date"],
    "deal_amount": ["recent deal amount", "total revenue", "amount", "deal amount"],
}


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9()% ]+", "", str(h).strip().lower()).strip()


_LOOKUP = {}
for canon, alts in ALIASES.items():
    for a in alts:
        _LOOKUP.setdefault(_norm(a), canon)


def normalise_columns(df: pd.DataFrame, prefer: dict[str, str] | None = None) -> pd.DataFrame:
    """Rename known export headers to canonical names. First match wins per canonical column.

    `prefer` lets a caller force a mapping, e.g. {"keyword": "keyword"} in a search-terms
    report where both "Search term" and "Keyword" exist.
    """
    prefer = prefer or {}
    rename, taken = {}, set()
    cols = list(df.columns)
    # Explicit preferences first
    for raw in cols:
        n = _norm(raw)
        if n in prefer and prefer[n] not in taken:
            rename[raw] = prefer[n]
            taken.add(prefer[n])
    for raw in cols:
        if raw in rename:
            continue
        canon = _LOOKUP.get(_norm(raw))
        if canon and canon not in taken:
            rename[raw] = canon
            taken.add(canon)
    return df.rename(columns=rename)


def to_num(s: pd.Series) -> pd.Series:
    """'£1,234.50' / '12.3%' / '--' / '< 10' -> float."""
    if pd.api.types.is_numeric_dtype(s):
        return s.astype(float)
    cleaned = (s.astype(str)
               .str.replace(r"[£$€,%<>\s]", "", regex=True)
               .replace({"--": None, "-": None, "": None, "nan": None, "None": None}))
    return pd.to_numeric(cleaned, errors="coerce")


def load_csv(path: str | Path, numeric: list[str] = (), prefer: dict[str, str] | None = None) -> pd.DataFrame:
    path = Path(path)
    # Google Ads / Microsoft Ads exports carry title rows above the header; sniff for it.
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        head = [next(fh, "") for _ in range(10)]
    skip = 0
    for i, line in enumerate(head):
        if line.count(",") >= 2 or line.count("\t") >= 2:
            skip = i
            break
    sep = "\t" if head[skip].count("\t") > head[skip].count(",") else ","
    df = pd.read_csv(path, skiprows=skip, sep=sep, encoding="utf-8-sig", encoding_errors="replace")
    df = normalise_columns(df, prefer)
    # Drop Google Ads "Total:" footer rows
    first = df.columns[0]
    df = df[~df[first].astype(str).str.lower().str.startswith("total")]
    for col in numeric:
        if col in df.columns:
            df[col] = to_num(df[col])
    return df.reset_index(drop=True)


def load_client(client: str) -> dict:
    cfg_path = CLIENTS_DIR / client / "client.yaml"
    if not cfg_path.exists():
        raise SystemExit(f"No config at {cfg_path}. Copy clients/_template/ to clients/{client}/ first.")
    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    cfg["_dir"] = CLIENTS_DIR / client
    cfg["_data"] = CLIENTS_DIR / client / "data"
    cfg.setdefault("name", client)
    cfg.setdefault("thresholds", {})
    return cfg


def find_file(cfg: dict, pattern: str) -> Path | None:
    """Most recently modified file in the client's data dir matching a glob."""
    hits = sorted(glob.glob(str(cfg["_data"] / pattern)), key=os.path.getmtime)
    return Path(hits[-1]) if hits else None


def require_file(cfg: dict, pattern: str, what: str) -> Path:
    p = find_file(cfg, pattern)
    if p is None:
        raise SystemExit(f"Missing {what}: expected a file matching clients/{cfg['_dir'].name}/data/{pattern}")
    return p


def is_brand(text: str, cfg: dict) -> bool:
    t = str(text).lower()
    return any(b.lower() in t for b in cfg.get("brand_terms", []))


def fmt_money(x: float, cfg: dict) -> str:
    sym = cfg.get("currency_symbol", "£")
    return f"{sym}{x:,.0f}" if pd.notna(x) else "–"


def md_table(df: pd.DataFrame, max_rows: int = 15) -> str:
    if df is None or df.empty:
        return "_None._\n"
    d = df.head(max_rows).copy()
    for c in d.columns:
        if pd.api.types.is_float_dtype(d[c]):
            d[c] = d[c].map(lambda v: "" if pd.isna(v) else (f"{v:,.2f}" if abs(v) < 10 else f"{v:,.0f}"))
    header = "| " + " | ".join(map(str, d.columns)) + " |"
    sep = "|" + "|".join("---" for _ in d.columns) + "|"
    rows = ["| " + " | ".join(str(v).replace("|", "/") for v in r) + " |" for r in d.itertuples(index=False)]
    more = f"\n_…and {len(df) - max_rows} more._" if len(df) > max_rows else ""
    return "\n".join([header, sep, *rows]) + more + "\n"
