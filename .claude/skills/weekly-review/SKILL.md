---
name: weekly-review
description: Run the full weekly demand-gen review for a client — SEO, GEO, paid search, paid social and HubSpot funnel — and produce a client-ready brief. Use when asked for a weekly/monthly review, client report, or "how is <client> doing".
argument-hint: <client-slug>
---

Weekly review for client `$ARGUMENTS`.

1. Read `clients/$ARGUMENTS/client.yaml`. List `clients/$ARGUMENTS/data/` and note which inputs exist and how
   old they are. If a core export is missing or more than 10 days old, say so up front. Don't silently skip it.
2. Run `python -m gtm all --client $ARGUMENTS --out` once to produce every report.
3. Launch the specialists **in parallel**, each with the client slug and pointed at its report in
   `reports/$ARGUMENTS/`: `seo-analyst`, `geo-analyst`, `paid-search-analyst`, `paid-social-analyst`,
   `funnel-analyst`. Skip any whose inputs are missing. Ask each for findings only (no preamble), with every
   number sourced.
4. Pass all findings to `gtm-strategist` to write `reports/$ARGUMENTS/<today>-weekly-brief.md`.
5. Reply with the TL;DR, the top 5 actions and the brief's path. Also attach the paste-ready assets
   (negative keyword list, keywords to add) the paid-search-analyst produced.
