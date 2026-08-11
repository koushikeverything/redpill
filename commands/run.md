---
description: Analyze an attached MIS/stock file — buffer statuses, transfers, orders, cockpit
argument-hint: "[path to MIS file, optional if attached]"
---

Run the Red Pill analysis. Follow the `redpill-inventory` skill exactly; the short version:

1. Locate the stock file: `$ARGUMENTS` if given, else the most recently attached
   Excel/CSV in this conversation. If none exists, say so and offer `/redpill:template`.
2. If the file is Excel, convert to CSV first (values only, first sheet with data).
3. Read the project profile if present: `.redpill/config.json`, `.redpill/mappings.json`,
   `.redpill/overrides.json` (session answers), `.redpill/policies.json`.
4. Run the deterministic engine — never compute inventory numbers yourself:
   `python3 <skill>/scripts/redpill_engine.py <file> --run-dir .redpill/runs/<as-of> --as-of <data date> [--mappings …] [--overrides …] [--config …]`
5. Triage the run verdict from `report.json`: `blocked` → relay reasons, stop;
   quarantined rows → ask-back per the skill's Step 1.5 (candidates → bounded questions →
   `overrides.json` → full rerun).
6. Render and publish the cockpit — every run, no exceptions:
   `python3 <skill>/scripts/render_cockpit.py --run-dir .redpill/runs/<as-of>`
   then publish `cockpit.html` as the artifact. In chat give only: verdict, the two rates,
   net order value (labelled *potential*), transfer savings (labelled *estimated*), and the
   top 3 actions. Long markdown reports only if explicitly requested.
7. Propose any master-data (ADS) changes as explicit approve/reject questions — never apply
   them yourself.

Red Pill is advisory: it recommends, the user executes. Every number you state must come
verbatim from `report.json`.
