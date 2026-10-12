"""Google Search Console → gsc_{queries,pages}_{current,previous}_<date>.csv. Read-only.

Read-only is enforced by the OAuth scope: credentials are only ever minted with
webmasters.readonly, which Google will not honour for any write (sitemaps, adding sites).
Add the service account's email to each GSC property as a user with Restricted permission.

Env:          GSC_SERVICE_ACCOUNT_JSON  (the key file's JSON contents, as an environment secret)
client.yaml:  accounts: {gsc: {site_url: "sc-domain:example.com"}}
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
from urllib.parse import quote

from . import NotReadOnlyError
from .http import ReadOnlySession

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
BASE = "https://searchconsole.googleapis.com/webmasters/v3/sites"
PAGE = 25_000
MAX_ROWS = 100_000
LAG_DAYS = 2  # GSC data is incomplete for the most recent ~2 days


class ReadOnlySearchConsole:
    def __init__(self, session=None):
        if session is None:
            raw = os.environ.get("GSC_SERVICE_ACCOUNT_JSON")
            if not raw:
                raise SystemExit("Search Console: missing environment secret GSC_SERVICE_ACCOUNT_JSON")
            from google.auth.transport.requests import AuthorizedSession
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
            if list(creds.scopes or []) != SCOPES:
                raise NotReadOnlyError(f"Search Console: unexpected scopes {creds.scopes}. Refusing to pull.")
            session = AuthorizedSession(creds)
        self.http = ReadOnlySession(session)

    def check_access(self, site_url: str) -> str:
        sites = self.http.get(BASE).json().get("siteEntry", [])
        level = next((s["permissionLevel"] for s in sites if s["siteUrl"] == site_url), None)
        if level is None:
            raise SystemExit(f"Search Console: no access to {site_url}. Add the service account's email to "
                             "the property (Settings → Users and permissions → Restricted).")
        return level

    def query(self, site_url: str, dimension: str, start: dt.date, end: dt.date) -> list[dict]:
        url = f"{BASE}/{quote(site_url, safe='')}/searchAnalytics/query"
        rows, start_row = [], 0
        while start_row < MAX_ROWS:
            body = {"startDate": start.isoformat(), "endDate": end.isoformat(), "dimensions": [dimension],
                    "type": "web", "rowLimit": PAGE, "startRow": start_row}
            batch = self.http.post(url, json=body).json().get("rows", [])
            rows += batch
            if len(batch) < PAGE:
                break
            start_row += PAGE
        return rows


def fetch(cfg: dict, periods: dict, api: ReadOnlySearchConsole | None = None) -> list[str]:
    from . import periods as make_periods
    acct = (cfg.get("accounts") or {}).get("gsc") or {}
    if not acct.get("site_url"):
        raise SystemExit("Search Console: set accounts.gsc.site_url in client.yaml")
    api = api or ReadOnlySearchConsole()
    api.check_access(acct["site_url"])
    days = (periods["current"][1] - periods["current"][0]).days + 1
    gsc_periods = make_periods(days, end=dt.date.today() - dt.timedelta(days=LAG_DAYS + 1))
    stamp, out = periods["current"][1].isoformat(), []
    for dim, kind, head in (("query", "queries", "Top queries"), ("page", "pages", "Top pages")):
        for label, (s, e) in gsc_periods.items():
            rows = api.query(acct["site_url"], dim, s, e)
            path = cfg["_data"] / f"gsc_{kind}_{label}_{stamp}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow([head, "Clicks", "Impressions", "Position"])
                w.writerows([r["keys"][0], r["clicks"], r["impressions"], round(r["position"], 2)] for r in rows)
            out.append(f"{path.name} ({len(rows)} rows, {s}..{e})")
    return out
