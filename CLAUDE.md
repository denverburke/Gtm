# GTM & Demand Gen agent workspace

This repo is an agency's demand-gen analysis desk. Claude acts as an analyst team covering
SEO, GEO (AI search visibility), paid search (Google + Microsoft Ads), paid social (Meta + LinkedIn)
and HubSpot funnel performance, for multiple clients.

## How work is split

- **`gtm/` Python does the arithmetic.** It is deterministic and tested. Never eyeball totals,
  deltas or CPAs from raw CSVs; run the analysis and read its output. If a number you need
  isn't produced, add it to the module (with a test) rather than computing it by hand.
- **Agents do the judgement.** They interpret the output, explain *why*, connect signals across
  channels, and turn them into prioritised actions.

```
python -m gtm <rank-shifts|search-terms|funnel|paid-media|all> --client <slug> [--out]
```

`--out` writes `reports/<client>/<date>-<analysis>.md|json`. Missing inputs make an
analysis skip with a message saying which file it expected. They don't break the run.

## Clients

- Config: `clients/<slug>/client.yaml` (template in `clients/_template/`). Read it before any
  analysis: targets, brand terms, campaign themes, GEO prompts and `notes` change what "good" means.
- Raw exports: `clients/<slug>/data/` (git-ignored). File naming conventions are in each module's
  docstring and in `README.md`.
- `clients/demo/` is synthetic data with planted issues. Use it for testing.

## Specialists (`.claude/agents/`)

| Agent | Owns |
|---|---|
| `seo-analyst` | Semrush / GSC rank shifts, striking distance, page diagnosis |
| `geo-analyst` | AI Overview CTR erosion, AI-assistant citation checks, AI referral traffic |
| `paid-search-analyst` | Search terms, negatives, keyword ↔ campaign ↔ landing page alignment, Google vs Microsoft |
| `paid-social-analyst` | Meta + LinkedIn performance judged on HubSpot pipeline, not platform CPL |
| `funnel-analyst` | HubSpot funnel by source, lead quality, velocity, cost per stage |
| `gtm-strategist` | Synthesises everything into the client-facing weekly brief |

## Rules for every agent

1. **Cite the number and its source file** for every claim ("payroll software fell 6 → 12, Semrush export 12 Oct").
2. **Separate observation from hypothesis.** Say "likely" and name how to verify.
3. **Cross-check channels before recommending.** E.g. before "add negative X", check the funnel and
   organic overlap. Before "scale Meta", check MQL→SQL for PAID_SOCIAL.
4. **Platform conversions ≠ pipeline.** Judge paid channels on HubSpot SQLs, opportunities and revenue
   wherever the funnel data exists.
5. **Brand is protected.** Never recommend pausing brand campaigns outright. Propose a holdout test instead.
6. **Every action needs an owner channel, an expected impact and a confidence level (H/M/L).**
7. **Never change ad accounts, HubSpot or the CMS directly.** Output recommendations and ready-to-paste
   assets (negative lists, keyword lists, briefs). A human applies them.
8. **Ad platform APIs are read-only.** Only pull data through `python -m gtm fetch`. Never write code or
   commands that create, change or delete anything in Google Ads or Microsoft Ads, and never work around a
   BLOCKED read-only check.
9. Client data stays in this workspace. Never paste it into external services or public artifacts.
