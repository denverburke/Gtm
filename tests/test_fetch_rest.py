"""HubSpot / Search Console / Semrush fetchers: allow-list, read-only checks, and output the analyses accept."""
import datetime as dt
import json as jsonlib
import sys
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gtm import funnel, rank_shifts  # noqa: E402
from gtm.fetch import NotReadOnlyError, periods  # noqa: E402
from gtm.fetch.http import ReadOnlySession, check  # noqa: E402

FETCH = sorted((ROOT / "gtm" / "fetch").glob("*.py"))


class Resp:
    def __init__(self, data=None, text=None, status=200):
        self._d, self.text, self.status_code = data, text if text is not None else jsonlib.dumps(data), status

    def json(self):
        return self._d


class FakeSession:
    """Stands in for requests.Session underneath ReadOnlySession, so the allow-list is still exercised."""

    def __init__(self, handler):
        self.headers, self.calls, self._h = {}, [], handler

    def request(self, method, url, params=None, json=None, timeout=None):
        self.calls.append((method, url, params, json))
        return self._h(method, url, params, json)


def cfg_for(tmp_path, **accounts):
    return {"name": "t", "_data": tmp_path, "thresholds": {}, "brand_terms": ["acme"], "accounts": accounts,
            "dayfirst_dates": True}


# --- allow-list

@pytest.mark.parametrize("method,url,params,ok", [
    ("POST", "https://api.hubapi.com/crm/v3/objects/contacts/search", None, True),
    ("POST", "https://api.hubapi.com/crm/v3/objects/contacts", None, False),          # create
    ("PATCH", "https://api.hubapi.com/crm/v3/objects/contacts/123", None, False),     # update
    ("DELETE", "https://api.hubapi.com/crm/v3/objects/contacts/123", None, False),
    ("POST", "https://api.hubapi.com/crm/v3/objects/contacts/batch/update", None, False),
    ("POST", "https://searchconsole.googleapis.com/webmasters/v3/sites/sc-domain%3Ax.com/searchAnalytics/query", None, True),
    ("PUT", "https://searchconsole.googleapis.com/webmasters/v3/sites/sc-domain%3Ax.com/sitemaps/s.xml", None, False),
    ("DELETE", "https://searchconsole.googleapis.com/webmasters/v3/sites/sc-domain%3Ax.com", None, False),
    ("GET", "https://api.semrush.com/", {"type": "domain_organic"}, True),
    ("GET", "https://api.semrush.com/", {"type": "backlinks"}, False),
    ("GET", "https://evil.example.com/crm/v3/objects/contacts", None, False),
])
def test_allow_list(method, url, params, ok):
    if ok:
        check(method, url, params)
    else:
        with pytest.raises(NotReadOnlyError):
            check(method, url, params)


@pytest.mark.parametrize("path", [p for p in FETCH if p.name != "http.py"], ids=lambda p: p.name)
def test_rest_calls_only_go_through_the_allow_listed_session(path):
    src = path.read_text()
    assert "import requests" not in src and "requests." not in src


def test_errors_never_leak_query_string_secrets():
    def boom(*a):
        raise requests.ConnectionError("HTTPSConnectionPool: Max retries exceeded with url: /?key=SECRET123")
    s = ReadOnlySession(FakeSession(boom))
    with pytest.raises(RuntimeError) as e:
        s.get("https://api.semrush.com/", params={"type": "domain_organic", "key": "SECRET123"}, retries=0)
    assert "SECRET123" not in str(e.value)
    s = ReadOnlySession(FakeSession(lambda *a: Resp(text="forbidden", status=403)))
    with pytest.raises(RuntimeError) as e:
        s.get("https://api.semrush.com/?key=SECRET123", params={"type": "domain_organic"}, retries=0)
    assert "SECRET123" not in str(e.value)


# --- HubSpot

def _hubspot(monkeypatch, scopes, contacts=(), total=None):
    from gtm.fetch import hubspot
    monkeypatch.setenv("HUBSPOT_TOKEN", "pat-test")

    def handler(method, url, params, body):
        if url.endswith("access-token-info"):
            return Resp({"hubId": 1, "scopes": scopes}) if scopes is not None else Resp({"message": "no"}, status=401)
        return Resp({"total": total if total is not None else len(contacts),
                     "results": [{"properties": c} for c in contacts]})
    fake = FakeSession(handler)
    api = hubspot.ReadOnlyHubSpot(session=ReadOnlySession(fake))
    return hubspot, api, fake


@pytest.mark.parametrize("scopes,ok", [
    (["crm.objects.contacts.read", "crm.objects.deals.read", "oauth"], True),
    (["crm.objects.contacts.read", "crm.objects.contacts.write"], False),
    (["crm.objects.contacts.read", "automation"], False),  # unknown non-.read scope → fail closed
    ([], False),
    (None, False),                                           # couldn't read scopes → fail closed
])
def test_hubspot_scope_check(monkeypatch, scopes, ok):
    _, api, _ = _hubspot(monkeypatch, scopes)
    if ok:
        api.verify_readonly()
    else:
        with pytest.raises(NotReadOnlyError):
            api.verify_readonly()


def test_hubspot_fetch_feeds_the_funnel(monkeypatch, tmp_path):
    contacts = [{"hs_analytics_source": "PAID_SEARCH", "hs_analytics_source_data_1": "google",
                 "lifecyclestage": "customer", "createdate": "2026-07-03T10:00:00.000Z",
                 "hs_lifecyclestage_marketingqualifiedlead_date": "2026-07-05T10:00:00Z",
                 "hs_lifecyclestage_salesqualifiedlead_date": "2026-07-12T10:00:00Z",
                 "hs_lifecyclestage_customer_date": "2026-08-20T10:00:00Z", "recent_deal_amount": "9000"}]
    hubspot, api, fake = _hubspot(monkeypatch, ["crm.objects.contacts.read"], contacts)
    cfg = cfg_for(tmp_path, hubspot={"lookback_days": 30})
    hubspot.fetch(cfg, periods(28, end=dt.date(2026, 7, 31)), api=api)
    df = funnel.load_contacts(cfg)
    r = df.iloc[0]
    # ISO dates must survive dayfirst parsing: 3 July, not 7 March
    assert r["create_date"] == dt.datetime(2026, 7, 3) and r["customer_date"] == dt.datetime(2026, 8, 20)
    assert r["source"] == "PAID_SEARCH" and r["deal_amount"] == 9000
    assert all(m in ("POST",) for m, *_ in fake.calls)


def test_hubspot_splits_windows_over_the_10k_cap(monkeypatch):
    _, api, fake = _hubspot(monkeypatch, ["crm.objects.contacts.read"], total=0)
    seen = []

    def handler(method, url, params, body):
        if url.endswith("access-token-info"):
            return Resp({"scopes": ["crm.objects.contacts.read"]})
        f = body["filterGroups"][0]["filters"][0]
        seen.append((f["value"], f["highValue"]))
        width_days = (f["highValue"] - f["value"]) / 86_400_000
        return Resp({"total": 15_000 if width_days > 10 else 10, "results": []})
    fake._h = handler
    start = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    api.contacts_created(start, start + dt.timedelta(days=30))
    leaves = [(v, h) for v, h in seen if (h - v) / 86_400_000 <= 10]  # windows small enough to page through
    assert len(seen) > len(leaves) > 1
    assert sum(h - v + 1 for v, h in leaves) == 30 * 86_400_000  # leaves cover the whole range, no gaps/overlap


# --- Search Console

def test_gsc_fetch_feeds_rank_shifts(tmp_path):
    from gtm.fetch import search_console

    def handler(method, url, params, body):
        if method == "GET":
            return Resp({"siteEntry": [{"siteUrl": "sc-domain:acme.com", "permissionLevel": "siteRestrictedUser"}]})
        recent = body["startDate"] > "2026-09-01"
        dim = body["dimensions"][0]
        key = "what is payroll" if dim == "query" else "https://acme.com/blog"
        return Resp({"rows": [{"keys": [key], "clicks": 30 if recent else 100, "impressions": 2000,
                               "ctr": 0.0, "position": 2.0}]})
    fake = FakeSession(handler)
    api = search_console.ReadOnlySearchConsole(session=fake)
    cfg = cfg_for(tmp_path, gsc={"site_url": "sc-domain:acme.com"})
    search_console.fetch(cfg, periods(28), api=api)
    assert all("%3A" in url for m, url, *_ in fake.calls if m == "POST")  # site URL is path-encoded
    g = rank_shifts.gsc_shifts(cfg)
    assert g["ctr_erosion"]["query"].tolist() == ["what is payroll"]  # CTR recomputed from clicks/impressions


def test_gsc_requires_property_access(tmp_path):
    from gtm.fetch import search_console
    api = search_console.ReadOnlySearchConsole(session=FakeSession(lambda *a: Resp({"siteEntry": []})))
    with pytest.raises(SystemExit, match="no access"):
        search_console.fetch(cfg_for(tmp_path, gsc={"site_url": "sc-domain:acme.com"}), periods(28), api=api)


def test_gsc_scope_is_readonly():
    from gtm.fetch.search_console import SCOPES
    assert SCOPES == ["https://www.googleapis.com/auth/webmasters.readonly"]


# --- Semrush

def test_semrush_fetch_feeds_rank_shifts(monkeypatch, tmp_path):
    from gtm.fetch import semrush
    monkeypatch.setenv("SEMRUSH_API_KEY", "k")
    text = ("Keyword;Position;Previous Position;Search Volume;Url;Traffic (%)\r\n"
            "payroll software;12;6;8100;https://acme.com/payroll;3.1\r\n"
            "acme login;1;1;500;https://acme.com/login;9.0\r\n")
    fake = FakeSession(lambda m, u, p, b: Resp(text=text))
    api = semrush.ReadOnlySemrush(session=ReadOnlySession(fake))
    cfg = cfg_for(tmp_path, semrush={"domain": "acme.com", "database": "uk", "limit": 50})
    semrush.fetch(cfg, periods(28), api=api)
    assert fake.calls[0][2]["display_limit"] == 50  # unit spend is capped
    s = rank_shifts.semrush_shifts(cfg)
    assert s["losers"]["query"].tolist() == ["payroll software"]


def test_semrush_nothing_found_is_empty_not_error(monkeypatch, tmp_path):
    from gtm.fetch import semrush
    monkeypatch.setenv("SEMRUSH_API_KEY", "k")
    api = semrush.ReadOnlySemrush(session=ReadOnlySession(FakeSession(lambda *a: Resp(text="ERROR 50 :: NOTHING FOUND"))))
    assert api.domain_organic("acme.com", "uk", 10).empty
