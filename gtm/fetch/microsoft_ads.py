"""Microsoft Advertising (Bing Ads) API → search terms + campaign CSVs. Read-only (see gtm/fetch/__init__.py).

Env (environment secrets):
  MSADS_DEVELOPER_TOKEN   from developers.ads.microsoft.com (Account → Developer settings)
  MSADS_CLIENT_ID         Azure app registration (public client / "mobile and desktop")
  MSADS_REFRESH_TOKEN     generated while signed in as the VIEWER-role user
client.yaml:  accounts: {bing_ads: {customer_id: 1234567, account_id: 123456789}}

Only two services are ever touched: CustomerManagement.GetUser (to read our own role) and
Reporting (report downloads). The Campaign Management and Bulk services are never constructed.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd

from . import NotReadOnlyError

ENV = ["MSADS_DEVELOPER_TOKEN", "MSADS_CLIENT_ID", "MSADS_REFRESH_TOKEN"]
VIEWER_ROLE_ID = 100  # Microsoft Advertising "Viewer": can see everything, change nothing
TIMEZONE = "GreenwichMeanTimeDublinEdinburghLisbonLondon"

SEARCH_COLS = ["SearchQuery", "CampaignName", "AdGroupName", "Keyword", "DeliveredMatchType",
               "Impressions", "Clicks", "Spend", "Conversions", "Revenue"]
CAMPAIGN_COLS = ["CampaignName", "Impressions", "Clicks", "Spend", "Conversions", "Revenue"]
FRIENDLY = {"searchquery": "Search term", "campaignname": "Campaign name", "adgroupname": "Ad group name",
            "keyword": "Keyword", "deliveredmatchtype": "Match type", "impressions": "Impressions",
            "clicks": "Clicks", "spend": "Spend", "conversions": "Conversions", "revenue": "Conv. value"}


class ReadOnlyMicrosoftAds:
    def __init__(self, customer_id, account_id):
        missing = [k for k in ENV if not os.environ.get(k)]
        if missing:
            raise SystemExit(f"Microsoft Ads: missing environment secrets {', '.join(missing)}")
        from bingads.authorization import AuthorizationData, OAuthDesktopMobileAuthCodeGrant
        auth = OAuthDesktopMobileAuthCodeGrant(client_id=os.environ["MSADS_CLIENT_ID"], env="production")
        auth.request_oauth_tokens_by_refresh_token(os.environ["MSADS_REFRESH_TOKEN"])
        self._auth = AuthorizationData(account_id=int(account_id), customer_id=int(customer_id),
                                       developer_token=os.environ["MSADS_DEVELOPER_TOKEN"], authentication=auth)
        self._verified = False

    def verify_readonly(self) -> None:
        """Read our own user's roles; refuse unless every role on this customer is Viewer."""
        if self._verified:
            return
        from bingads.service_client import ServiceClient
        cm = ServiceClient("CustomerManagementService", version=13, authorization_data=self._auth,
                           environment="production")
        resp = cm.GetUser(UserId=None)
        roles = [r for r in (resp.CustomerRoles.CustomerRole if resp.CustomerRoles else [])
                 if int(r.CustomerId) == self._auth.customer_id]
        ids = sorted({int(r.RoleId) for r in roles})
        if not ids or ids != [VIEWER_ROLE_ID]:
            raise NotReadOnlyError(
                f"Microsoft Ads customer {self._auth.customer_id}: user role ids {ids or 'none'} are not "
                f"Viewer-only ({VIEWER_ROLE_ID}). Regenerate MSADS_REFRESH_TOKEN as a Viewer user. Refusing to pull.")
        self._verified = True

    def download(self, kind: str, columns: list[str], start, end) -> pd.DataFrame:
        self.verify_readonly()
        from bingads.service_client import ServiceClient
        from bingads.v13.reporting import ReportingDownloadParameters, ReportingServiceManager
        f = ServiceClient("ReportingService", version=13, authorization_data=self._auth,
                          environment="production").factory
        req = f.create(f"{kind}ReportRequest")
        req.Aggregation, req.Format, req.FormatVersion = "Summary", "Csv", "2.0"
        req.ExcludeReportHeader = req.ExcludeReportFooter = True
        req.ExcludeColumnHeaders, req.ReturnOnlyCompleteData = False, False
        req.ReportName = f"gtm {kind}"
        scope = f.create("AccountThroughAdGroupReportScope" if kind == "SearchQueryPerformance"
                         else "AccountThroughCampaignReportScope")
        scope.AccountIds = {"long": [self._auth.account_id]}
        scope.Campaigns = None
        if hasattr(scope, "AdGroups"):
            scope.AdGroups = None
        req.Scope = scope
        t = f.create("ReportTime")
        for attr, d in (("CustomDateRangeStart", start), ("CustomDateRangeEnd", end)):
            x = f.create("Date")
            x.Year, x.Month, x.Day = d.year, d.month, d.day
            setattr(t, attr, x)
        t.PredefinedTime, t.ReportTimeZone = None, TIMEZONE
        req.Time = t
        cols = f.create(f"ArrayOf{kind}ReportColumn")
        getattr(cols, f"{kind}ReportColumn").append(columns)
        req.Columns = cols

        mgr = ReportingServiceManager(authorization_data=self._auth, poll_interval_in_milliseconds=5000,
                                      environment="production")
        with tempfile.TemporaryDirectory() as tmp:
            path = mgr.download_file(ReportingDownloadParameters(
                report_request=req, result_file_directory=tmp, result_file_name="r.csv",
                overwrite_result_file=True, timeout_in_milliseconds=3_600_000))
            if not path:  # no data in range
                return pd.DataFrame(columns=columns)
            df = pd.read_csv(path, encoding="utf-8-sig")
        return df


def to_friendly(df: pd.DataFrame) -> pd.DataFrame:
    """Map API column names (SearchQuery, Spend…) to the export headers gtm already understands."""
    return df.rename(columns={c: FRIENDLY.get(str(c).replace(" ", "").lower(), c) for c in df.columns})


def fetch(cfg: dict, periods: dict, api: ReadOnlyMicrosoftAds | None = None) -> list[str]:
    acct = (cfg.get("accounts") or {}).get("bing_ads") or {}
    if not (acct.get("customer_id") and acct.get("account_id")):
        raise SystemExit("Microsoft Ads: set accounts.bing_ads.customer_id and account_id in client.yaml")
    api = api or ReadOnlyMicrosoftAds(acct["customer_id"], acct["account_id"])
    stamp, out = periods["current"][1].isoformat(), []
    data: Path = cfg["_data"]
    data.mkdir(parents=True, exist_ok=True)

    df = to_friendly(api.download("SearchQueryPerformance", SEARCH_COLS, *periods["current"]))
    p = data / f"bing_ads_search_terms_{stamp}.csv"
    df.to_csv(p, index=False)
    out.append(f"{p.name} ({len(df)} rows)")
    for label, (s, e) in periods.items():
        df = to_friendly(api.download("CampaignPerformance", CAMPAIGN_COLS, s, e))
        p = data / f"bing_ads_campaigns_{label}_{stamp}.csv"
        df.to_csv(p, index=False)
        out.append(f"{p.name} ({len(df)} rows)")
    return out
