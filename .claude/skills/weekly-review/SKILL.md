---
name: weekly-review
description: Run the full weekly demand-gen review for a client — SEO, GEO, paid search, paid social and HubSpot funnel — and produce a client-ready brief. Use when asked for a weekly/monthly review, client report, or "how is <client> doing".
argument-hint: <client-slug>
---

Weekly review for client `$ARGUMENTS`.

1. Read `clients/$ARGUMENTS/client.yaml`. List `clients/$ARGUMENTS/data/` and note which inputs exist and how
   old they are. If a core export is missing or more than 10 days old, say so up front. Don't silently skip it.
2. If client.yaml has `accounts:` and the API secrets are set, run `python -m gtm fetch --client $ARGUMENTS`
   first. If it prints BLOCKED, stop and tell the user: credentials that can make changes must not be
   used, and you must not work around the block. Fall back to existing exports only if the user agrees.
3. Run `python -m gtm all --client $ARGUMENTS --out` once to produce every report.
4. Launch the specialists **in parallel**, each with the client slug and pointed at its report in
   `reports/$ARGUMENTS/`: `seo-analyst`, `geo-analyst`, `paid-search-analyst`, `paid-social-analyst`,
   `funnel-analyst`. Skip any whose inputs are missing. Ask each for findings only (no preamble), with every
   number sourced.
5. Pass all findings to `gtm-strategist` to write `reports/$ARGUMENTS/<today>-weekly-brief.md`.
6. Reply with the TL;DR, the top 5 actions and the brief's path. Also attach the paste-ready assets
   (negative keyword list, keywords to add) the paid-search-analyst produced.
