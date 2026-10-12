# GTM / Demand Gen agent desk

An agentic analysis workspace for an agency demand-gen team. You drop in the exports you already pull
(Semrush, Search Console, Google Ads, Microsoft Ads, Meta, LinkedIn, HubSpot). A team of Claude
specialist agents then turns them into diagnosed findings, paste-ready fixes and a client-ready weekly brief.

```
 exports ──► gtm/ (Python: deterministic maths) ──► reports/*.md|json
                                                        │
        seo · geo · paid-search · paid-social · funnel  ◄┘  (specialist agents, run in parallel)
                                                        │
                              gtm-strategist ──► weekly brief + top 5 actions
```

The design rule: **code does the arithmetic, agents do the judgement.** LLMs are unreliable at summing a
2,000-row search term report, and good at explaining why a page dropped and what to do about it.

## Quick start

```bash
pip install -r requirements.txt
python scripts/make_demo_data.py          # synthetic client with planted issues
python -m gtm all --client demo           # raw analysis output
claude                                    # then: /weekly-review demo
```

See `examples/demo-weekly-brief.md` for the kind of brief the agents produce.

## Commands (Claude Code skills)

| Command | What you get |
|---|---|
| `/new-client <slug>` | Interviews you, drafts client.yaml (themes, landing pages, GEO prompts from the website) |
| `/weekly-review <slug>` | All five specialists in parallel → strategist brief with top 5 actions |
| `/rank-shifts <slug>` | Diagnosed ranking losses, CTR erosion, striking-distance opportunities |
| `/search-terms <slug>` | Paste-ready negatives (incl. n-grams), keywords to promote, misrouting, brand leakage, Bing gaps, paid/organic overlap |
| `/funnel-review <slug> [start] [end]` | HubSpot funnel by source, leaky stages, velocity, cost per MQL/SQL/customer |
| `/geo-check <slug>` | AI Overview erosion, citation checks on buyer prompts, AI-referral pipeline |

## What to export (into `clients/<slug>/data/`)

Files are matched by prefix; the newest file wins, so date-stamp names (`..._2026-10-12.csv`).
Column names are auto-mapped, so exports in native format are fine.

| File prefix | Source | Notes |
|---|---|---|
| `semrush_positions*.csv` | Semrush → Organic Research → Positions → Export | Needs Keyword, Position, Previous position, Search Volume, URL |
| `gsc_queries_current*.csv` / `gsc_queries_previous*.csv` | Search Console → Performance → Queries (two periods, e.g. last 28d and prior 28d) | Unzip the export, use `Queries.csv` |
| `gsc_pages_current*.csv` / `gsc_pages_previous*.csv` | Same, Pages tab | Optional |
| `google_ads_search_terms*.csv` | Google Ads → Insights & reports → Search terms | Add Campaign, Ad group, Keyword, Match type, Cost, Conversions columns |
| `bing_ads_search_terms*.csv` | Microsoft Ads → Reports → Search query | |
| `google_ads_campaigns_current*.csv` (+ `_previous`) | Campaign report | Same for `bing_ads_`, `meta_ads_`, `linkedin_ads_` |
| `hubspot_contacts*.csv` | HubSpot → Contacts → export | Include Original Source, Original Source Drill-Down 1, Lifecycle Stage, Create Date, Became a MQL/SQL/Opportunity/Customer Date, Recent Deal Amount |

## Direct API pulls, read-only

`python -m gtm fetch --client <slug> [--source google_ads,bing_ads,hubspot,gsc,semrush] [--days 28]` pulls
every source listed under `accounts:` in client.yaml: ad platform search terms and campaigns (last N days and
the N before), Search Console queries and pages (both periods, offset 3 days for GSC's data lag), Semrush
organic positions, and HubSpot contacts created in the last `lookback_days`. It writes them to `data/` under the same names as
the manual exports, so nothing downstream changes. `/weekly-review` runs it automatically when credentials exist.

### How read-only is guaranteed

| Source | Hard guarantee | Pre-flight check (fails closed) |
|---|---|---|
| Google Ads | Credentials belong to a **Read only** user (the API has no read-only scope) | `validate_only` test change must be refused |
| Microsoft Ads | Credentials belong to a **Viewer** user (no read-only scope either) | User's role must be Viewer and nothing else |
| HubSpot | Private app created with **only `.read` scopes** | Token's scopes are fetched; any non-`.read` scope blocks the pull |
| Search Console | OAuth scope is **`webmasters.readonly`**, plus a Restricted user on the property | Scope is pinned in code and asserted |
| Semrush | The Analytics API has no write operations | Report type pinned to `domain_organic`; `limit` caps API units spent |

The same three safety nets cover every source:
- **Allow-list:** HubSpot, GSC and Semrush calls go through one HTTP client that only permits named read
  endpoints. A create, update or delete is refused before it leaves the machine.
- **Tests:** `tests/test_fetch_*.py` fail if a write call, a direct HTTP call or a new endpoint appears.
- **Agent permissions:** `.claude/settings.json` makes Claude ask you before editing `gtm/fetch/`.

Secrets never appear in logs: HTTP errors are reported without query strings.

### One-time setup
**Google Ads**
1. In your MCC, invite a dedicated login (e.g. `reporting@youragency.com`) with **Read only** access. Grant it at
   MCC level to cover every client, or per client account.
2. API Center (MCC → Admin → API Center): get the developer token. Basic access is needed for production accounts.
3. Google Cloud: enable the Google Ads API and create an OAuth client of type **Desktop app**. Set the consent
   screen to **In production** or **Internal**. In "Testing" mode, refresh tokens expire after 7 days.
4. On your laptop: `python scripts/get_ads_refresh_tokens.py google`, and sign in as the reporting login.

**Microsoft Advertising**
1. Invite the reporting login as a **Viewer** user on your manager account (or on each client account).
2. Azure portal → App registrations → new app with a "Mobile and desktop" redirect
   `https://login.microsoftonline.com/common/oauth2/nativeclient`, then copy the client ID.
3. Get the developer token from developers.ads.microsoft.com.
4. On your laptop: `python scripts/get_ads_refresh_tokens.py microsoft`, and sign in as the Viewer user.

**HubSpot** (per client portal)
1. In the client's portal: Settings → Integrations → Private apps → Create. Tick **only** `crm.objects.contacts.read`
   (add `crm.objects.deals.read` if you'll want deals later). Leave every write scope off.
2. Store the token as `HUBSPOT_TOKEN_<CLIENT>` and set `accounts.hubspot.token_env` to that name.

**Search Console**
1. Google Cloud: enable the Search Console API, create a service account and download a JSON key.
2. In each GSC property: Settings → Users and permissions → add the service account email as **Restricted**.
3. Store the JSON file's contents as `GSC_SERVICE_ACCOUNT_JSON`.

**Semrush:** API access needs a Business plan with API units. Store the key as `SEMRUSH_API_KEY`.
domain_organic is billed per row returned, so `limit: 2000` costs roughly 20k units per run. Check
current pricing.

**Store as environment secrets** (Claude Code cloud: environment settings; locally: your shell or a `.env`
that is never committed): `GOOGLE_ADS_DEVELOPER_TOKEN`, `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`,
`GOOGLE_ADS_REFRESH_TOKEN`, `GOOGLE_ADS_LOGIN_CUSTOMER_ID` (MCC id), `MSADS_DEVELOPER_TOKEN`,
`MSADS_CLIENT_ID`, `MSADS_REFRESH_TOKEN`, `HUBSPOT_TOKEN_<CLIENT>`, `GSC_SERVICE_ACCOUNT_JSON`, `SEMRUSH_API_KEY`. Put each client's account IDs under `accounts:` in its client.yaml.

**Network:** cloud environments must allow `googleads.googleapis.com`, `oauth2.googleapis.com`,
`login.microsoftonline.com`, `login.live.com`, `clientcenter.api.bingads.microsoft.com` and
`reporting.api.bingads.microsoft.com`, `api.hubapi.com`, `searchconsole.googleapis.com` and
`api.semrush.com`. Microsoft reports download from a storage URL; if the
first run names a blocked host, allow that too.

**Install:** `pip install -r requirements-fetch.txt` inside a virtualenv. On Debian-based system Pythons,
`bingads` fails to build outside one.

### Other sources
Meta and LinkedIn aren't wired up yet. Use exports, or a Supermetrics/Windsor.ai connector writing into
`data/` with the `meta_ads_` / `linkedin_ads_` prefixes.
For scheduling, use a Claude Code Routine or cron with `claude -p "/weekly-review <slug>"`.

## Repo layout

```
CLAUDE.md                 operating rules every agent follows
.claude/agents/           6 specialist agents
.claude/skills/           slash commands that orchestrate them
gtm/                      analysis modules (rank_shifts, search_terms, funnel, paid_media) + CLI
gtm/fetch/                read-only API pulls: Google Ads, Microsoft Ads, HubSpot, Search Console, Semrush
clients/_template/        client.yaml template — targets, brand terms, themes, GEO prompts, thresholds
clients/demo/             synthetic demo client
reports/                  generated output (git-ignored)
tests/                    pytest regression suite (python -m pytest)
```
