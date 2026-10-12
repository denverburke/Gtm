---
name: geo-check
description: Assess a client's AI search / GEO visibility — AI Overview CTR erosion, citation checks for the client's buyer prompts, and AI-referral pipeline in HubSpot.
argument-hint: <client-slug>
---

Run `python -m gtm rank-shifts --client $ARGUMENTS --out` and `python -m gtm funnel --client $ARGUMENTS --out`
if today's reports don't exist yet, then delegate to the `geo-analyst` agent for client `$ARGUMENTS`. Return
its scorecard and actions.
