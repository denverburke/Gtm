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

## Going from "drop exports" to fully hands-off

The CSV layer works today with zero credentials. To automate collection, swap exports for connectors one at a time:

1. **MCP connectors**: add HubSpot, Google Search Console, Google Ads, Semrush and LinkedIn MCP servers to
   Claude Code (`claude mcp add …`). The agents can then pull fresh data before analysing. Keep the `gtm/`
   modules as the maths layer by having the agent write pulled data into `data/` with the same prefixes.
2. **Scheduled runs**: a Claude Code Routine (cloud) or cron with `claude -p "/weekly-review <slug>"` every
   Monday 07:00 per client, with the brief committed to `reports/` or posted to Slack or email.
3. **Alerting**: a daily lightweight run of `rank-shifts` and `paid-media` that only messages you when a
   threshold breaks (a top-10 keyword drops out, or a campaign spends 2× target CPA without converting).

## Repo layout

```
CLAUDE.md                 operating rules every agent follows
.claude/agents/           6 specialist agents
.claude/skills/           slash commands that orchestrate them
gtm/                      analysis modules (rank_shifts, search_terms, funnel, paid_media) + CLI
clients/_template/        client.yaml template — targets, brand terms, themes, GEO prompts, thresholds
clients/demo/             synthetic demo client
reports/                  generated output (git-ignored)
tests/                    pytest regression suite (python -m pytest)
```
