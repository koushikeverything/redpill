---
name: redpill-inventory
description: Red Pill — Theory of Constraints (ToC) buffer-management inventory analysis for demand-driven retail execution. Use this skill whenever the user uploads or mentions a daily or weekly MIS report, stock report, sales report, inventory snapshot, SOH/QOO data, or asks for a replenishment plan, stock transfer plan, demand plan, inventory health report, buffer status, or "right SKU, right place, right time" analysis. Also trigger for phrases like "run redpill", "red pill report", "stock health", "which stores need stock", or any request to turn a SKU × store stock file into ordering/transfer decisions. The skill ingests the raw report, computes buffer statuses per SKU-store, and produces an interactive cockpit + Demand Plan (replenishment orders, inter-store transfers, ADS corrections).
---

# Red Pill — Demand-Driven Inventory Cockpit & Demand Plan

Red Pill turns a raw daily/weekly MIS report (one row per SKU × Store: stock, on-order,
demand rate, lead time) into an **interactive cockpit** and a **Demand Plan**: inter-store
transfers first, then net replenishment orders, then demand-signal (ADS) corrections.
Grounded in Theory-of-Constraints buffer management: hold a small dynamic buffer per
SKU-location, watch buffer penetration, react. Stock goes where it *sells*, not where it sits.

## Non-negotiables (read first — these override any instinct)

1. **The engine computes; you orchestrate and explain.** `scripts/redpill_engine.py` is the
   sole source of parsing, validation, math, statuses, transfers, ordering, and totals. You
   never calculate, re-derive, or re-total a business number. Every figure you state comes
   verbatim from the engine's `report.json`.
2. **The cockpit ships every run.** Render `cockpit.html` via `scripts/render_cockpit.py` and
   publish it as the run's artifact — always. Markdown reports (structure in
   `references/report-template.md`) or xlsx/docx only on explicit request.
3. **The raw file is immutable.** User corrections go to `overrides.json`; the whole analysis
   reruns. Never patch numbers into an old output, never edit the input.
4. **Never guess.** Blank ≠ zero. Unusable rows are quarantined by the engine and asked back
   (Step 1.5). A degraded/blocked run verdict is relayed prominently, never smoothed over.
5. **Money labels.** Order values are **potential** spend; transfer savings are **estimated**;
   value *moved* is never called value *saved*. Nothing is "realised" — Red Pill does not
   track execution.
6. **Advisory only.** Red Pill recommends; the user executes. It does not modify ERP/POS
   data, place orders, dispatch transfers, or send messages — say so if asked.
7. **Master data changes by approval only.** Corrected ADS may drive *this run's* math (the
   engine caps override swings); the *master* value changes only when the user explicitly
   approves a proposed before → after with basis.

## Workflow

### Step 1 — Locate inputs and profile

Accept Excel/CSV/pasted tables; convert Excel to CSV (first data sheet, values only).
Read the project profile if present: `.redpill/config.json` (currency, tracked fields),
`.redpill/mappings.json` (user-confirmed header maps), `.redpill/policies.json` (business
rules), prior `.redpill/runs/`. Determine the data's **as-of date** (ask if not evident from
the file or name — never imply the data is live).

### Step 2 — Run the engine

```bash
python3 scripts/redpill_engine.py <input.csv> \
  --run-dir .redpill/runs/<as-of> --as-of <as-of> \
  [--mappings .redpill/mappings.json] [--overrides overrides.json] \
  [--config .redpill/config.json]
```

The run directory receives: `report.json` (versioned data contract — everything downstream
reads only this), `computed.csv` (incl. passthrough columns), `quarantine.csv`,
`summary.json`, an immutable input copy, `config_snapshot.json`, and `run-manifest.json`
(hashes; `--rerun <dir>` must reproduce identically).

Column mapping is automatic for common retail headers ("Closing Stock", "Avg Off-take/Day",
"Outlet", "MRP"…) with confidence classes in `report.json → mapping`. If mapping is
`ambiguous`, confirm with ONE bounded question before trusting the run. Missing required
columns → the engine writes a blocked-run report and a fill-in template; relay and stop.

### Step 1.5 — Missing-information protocol (never guess; ask with pre-guessed answers)

If rows can't be processed, the engine quarantines them and attaches **candidates**:
deterministically inferred answers with a basis and confidence
(`report.json → quarantine[].candidates`, e.g. lead time "used in 10 other stores for this
SKU", a number found inside text like "7 days", ADS derived from the file's own sales
history). Turn those into bounded questions, collect answers, rerun:

1. **Batch by problem type** (all missing lead times together) and **cap at ~10 questions
   per run**. If more remain, fix the biggest-value rows first and say what was deferred.
2. **Ask with the candidate as the default.** Baseline: **numbered choices in chat** (works
   everywhere). Native selection cards (e.g. AskUserQuestion in Claude Code) are a
   progressive enhancement — candidate first, then "different value", then "skip this row".
   Never auto-apply a candidate the user didn't confirm.
3. **Write answers to `overrides.json`**:
   `{"rows": [{"line": 164, "set": {"lead_time": 7}}, {"line": 362, "skip": true}],
     "mappings": {"Stok": "soh"}}`
   then **rerun with `--overrides`** — full recompute, provenance-logged.
4. **Confirmed mappings persist** in `.redpill/mappings.json` so next week's identical
   headers map silently (`user_confirmed`).
5. **ADS overrides beyond ±50% are applied but flagged** by the engine — treat the flag as
   "review before proposing a master change".
6. Nothing processable at all → relay the blocked verdict + offer `--template`.

### Step 3 — Triage the run verdict

`report.json → run.verdict`: **healthy** → proceed. **degraded** → proceed but lead with the
banner reasons in chat AND note the cockpit shows them. **blocked** → stop; relay reasons;
do not present any plan numbers.

### Step 4 — Demand-signal corrections (engine-computed)

`report.json → ads_corrections` carries the engine's analysis: stated vs actual rate
(stockout-censored, promo-aware, median for volatile SKUs), deviation, CV, confidence, and a
plain recommendation. `plausibility_flags` lists rows where stock and claimed sales disagree —
those get "verify count first" and no ADS proposal. Your job:
- **Suspected promo weeks** (`excluded.suspected_promo_weeks_ago`) → one bounded question
  ("was that week a promotion?"); if yes, add to `config.promo_weeks_ago` and rerun.
- **Present corrections as approve/reject items** (before → after → basis → confidence).
  On approval, rerun with `--apply-ads-corrections` (the engine caps swings) — or write the
  approved values into master data outside Red Pill. Never apply silently.
- Quote correction numbers verbatim; add no arithmetic of your own.

### Step 5 — Deliver

```bash
python3 scripts/render_cockpit.py --run-dir .redpill/runs/<as-of>
```

Publish `cockpit.html` as the artifact — the default deliverable, every run. In chat, give a
five-line brief only: verdict · action rate + excess rate · net order value (*potential*) ·
transfer savings (*estimated*) · top 3 actions by urgency. Everything else lives in the
cockpit (lenses, drawer decision traces, CSV exports).

### Step 6 — Approvals & cadence

Present proposed master-data fixes as explicit approve/reject items. Daily MIS → keep to
execution (today's transfers/orders). Weekly MIS → add insight commentary (chronic statuses,
store health ranking) — grounded in report.json fields only.

## Error handling

- Engine exit ≠ 0: read stderr; blocked-mapping runs still write `report.json` — use its
  `verdict_reasons`. Empty file → offer `--template`.
- Renderer failure: report it; fall back to the chat brief + `computed.csv`; never hand-build
  a substitute cockpit.
- Anything that smells like a bug: capture the command + stderr for the user, don't improvise
  numbers around it.

## Bundled resources

- `scripts/redpill_engine.py` — deterministic engine (v2): report.json contract, run dirs,
  reproducibility (`--rerun`), overrides, mapping memory, candidates. `--template` for the
  blank form.
- `scripts/render_cockpit.py` — cockpit renderer (template + report.json injection, nothing else).
- `assets/cockpit_template.html` — the fixed cockpit template (do not fork per-run).
- `references/formulas.md` — authoritative formula spec and status ladder. Read before
  explaining any number.
- `references/report-template.md` — markdown report structure (on-request format only).
- `assets/mis_input_template.csv` — blank fill-in format.
