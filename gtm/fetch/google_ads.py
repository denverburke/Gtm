"""Google Ads API → search terms + campaign CSVs. Read-only (see gtm/fetch/__init__.py).

Env (store as environment secrets, never in the repo):
  GOOGLE_ADS_DEVELOPER_TOKEN   from your manager (MCC) account's API Center
  GOOGLE_ADS_CLIENT_ID / GOOGLE_ADS_CLIENT_SECRET   OAuth client (Desktop app) in Google Cloud
  GOOGLE_ADS_REFRESH_TOKEN     generated while signed in as the READ-ONLY user
  GOOGLE_ADS_LOGIN_CUSTOMER_ID manager account id, digits only
client.yaml:  accounts: {google_ads: {customer_id: "123-456-7890"}}
"""
from __future__ import annotations

import csv
import os
import re
from pathlib import Path

from . import NotReadOnlyError

ENV = ["GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET",
       "GOOGLE_ADS_REFRESH_TOKEN", "GOOGLE_ADS_LOGIN_CUSTOMER_ID"]

SEARCH_TERMS_GAQL = """
SELECT search_term_view.search_term, segments.search_term_match_type, campaign.name, ad_group.name,
       segments.keyword.info.text, metrics.impressions, metrics.clicks, metrics.cost_micros,
       metrics.conversions, metrics.conversions_value
FROM search_term_view
WHERE segments.date BETWEEN '{start}' AND '{end}' AND metrics.impressions > 0
"""
CAMPAIGNS_GAQL = """
SELECT campaign.name, metrics.impressions, metrics.clicks, metrics.cost_micros,
       metrics.conversions, metrics.conversions_value
FROM campaign
WHERE segments.date BETWEEN '{start}' AND '{end}' AND metrics.impressions > 0
"""


def _digits(x) -> str:
    return re.sub(r"\D", "", str(x))


def assert_select_only(gaql: str) -> str:
    """GAQL is read-only by design, but refuse anything that isn't a plain SELECT anyway."""
    q = gaql.strip()
    if not re.match(r"(?is)^select\s", q) or ";" in q:
        raise NotReadOnlyError(f"Refusing non-SELECT GAQL: {q[:60]!r}")
    return q


class ReadOnlyGoogleAds:
    """The only surface the rest of the code gets: run a SELECT, get dict rows back."""

    def __init__(self):
        missing = [k for k in ENV if not os.environ.get(k)]
        if missing:
            raise SystemExit(f"Google Ads: missing environment secrets {', '.join(missing)}")
        from google.ads.googleads.client import GoogleAdsClient
        self._client = GoogleAdsClient.load_from_dict({
            "developer_token": os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
            "client_id": os.environ["GOOGLE_ADS_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_ADS_CLIENT_SECRET"],
            "refresh_token": os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
            "login_customer_id": _digits(os.environ["GOOGLE_ADS_LOGIN_CUSTOMER_ID"]),
            "use_proto_plus": True,
        })
        self._verified: set[str] = set()

    def verify_readonly(self, customer_id: str) -> None:
        """Prove the credentials cannot change this account, or raise.

        Sends a create-budget request with validate_only=True. The API checks permissions and
        validates the request but never executes it, so nothing changes even if the user turns
        out to have write access. A read-only user gets an AuthorizationError. Any other outcome
        means we can't prove read-only, so we fail closed.
        """
        cid = _digits(customer_id)
        if cid in self._verified:
            return
        from google.ads.googleads.errors import GoogleAdsException
        c = self._client
        op = c.get_type("CampaignBudgetOperation")
        op.create.name = "gtm read-only probe (validate_only, never created)"
        op.create.amount_micros = 1_000_000
        op.create.delivery_method = c.enums.BudgetDeliveryMethodEnum.STANDARD
        req = c.get_type("MutateCampaignBudgetsRequest")
        req.customer_id, req.validate_only = cid, True
        req.operations.append(op)
        try:
            c.get_service("CampaignBudgetService").mutate_campaign_budgets(request=req)
        except GoogleAdsException as ex:
            if any(e.error_code._pb.WhichOneof("error_code") == "authorization_error" for e in ex.failure.errors):
                self._verified.add(cid)
                return
            raise NotReadOnlyError(f"Google Ads {customer_id}: could not prove read-only access "
                                   f"({ex.failure.errors[0].message}). Refusing to pull.") from ex
        raise NotReadOnlyError(
            f"Google Ads {customer_id}: these credentials CAN make changes. Regenerate "
            "GOOGLE_ADS_REFRESH_TOKEN while signed in as a user with 'Read only' access.")

    def search(self, customer_id: str, gaql: str):
        self.verify_readonly(customer_id)
        svc = self._client.get_service("GoogleAdsService")
        for batch in svc.search_stream(customer_id=_digits(customer_id), query=assert_select_only(gaql)):
            yield from batch.results


def _write(path: Path, header: list[str], rows: list[list]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return len(rows)


def fetch(cfg: dict, periods: dict, api: ReadOnlyGoogleAds | None = None) -> list[str]:
    acct = (cfg.get("accounts") or {}).get("google_ads") or {}
    if not acct.get("customer_id"):
        raise SystemExit("Google Ads: set accounts.google_ads.customer_id in client.yaml")
    api = api or ReadOnlyGoogleAds()
    cid, out, stamp = acct["customer_id"], [], periods["current"][1].isoformat()
    s, e = periods["current"]

    rows = [[r.search_term_view.search_term, r.segments.search_term_match_type.name, r.campaign.name,
             r.ad_group.name, r.segments.keyword.info.text, r.metrics.impressions, r.metrics.clicks,
             round(r.metrics.cost_micros / 1e6, 2), r.metrics.conversions, r.metrics.conversions_value]
            for r in api.search(cid, SEARCH_TERMS_GAQL.format(start=s, end=e))]
    p = cfg["_data"] / f"google_ads_search_terms_{stamp}.csv"
    n = _write(p, ["Search term", "Match type", "Campaign", "Ad group", "Keyword", "Impressions", "Clicks",
                   "Cost", "Conversions", "Conv. value"], rows)
    out.append(f"{p.name} ({n} rows)")

    for label, (s, e) in periods.items():
        agg: dict[str, list[float]] = {}
        for r in api.search(cid, CAMPAIGNS_GAQL.format(start=s, end=e)):
            a = agg.setdefault(r.campaign.name, [0, 0, 0, 0, 0])
            for i, v in enumerate((r.metrics.impressions, r.metrics.clicks, r.metrics.cost_micros / 1e6,
                                   r.metrics.conversions, r.metrics.conversions_value)):
                a[i] += v
        p = cfg["_data"] / f"google_ads_campaigns_{label}_{stamp}.csv"
        n = _write(p, ["Campaign", "Impressions", "Clicks", "Cost", "Conversions", "Conv. value"],
                   [[k, *(round(x, 2) for x in v)] for k, v in agg.items()])
        out.append(f"{p.name} ({n} rows)")
    return out
