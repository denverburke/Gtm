"""Semrush Analytics API → semrush_positions_<date>.csv. Read-only.

The Analytics API has no write operations; the shared HTTP allow-list additionally pins the
report type to domain_organic. The real cost here is API units: domain_organic is billed per
returned line, so `limit` caps spend per run. Requires a Semrush Business plan with API units.

Env:          SEMRUSH_API_KEY
client.yaml:  accounts: {semrush: {domain: example.com, database: uk, limit: 2000}}

Note: "Previous Position" compares with Semrush's previous database snapshot, not necessarily
exactly 7 days ago. For strict week-on-week tracking of a fixed keyword set, use Position Tracking.
"""
from __future__ import annotations

import io
import os

import pandas as pd

from .http import ReadOnlySession

URL = "https://api.semrush.com/"
COLUMNS = "Ph,Po,Pp,Nq,Ur,Tr"
HEADERS = {"Ph": "Keyword", "Po": "Position", "Pp": "Previous position", "Nq": "Search Volume",
           "Ur": "URL", "Tr": "Traffic (%)"}


class ReadOnlySemrush:
    def __init__(self, session=None):
        self._key = os.environ.get("SEMRUSH_API_KEY")
        if not self._key and session is None:
            raise SystemExit("Semrush: missing environment secret SEMRUSH_API_KEY")
        self.http = session or ReadOnlySession()

    def domain_organic(self, domain: str, database: str, limit: int) -> pd.DataFrame:
        params = {"type": "domain_organic", "key": self._key, "domain": domain, "database": database,
                  "display_limit": int(limit), "display_sort": "tr_desc", "export_columns": COLUMNS}
        text = self.http.get(URL, params=params).text
        if text.startswith("ERROR"):
            if "NOTHING FOUND" in text:
                return pd.DataFrame(columns=list(HEADERS.values()))
            raise SystemExit(f"Semrush: {text.strip()}")
        df = pd.read_csv(io.StringIO(text), sep=";")
        # The API returns long names ("Previous Position", "Url"); normalise to the export headers.
        long = {"Keyword": "Keyword", "Position": "Position", "Previous Position": "Previous position",
                "Search Volume": "Search Volume", "Url": "URL", "Traffic (%)": "Traffic (%)"}
        return df.rename(columns={**long, **HEADERS})


def fetch(cfg: dict, periods: dict, api: ReadOnlySemrush | None = None) -> list[str]:
    acct = (cfg.get("accounts") or {}).get("semrush") or {}
    if not acct.get("domain"):
        raise SystemExit("Semrush: set accounts.semrush.domain (and database) in client.yaml")
    api = api or ReadOnlySemrush()
    df = api.domain_organic(acct["domain"], acct.get("database", "uk"), acct.get("limit", 2000))
    path = cfg["_data"] / f"semrush_positions_{periods['current'][1].isoformat()}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return [f"{path.name} ({len(df)} keywords)"]
