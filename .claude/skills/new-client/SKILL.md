---
name: new-client
description: Onboard a new agency client into the workspace — create clients/<slug>/client.yaml from the template by interviewing the user, and list exactly which exports to drop into data/.
argument-hint: <client-slug>
---

1. Copy `clients/_template/` to `clients/$ARGUMENTS/` and create `clients/$ARGUMENTS/data/`.
2. Ask the user (one AskUserQuestion round, at most 4 questions) for anything you can't infer: target CPA,
   brand terms, competitors, and the main campaign themes. If they give a website, WebFetch it to draft
   the themes, landing_pages and geo_prompts yourself, then ask them to confirm.
3. Write client.yaml.
4. Print the export checklist from README.md ("What to export"), with file names filled in for this client.
