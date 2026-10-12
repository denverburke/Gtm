"""Regression tests against the synthetic demo client (regenerated fresh each run)."""
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gtm import funnel, paid_media, rank_shifts, search_terms  # noqa: E402
from gtm.common import load_client, normalise_columns, to_num  # noqa: E402


@pytest.fixture(scope="session")
def cfg():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "make_demo_data.py")], check=True, capture_output=True)
    return load_client("demo")


def test_number_cleaning():
    s = to_num(pd.Series(["£1,234.50", "12.5%", "--", "< 10", 3]))
    assert s.tolist()[:2] == [1234.5, 12.5] and pd.isna(s[2]) and s[3] == 10


def test_header_aliases_keep_search_term_and_keyword_distinct():
    df = normalise_columns(pd.DataFrame(columns=["Search term", "Keyword", "Impr.", "Amount spent (GBP)"]))
    assert list(df.columns) == ["query", "keyword", "impressions", "cost"]


def test_rank_shifts_find_planted_signals(cfg):
    sem = rank_shifts.semrush_shifts(cfg)
    assert "payroll software" in sem["losers"]["query"].tolist()
    assert "brightpay alternatives" in sem["new"]["query"].tolist()
    gsc = rank_shifts.gsc_shifts(cfg)
    assert "what is an hris" in gsc["ctr_erosion"]["query"].tolist()
    assert "northwind hr" not in gsc["striking_distance"]["query"].tolist()  # brand excluded


def test_search_terms(cfg):
    r = search_terms.analyse(cfg)
    assert "free payroll software" in r["waste"]["query"].tolist()
    assert {"free", "jobs", "login"} <= set(r["neg_grams"]["ngram"])
    assert "payroll software uk" in r["promote"]["query"].tolist()
    assert r["misrouted"].empty  # brand queries in the brand campaign aren't misrouted
    assert "payroll software" in r["seo_opportunity"]["query"].tolist()


def test_funnel_uses_current_spend_and_flags_quality(cfg):
    df = funnel.period_filter(funnel.load_contacts(cfg), cfg)
    spend = funnel.cost_per_stage(df, funnel.load_spend(cfg)).set_index("channel")
    cur = paid_media.load_channel(cfg, "google_ads", previous=False)
    assert spend.loc["google_ads", "spend"] == pytest.approx(cur["cost"].sum())
    assert spend.loc["meta_ads", "Cost/SQL"] > 2 * spend.loc["linkedin_ads", "Cost/SQL"]
    # stage dates imply ever-reached: every customer is also counted as SQL
    assert (df["customer_date"].notna() <= df["sql_date"].notna()).all()


def test_cli_all(cfg):
    out = subprocess.run([sys.executable, "-m", "gtm", "all", "--client", "demo"], cwd=ROOT,
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    for h in ("Ranking shifts", "Search terms", "HubSpot funnel", "Paid media"):
        assert h in out.stdout
