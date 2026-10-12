---
name: funnel-review
description: HubSpot funnel analysis by original source for a client — stage conversion, lead quality, velocity, and cost per MQL/SQL/customer for paid channels.
argument-hint: <client-slug> [start YYYY-MM-DD] [end YYYY-MM-DD]
---

Delegate to the `funnel-analyst` agent with these arguments: `$ARGUMENTS`. If dates are given, it should
run `python -m gtm funnel --client <slug> --start <start> --end <end> --out`. If paid social looks weak or strong on quality, also brief the
`paid-social-analyst` on the evidence and include its verdict.
