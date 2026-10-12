"""Generate a synthetic 'demo' client with planted issues so every analysis has something to find.

python scripts/make_demo_data.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(7)
OUT = Path(__file__).resolve().parent.parent / "clients" / "demo" / "data"
OUT.mkdir(parents=True, exist_ok=True)

KW = {  # keyword: (volume, prev_pos, cur_pos, url)
    "northwind hr": (1900, 1, 1, "/"),
    "northwind payroll login": (720, 1, 1, "/login"),
    "payroll software": (8100, 6, 12, "/payroll"),            # dropped off page 1
    "payroll software uk": (2400, 4, 9, "/payroll"),
    "small business payroll": (1300, 11, 6, "/payroll/smb"),   # entered page 1
    "hr software": (6600, 9, 8, "/hr-software"),
    "hris": (3600, 14, 15, "/hr-software"),
    "hr software for small business": (1000, 7, 3, "/hr-software/smb"),
    "employee onboarding software": (880, 22, 13, "/onboarding"),
    "absence management software": (590, 5, 5, "/absence"),
    "people management software": (480, 3, 3, "/hr-software"),
    "what is an hris": (2900, 2, 2, "/blog/what-is-hris"),       # CTR erosion candidate
    "how to run payroll": (1600, 3, 4, "/blog/run-payroll"),     # CTR erosion candidate
    "brightpay alternatives": (390, 0, 7, "/compare/brightpay"),
    "sage payroll alternative": (320, 8, 18, "/compare/sage"),
    "payroll outsourcing": (1300, 13, 16, "/payroll"),
    "holiday tracker": (2400, 17, 19, "/absence"),
}

# --- Semrush positions
pd.DataFrame([{"Keyword": k, "Position": c, "Previous position": p, "Search Volume": v,
               "URL": f"https://northwind.example{u}", "Traffic": round(v * max(0.3 - c * 0.02, 0.005))}
              for k, (v, p, c, u) in KW.items()]).to_csv(OUT / "semrush_positions_2026-10-12.csv", index=False)


def ctr_for(pos):
    return max(0.32 * np.exp(-0.35 * (pos - 1)), 0.004)


# --- GSC queries (current vs previous 28 days)
for period, idx in (("previous", 1), ("current", 2)):
    rows = []
    for k, (v, p, c, u) in KW.items():
        pos = (p if idx == 1 else c) or 40
        impr = int(v * 0.9 * rng.uniform(0.9, 1.1))
        ctr = ctr_for(pos)
        if period == "current" and k in ("what is an hris", "how to run payroll"):
            ctr *= 0.45  # AI Overview landed
        rows.append({"Top queries": k, "Clicks": int(impr * ctr), "Impressions": impr,
                     "CTR": f"{ctr * 100:.2f}%", "Position": round(max(pos + rng.uniform(-0.3, 0.3), 1.0), 1)})
    pd.DataFrame(rows).to_csv(OUT / f"gsc_queries_{period}_2026-10-12.csv", index=False)

# --- Google Ads search terms (with title rows, like the real export)
terms = [  # term, campaign, keyword, match, clicks, cost, conv
    ("northwind hr", "Brand", "northwind hr", "Exact match", 420, 210, 38),
    ("northwind payroll login", "Brand", "northwind", "Phrase match", 180, 95, 0),
    ("payroll software", "Payroll - Generic", "payroll software", "Exact match", 160, 1450, 11),
    ("payroll software uk", "Payroll - Generic", "payroll software", "Phrase match", 95, 820, 9),
    ("free payroll software", "Payroll - Generic", "payroll software", "Broad match", 120, 640, 0),
    ("payroll software free download", "Payroll - Generic", "payroll software", "Broad match", 40, 210, 0),
    ("payroll jobs", "Payroll - Generic", "payroll", "Broad match", 60, 310, 0),
    ("payroll jobs remote", "Payroll - Generic", "payroll", "Broad match", 25, 140, 0),
    ("small business payroll", "Payroll - Generic", "payroll software", "Broad match", 70, 520, 6),
    ("payroll for small business uk", "Payroll - Generic", "payroll software", "Broad match", 32, 260, 4),
    ("hr software", "HR Software", "hr software", "Exact match", 140, 1380, 9),
    ("hris for small business", "HR Software", "hris", "Phrase match", 45, 420, 3),
    ("hr software payroll integration", "HR Software", "hr software", "Phrase match", 30, 300, 3),
    ("payroll and hr software", "HR Software", "hr software", "Broad match", 35, 350, 2),
    ("what is hr software", "HR Software", "hr software", "Broad match", 90, 380, 0),
    ("brightpay alternatives", "Competitor", "brightpay", "Phrase match", 40, 520, 2),
    ("brightpay login", "Competitor", "brightpay", "Phrase match", 55, 330, 0),
    ("employee onboarding software", "HR Software", "onboarding software", "Phrase match", 28, 300, 3),
    ("how to run payroll", "Payroll - Generic", "payroll", "Broad match", 50, 210, 1),
    ("what is an hris", "HR Software", "hris", "Broad match", 40, 160, 1),
    ("northwind hr pricing", "HR Software", "hr software", "Broad match", 25, 110, 4),
]
st = pd.DataFrame([{"Search term": t, "Match type": m, "Campaign": c, "Ad group": c + " - AG1", "Keyword": k,
                    "Impr.": cl * int(rng.integers(8, 20)), "Clicks": cl, "Cost": f"£{cost:,.2f}",
                    "Conversions": conv, "Conv. value": conv * 0} for t, c, k, m, cl, cost, conv in terms])
with open(OUT / "google_ads_search_terms_2026-10-12.csv", "w") as fh:
    fh.write("Search terms report\n1 September 2026 - 30 September 2026\n")
    st.to_csv(fh, index=False)
    fh.write("Total: account,,,,,,,,,\n")

bing = pd.DataFrame([{"Search term": t, "Campaign name": c, "Ad group name": c, "Keyword": k,
                      "Impressions": cl * 10, "Clicks": max(cl // 5, 1), "Spend": round(cost / 6, 2),
                      "Conversions": conv // 5}
                     for t, c, k, m, cl, cost, conv in terms if "brightpay" not in t and "hris" not in t][:12])
bing.to_csv(OUT / "bing_ads_search_terms_2026-10-12.csv", index=False)

# --- Campaign-level exports for each channel (current and previous)
camps = {
    "google_ads": [("Brand", 650, 46), ("Payroll - Generic", 4800, 33), ("HR Software", 3400, 25), ("Competitor", 1300, 4)],
    "bing_ads": [("Brand", 110, 9), ("Payroll - Generic", 700, 7), ("HR Software", 520, 5)],
    "meta_ads": [("Prospecting - Payroll Guide", 2200, 61), ("Retargeting - Demo", 900, 22), ("Prospecting - Video", 800, 3)],
    "linkedin_ads": [("ABM - Mid-market HR Directors", 4200, 14), ("Lead Gen - Payroll Checklist", 2600, 31)],
}
heads = {"google_ads": ("Campaign", "Cost", "Conversions"), "bing_ads": ("Campaign name", "Spend", "Conversions"),
         "meta_ads": ("Campaign name", "Amount spent (GBP)", "Results"),
         "linkedin_ads": ("Campaign Name", "Total Spent", "Leads")}
for ch, rows in camps.items():
    cn, sp, cv = heads[ch]
    for period, mult in (("current", 1.0), ("previous", 0.85)):
        pd.DataFrame([{cn: n, "Impressions": int(s * 40 * mult), "Clicks": int(s / 4 * mult),
                       sp: round(s * mult, 2), cv: int(c * (1.1 if period == "previous" else 1))}
                      for n, s, c in rows]).to_csv(OUT / f"{ch}_campaigns_{period}_2026-10-12.csv", index=False)

# --- HubSpot contacts
src_mix = [  # source, drilldown, n, p_mql, p_sql|mql, p_opp|sql, p_won|opp, avg_deal
    ("PAID_SEARCH", "google", 140, 0.55, 0.45, 0.6, 0.35, 9000),
    ("PAID_SEARCH", "bing", 22, 0.55, 0.5, 0.6, 0.35, 9000),
    ("PAID_SOCIAL", "facebook", 95, 0.35, 0.12, 0.5, 0.25, 5000),   # high volume, poor quality
    ("PAID_SOCIAL", "linkedin", 48, 0.7, 0.55, 0.65, 0.4, 18000),
    ("ORGANIC_SEARCH", "google", 160, 0.5, 0.42, 0.55, 0.33, 10000),
    ("AI_REFERRALS", "chatgpt.com", 18, 0.7, 0.6, 0.6, 0.4, 12000),
    ("DIRECT_TRAFFIC", "", 110, 0.4, 0.4, 0.5, 0.3, 9000),
    ("REFERRALS", "capterra.com", 40, 0.6, 0.5, 0.55, 0.35, 8000),
    ("EMAIL_MARKETING", "nurture", 35, 0.6, 0.35, 0.5, 0.3, 7000),
]
rows, i = [], 0
start = pd.Timestamp("2026-07-01")
for src, drill, n, pm, ps, po, pw, deal in src_mix:
    for _ in range(n):
        i += 1
        created = start + pd.Timedelta(days=int(rng.integers(0, 90)))
        r = {"Record ID": i, "Original Source": src, "Original Source Drill-Down 1": drill,
             "Create Date": created.strftime("%d/%m/%Y")}
        stage, t = "lead", created
        for p, col, st_name, gap in ((pm, "Became a Marketing Qualified Lead Date", "marketingqualifiedlead", 6),
                                     (ps, "Became a Sales Qualified Lead Date", "salesqualifiedlead", 9),
                                     (po, "Became an Opportunity Date", "opportunity", 7),
                                     (pw, "Became a Customer Date", "customer", 30)):
            if rng.random() < p:
                t = t + pd.Timedelta(days=int(rng.integers(1, gap * 2)))
                r[col] = t.strftime("%d/%m/%Y")
                stage = st_name
            else:
                break
        r["Lifecycle Stage"] = stage
        r["Recent Deal Amount"] = int(deal * rng.uniform(0.6, 1.5)) if stage == "customer" else ""
        rows.append(r)
pd.DataFrame(rows).to_csv(OUT / "hubspot_contacts_2026-10-12.csv", index=False)
print(f"Demo data written to {OUT}")
