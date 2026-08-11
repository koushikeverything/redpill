---
name: redpill-inventory
description: Red Pill — Theory of Constraints (ToC) buffer-management inventory analysis for demand-driven retail execution. Use this skill whenever the user uploads or mentions a daily or weekly MIS report, stock report, sales report, inventory snapshot, SOH/QOO data, or asks for a replenishment plan, stock transfer plan, demand plan, inventory health report, buffer status, or "right SKU, right place, right time" analysis. Also trigger for phrases like "run redpill", "red pill report", "stock health", "which stores need stock", or any request to turn a SKU × store stock file into ordering/transfer decisions. The skill ingests the raw report, computes buffer statuses per SKU-store, and produces a Final Report + Demand Plan (replenishment orders, inter-store transfers, ADS corrections).
---

# Red Pill — Demand-Driven Inventory Report & Demand Plan

Red Pill turns a raw daily/weekly MIS report into two deliverables:

1. **Final Report** — inventory health across every SKU × Store: status colours, health score, urgency ranking, exceptions.
2. **Demand Plan** — the actions that put the right SKU in the right place at the right time: replenishment orders, inter-store transfers, and ADS (demand-rate) corrections.

The system is grounded in **Theory of Constraints buffer management**: don't forecast far ahead — hold a small dynamic buffer per SKU-location, watch buffer penetration daily, and react by replenishing, transferring, or correcting the demand signal. Stock should go where it sells, not where it sits.

**Core invariant: derived values are never trusted from the input file and never stored — always recompute everything from raw inputs using the formulas in this skill.** If the MIS report contains pre-computed statuses or reorder quantities, recompute them and flag any mismatches.

## Workflow

### Step 1 — Ingest the MIS report

Accept Excel/CSV/pasted tables. Read with pandas/openpyxl. The minimum raw inputs per SKU × Store row:

| Field | Meaning | Required |
|---|---|---|
| SKU / Product | Item identifier | ✅ |
| Store / Location | Selling location | ✅ |
| SOH | Stock on hand (units on shelf) | ✅ |
| QOO | Quantity on order (in transit) | ✅ (assume 0 if absent, and say so) |
| ADS | Average daily sales (units/day) | ✅ (derive from sales history if absent — see Step 2) |
| Lead Time (LT) | Supplier lead time in days, **per SKU × Store** | ✅ |
| Unit price / cost | For order values & savings | Optional |
| Daily/weekly sales history | For ADS correction | Optional but powerful |

Column names vary wildly in real MIS reports ("Closing Stock", "In Transit", "Avg Off-take", "Pending PO"). Map them intelligently, state the mapping you assumed, and ask only if genuinely ambiguous. Lead time and ADS live **per SKU × Store**, never per supplier — the same SKU can have different lead times in different stores.

### Step 1.5 — Missing-information protocol (never guess; ask with pre-guessed answers)

If rows can't be processed, the engine quarantines them and — new in v2 — attaches
**candidates**: deterministically inferred answers with a basis and confidence
(`report.json → quarantine[].candidates`, e.g. lead time "used in 10 other stores for this
SKU", a number found inside text like "7 days", ADS derived from the file's own sales history).
Your job is to turn those into bounded questions, collect answers, and rerun. Protocol:

1. **Batch by problem type** (all missing lead times together, all stock questions together)
   and **cap at ~10 questions per run** — an interrogation kills trust. If more remain, fix the
   biggest-value rows first and say what was deferred.
2. **Ask with the candidate as the default.** The guaranteed baseline is **numbered choices in
   chat** (works on every surface). Where the surface supports native selection cards
   (e.g. the AskUserQuestion tool in Claude Code), use them as a progressive enhancement —
   candidate first, then "enter a different value", then "skip this row". Never depend solely
   on cards; never auto-apply a candidate the user didn't confirm.
3. **Write answers to `overrides.json`** — never edit the raw file (it is immutable):
   `{"rows": [{"line": 164, "set": {"lead_time": 7}}, {"line": 362, "skip": true}],
     "mappings": {"Stok": "soh"}}`
   Then **rerun the engine with `--overrides overrides.json`** — the whole analysis recomputes;
   answers are provenance-logged per row. Never patch numbers into an old output.
4. **Confirmed column mappings go to `mappings.json`** (project-local mapping memory): next
   week's file with the same headers maps silently with confidence `user_confirmed`.
5. **ADS changes are governed** (G14): an override that swings ADS beyond ±50% is applied for
   the run but flagged for review — and a *master-data* change is only ever proposed to the
   user as an explicit approve/reject question, listing before → after → basis.
6. If *nothing* is processable, the engine writes a blocked-run `report.json` with reasons —
   relay them and offer the blank template (`--template`).
### Step 2 — ADS correction (the AI layer)

If sales history is present (a weekly MIS usually has day-wise or week-wise sales):

- Compute actual ADS from recent history (e.g., trailing 14–30 days, or the report period).
- Compare against the stated/master ADS. Flag any SKU-store where actual demand deviates >20% from stated ADS.
- Detect patterns worth naming: weekend uplift, post-promotion decay, volatile stores (high coefficient of variation), consistent under/over-estimation.
- **Use the corrected ADS for all downstream calculations**, and list every correction in the report. The AI layer adjusts inputs, never the formulas.

If no history is present, use the stated ADS and note that corrections weren't possible.

### Step 3 — Compute buffer statuses

Run every row through the deterministic engine — **always**, never by hand: `python scripts/redpill_engine.py input.csv --run-dir runs/<date> --as-of <data-date>` emits the versioned `report.json` that owns every number downstream (plus computed.csv, quarantine.csv and a reproducibility manifest). You orchestrate and explain; you never recompute or re-total engine numbers. **Full formula spec with evaluation order: `references/formulas.md` — read it before computing.** Summary:

```
Pipeline      = SOH + QOO
Buffer        = ADS × LT × 1.5
ROP           = ADS × LT
Days of Stock = Pipeline / ADS   (0 if ADS = 0)
Reorder Qty   = MAX(0, ROUNDUP(ADS × LT × 2.5 − SOH − QOO))
Transfer Qty  = MAX(0, MIN(FROM.SOH − FROM.Buffer, TO.Buffer − TO.Pipeline))
```

Status (evaluate in this exact order, first match wins):

1. **⚫ OUT OF STOCK** — SOH = 0 and QOO = 0
2. **🟣 INCOMING** — SOH = 0 and QOO > 0
3. **🔴 CRITICAL** — Pipeline < 0.5 × ROP
4. **🟡 REORDER** — Pipeline < ROP
5. **🔵 OVERSTOCK** — SOH > 2 × Buffer
6. **🟢 OPTIMAL** — everything else

Health Score = Optimal rows ÷ total rows (as %). Target ≥ 70%.

### Step 4 — Build the Demand Plan

**Replenishment plan:** every row with status OUT OF STOCK, INCOMING, CRITICAL, or REORDER and Reorder Qty > 0. Include qty, order value (qty × unit cost if available), expected delivery date (today + LT), ranked by Days of Stock ascending (who runs out first, acts first).

**Transfer plan (before fresh orders):** for each SKU, pair OVERSTOCK stores (surplus = SOH − Buffer) with deficit stores (OUT OF STOCK / CRITICAL / REORDER; deficit = Buffer − Pipeline). Transfer = MIN(surplus, deficit). Generate pairs greedily, largest deficit matched to largest surplus first; reduce the receiving store's replenishment order by the transferred quantity. Estimated saving = transfer value × savings rate (default 15%, configurable). Transfers beat fresh orders because they're faster than supplier lead time and cost nothing new. If no OVERSTOCK rows exist, say the transfer plan is empty — never invent pairs.

**ADS corrections:** the Step 2 list, phrased as concrete master-data changes ("Raise Goa Face Serum ADS 8 → 11; weekend demand is 2.1× weekday — consider buffer factor 2.2").

### Step 5 — Produce the Final Report

Default deliverable: render the interactive cockpit — `python scripts/render_cockpit.py --run-dir runs/<date>` — and publish `cockpit.html` as the run's artifact, every run. It reads only `report.json`. Markdown (`references/report-template.md` structure) or xlsx/docx only on explicit request. Executive summary first (health score, count by status, top 3 urgent actions), then the detail tables, then the demand plan. Every number must trace back to a formula — no vibes.

### Step 6 — Weekly vs daily cadence

- **Daily MIS** → focus on execution: today's orders and transfers. Keep it short.
- **Weekly MIS** → add the insight layer: ADS corrections, chronic-status SKUs (same status 3+ periods running means a parameter is wrong, not the world), store-level health trends, buffer-factor tuning suggestions.

## Guardrails

- Never store or trust derived values; recompute from raw inputs every run.
- Never fabricate missing data. Absent QOO → assume 0 and disclose. Absent LT → ask.
- Flag rows where computed status conflicts with the report's own status column.
- Transfers reduce replenishment needs — apply them before finalizing order quantities.
- Round order quantities up (ROUNDUP), never down — a partial unit of buffer is a stockout risk.
- Chronic REORDER across most stores = ADS set too low. Chronic OVERSTOCK in one store = ADS set too high or over-ordering habit. Say this explicitly in weekly reports.

## Bundled resources

- `references/formulas.md` — authoritative formula spec, status logic, evaluation order, colour codes. Read before any computation.
- `references/report-template.md` — Final Report + Demand Plan structure with examples. Read before writing the report.
- `scripts/redpill_engine.py` — deterministic calculator: normalized CSV in → computed CSV + JSON summary + `data_gaps.csv` quarantine out. Run with `--template` for a blank fill-in form. Prefer it for >20 rows.
- `assets/mis_input_template.csv` — the blank fill-in format to hand users when required data is missing.
