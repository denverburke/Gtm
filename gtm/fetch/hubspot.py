"""HubSpot CRM → hubspot_contacts_<date>.csv. Read-only (see gtm/fetch/__init__.py).

Uses a private app access token per client portal. Unlike the ad platforms, HubSpot scopes are
granular, so read-only is enforced by the token itself: create the private app with ONLY read
scopes (crm.objects.contacts.read, crm.objects.deals.read). Before every pull we ask HubSpot which
scopes the token has, and refuse to run if any of them is not a .read scope.

client.yaml:  accounts: {hubspot: {token_env: HUBSPOT_TOKEN_ACME, lookback_days: 365}}
"""
from __future__ import annotations

import csv
import datetime as dt
import os

from . import NotReadOnlyError
from .http import ReadOnlySession

BASE = "https://api.hubapi.com"
READ_ONLY_EXTRA = {"oauth"}  # scopes that grant no write access despite lacking a .read suffix

PROPS = {  # API property → export header the funnel module already understands
    "hs_analytics_source": "Original Source",
    "hs_analytics_source_data_1": "Original Source Drill-Down 1",
    "lifecyclestage": "Lifecycle Stage",
    "createdate": "Create Date",
    "hs_lifecyclestage_lead_date": "Became a Lead Date",
    "hs_lifecyclestage_marketingqualifiedlead_date": "Became a Marketing Qualified Lead Date",
    "hs_lifecyclestage_salesqualifiedlead_date": "Became a Sales Qualified Lead Date",
    "hs_lifecyclestage_opportunity_date": "Became an Opportunity Date",
    "hs_lifecyclestage_customer_date": "Became a Customer Date",
    "recent_deal_amount": "Recent Deal Amount",
}
SEARCH_CAP = 10_000  # HubSpot search can page through at most 10k results per query


def readonly_scopes(scopes: list[str]) -> bool:
    return bool(scopes) and all(s.endswith(".read") or s in READ_ONLY_EXTRA for s in scopes)


class ReadOnlyHubSpot:
    def __init__(self, token_env: str = "HUBSPOT_TOKEN", session=None):
        self._token = os.environ.get(token_env)
        if not self._token:
            raise SystemExit(f"HubSpot: missing environment secret {token_env}")
        self.http = session or ReadOnlySession(headers={"Authorization": f"Bearer {self._token}"},
                                               min_interval=0.22)  # search API: 5 requests/sec
        self._verified = False

    def verify_readonly(self) -> None:
        if self._verified:
            return
        try:
            info = self.http.post(f"{BASE}/oauth/v2/private-apps/get/access-token-info",
                                  json={"tokenKey": self._token}).json()
        except Exception as ex:  # can't prove it → don't run
            raise NotReadOnlyError(f"HubSpot: could not read token scopes ({ex}). Refusing to pull.") from ex
        scopes = info.get("scopes") or []
        if not readonly_scopes(scopes):
            bad = [s for s in scopes if not (s.endswith(".read") or s in READ_ONLY_EXTRA)]
            raise NotReadOnlyError(f"HubSpot portal {info.get('hubId')}: token has non-read scopes {bad or '(none listed)'}. "
                                   "Recreate the private app with read scopes only. Refusing to pull.")
        self._verified = True

    def contacts_created(self, start: dt.datetime, end: dt.datetime) -> list[dict]:
        """All contacts created in [start, end), splitting the window whenever it would exceed the 10k cap."""
        self.verify_readonly()
        body = {"filterGroups": [{"filters": [{"propertyName": "createdate", "operator": "BETWEEN",
                                               "value": int(start.timestamp() * 1000),
                                               "highValue": int(end.timestamp() * 1000) - 1}]}],
                "properties": list(PROPS), "sorts": [{"propertyName": "createdate", "direction": "ASCENDING"}],
                "limit": 200}
        first = self.http.post(f"{BASE}/crm/v3/objects/contacts/search", json=body).json()
        if first.get("total", 0) >= SEARCH_CAP and end - start > dt.timedelta(hours=1):
            mid = start + (end - start) / 2
            return self.contacts_created(start, mid) + self.contacts_created(mid, end)
        rows, page = [], first
        while True:
            rows += [r["properties"] for r in page.get("results", [])]
            after = (page.get("paging") or {}).get("next", {}).get("after")
            if not after:
                return rows
            page = self.http.post(f"{BASE}/crm/v3/objects/contacts/search", json={**body, "after": after}).json()


def _date(v):
    return v[:10] if v else ""  # ISO timestamp → YYYY-MM-DD


def fetch(cfg: dict, periods: dict, api: ReadOnlyHubSpot | None = None) -> list[str]:
    acct = (cfg.get("accounts") or {}).get("hubspot")
    if acct is None:
        raise SystemExit("HubSpot: add accounts.hubspot (with token_env) to client.yaml")
    api = api or ReadOnlyHubSpot(acct.get("token_env", "HUBSPOT_TOKEN"))
    end = dt.datetime.combine(periods["current"][1] + dt.timedelta(days=1), dt.time(), dt.timezone.utc)
    start = end - dt.timedelta(days=int(acct.get("lookback_days", 365)))
    rows = []
    while start < end:  # 30-day chunks keep each search well under the cap
        nxt = min(start + dt.timedelta(days=30), end)
        rows += api.contacts_created(start, nxt)
        start = nxt
    path = cfg["_data"] / f"hubspot_contacts_{periods['current'][1].isoformat()}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(PROPS.values())
        for r in rows:
            w.writerow([_date(r.get(k)) if k.endswith("date") else (r.get(k) or "") for k in PROPS])
    return [f"{path.name} ({len(rows)} contacts)"]
