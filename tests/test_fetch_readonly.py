"""Guards for the read-only API layer. These fail the build if a write path sneaks into gtm/fetch/."""
import ast
import datetime as dt
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gtm.common import load_csv  # noqa: E402
from gtm.fetch import NotReadOnlyError, periods  # noqa: E402

FETCH = sorted((ROOT / "gtm" / "fetch").glob("*.py"))


def _enclosing_functions(tree):
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    def fn_of(n):
        while n in parents:
            n = parents[n]
            if isinstance(n, ast.FunctionDef):
                return n.name
        return None
    return fn_of


@pytest.mark.parametrize("path", FETCH, ids=lambda p: p.name)
def test_no_write_calls_outside_the_validate_only_probe(path):
    src = path.read_text()
    for banned in ("CampaignManagementService", "BulkServiceManager", "BulkService", "AdGroupService",
                   "AdGroupCriterionService", "CampaignService\"", "SharedSetService"):
        assert banned not in src, f"{path.name} references write-capable {banned}"
    tree = ast.parse(src)
    fn_of = _enclosing_functions(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and "mutate" in node.attr.lower():
            assert fn_of(node) == "verify_readonly", f"{path.name}: {node.attr} outside verify_readonly"
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "get_service":
            name = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else None
            assert name in {"GoogleAdsService", "CampaignBudgetService"}, f"{path.name}: get_service({name!r})"
            if name == "CampaignBudgetService":
                assert fn_of(node) == "verify_readonly"


def test_probe_is_validate_only():
    src = (ROOT / "gtm" / "fetch" / "google_ads.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "verify_readonly")
    body = ast.unparse(fn)
    assert "req.validate_only = (cid, True)" in body or "validate_only = cid, True" in body \
        or "req.customer_id, req.validate_only = (cid, True)" in body


def test_select_only_guard():
    from gtm.fetch.google_ads import assert_select_only
    assert assert_select_only("  select campaign.name FROM campaign")
    for bad in ("DELETE FROM campaign", "select 1; mutate", "campaign.name"):
        with pytest.raises(NotReadOnlyError):
            assert_select_only(bad)


def test_periods_are_contiguous_and_equal_length():
    p = periods(28, end=dt.date(2026, 10, 11))
    assert p["current"] == (dt.date(2026, 9, 14), dt.date(2026, 10, 11))
    assert p["previous"][1] == dt.date(2026, 9, 13)
    assert (p["previous"][1] - p["previous"][0]).days == 27


# --- Google Ads probe behaviour (no network: the service is faked, the protos are real)

def _google_api(service_behaviour):
    ga = pytest.importorskip("google.ads.googleads.client")
    from gtm.fetch.google_ads import ReadOnlyGoogleAds
    from google.auth.credentials import AnonymousCredentials
    real = ga.GoogleAdsClient(credentials=AnonymousCredentials(), developer_token="x", use_proto_plus=True)

    class Svc:
        def mutate_campaign_budgets(self, request):
            assert request.validate_only is True  # the probe must never be able to execute
            return service_behaviour()

    api = ReadOnlyGoogleAds.__new__(ReadOnlyGoogleAds)
    api._client = NS(get_type=real.get_type, enums=real.enums, get_service=lambda name: Svc())
    api._verified = set()
    return api


def _gads_exception(kind):
    from google.ads.googleads.errors import GoogleAdsException
    from google.ads.googleads.v25.errors.types.authorization_error import AuthorizationErrorEnum
    from google.ads.googleads.v25.errors.types.field_error import FieldErrorEnum
    from google.ads.googleads.v25.errors.types.errors import ErrorCode, GoogleAdsError, GoogleAdsFailure
    code = ErrorCode(authorization_error=AuthorizationErrorEnum.AuthorizationError.ACTION_NOT_PERMITTED) \
        if kind == "auth" else ErrorCode(field_error=FieldErrorEnum.FieldError.REQUIRED)
    failure = GoogleAdsFailure(errors=[GoogleAdsError(error_code=code, message=kind)])
    return GoogleAdsException(None, None, failure, "req")


def test_google_readonly_user_passes():
    def deny():
        raise _gads_exception("auth")
    api = _google_api(deny)
    api.verify_readonly("123-456-7890")
    assert "1234567890" in api._verified


def test_google_write_capable_user_is_blocked():
    api = _google_api(lambda: NS())  # validation succeeded → user could write
    with pytest.raises(NotReadOnlyError, match="CAN make changes"):
        api.verify_readonly("1234567890")


def test_google_inconclusive_probe_fails_closed():
    def other():
        raise _gads_exception("field")
    with pytest.raises(NotReadOnlyError, match="could not prove"):
        _google_api(other).verify_readonly("1234567890")


def test_google_fetch_writes_files_the_analysis_understands(tmp_path):
    from gtm.fetch import google_ads
    m = NS(impressions=100, clicks=10, cost_micros=55_500_000, conversions=2.0, conversions_value=0.0)
    row = NS(search_term_view=NS(search_term="payroll software"),
             segments=NS(search_term_match_type=NS(name="PHRASE"), keyword=NS(info=NS(text="payroll"))),
             campaign=NS(name="Payroll"), ad_group=NS(name="AG"), metrics=m)
    api = NS(search=lambda cid, q: iter([row, row]))
    cfg = {"_data": tmp_path, "accounts": {"google_ads": {"customer_id": "1"}}}
    google_ads.fetch(cfg, periods(7, end=dt.date(2026, 10, 11)), api=api)
    st = load_csv(next(tmp_path.glob("google_ads_search_terms_*.csv")), ["cost"])
    assert {"query", "keyword", "match_type", "campaign", "cost", "conversions"} <= set(st.columns)
    camp = load_csv(next(tmp_path.glob("google_ads_campaigns_current_*.csv")), ["cost"])
    assert camp.loc[0, "cost"] == pytest.approx(111.0)  # two rows aggregated, micros → currency


# --- Microsoft Ads

def test_bing_columns_map_to_known_headers(tmp_path):
    import pandas as pd
    from gtm.fetch.microsoft_ads import to_friendly
    df = to_friendly(pd.DataFrame(columns=["SearchQuery", "CampaignName", "AdGroupName", "Keyword",
                                           "DeliveredMatchType", "Impressions", "Clicks", "Spend",
                                           "Conversions", "Revenue"]))
    df.to_csv(tmp_path / "x.csv", index=False)
    cols = set(load_csv(tmp_path / "x.csv").columns)
    assert {"query", "campaign", "ad_group", "keyword", "match_type", "cost", "conv_value"} <= cols


@pytest.mark.parametrize("role_ids,ok", [([100], True), ([41], False), ([100, 16], False), ([], False)])
def test_bing_role_check(monkeypatch, role_ids, ok):
    sc = pytest.importorskip("bingads.service_client")
    from gtm.fetch.microsoft_ads import ReadOnlyMicrosoftAds
    roles = [NS(RoleId=r, CustomerId=777) for r in role_ids] + [NS(RoleId=41, CustomerId=999)]  # other customer
    fake = lambda *a, **k: NS(GetUser=lambda UserId: NS(CustomerRoles=NS(CustomerRole=roles)))  # noqa: E731
    monkeypatch.setattr(sc, "ServiceClient", fake)
    api = ReadOnlyMicrosoftAds.__new__(ReadOnlyMicrosoftAds)
    api._auth, api._verified = NS(customer_id=777), False
    if ok:
        api.verify_readonly()
    else:
        with pytest.raises(NotReadOnlyError):
            api.verify_readonly()
