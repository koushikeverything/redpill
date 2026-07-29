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

### Step 1.5 — Missing-information protocol (never guess, always ask with a form)

If the report can't be processed — missing columns, or rows with unusable values — **do not silently default and compute.** A defaulted lead time of 0 or an "N/A" read as 0 produces confidently wrong statuses and phantom orders. Instead:

1. **Process what's valid, quarantine what isn't.** The engine does this automatically: bad rows go to `data_gaps.csv` with a `reason` per row (blank ADS, missing lead time, negative/non-numeric stock, duplicate SKU+Store). Valid rows still get a full report, clearly marked partial.
2. **Give the user a fill-in format, pre-populated with everything already known.** Present it as a table in chat (and/or hand them `data_gaps.csv` / the blank template from `assets/mis_input_template.csv` or `python redpill_engine.py --template`). Blank cells = exactly what's needed; nothing more. Example:

   | sku | store | soh | qoo | ads | lead_time | unit_price | needed |
   |---|---|---|---|---|---|---|---|
   | Face Serum | Goa | 60 | 0 | 4 | **?** | 450 | supplier lead time in days for this SKU at Goa |
   | Protein Powder | Mumbai | **?** | 0 | 8 | 7 | 900 | shelf stock — report said "N/A" |

3. **Distinguish blank from zero.** Blank ADS ≠ zero demand; blank QOO → assume 0 (safe) and disclose. Missing lead time is never assumable.
4. **When they reply with the filled values, merge and rerun** the full pipeline — never patch numbers into an old output.
5. If *nothing* is processable (or no file at all), send the blank template with the one-line meaning of each column and one worked example row.


### Step 2 — ADS correction (the AI layer)

If sales history is present (a weekly MIS usually has day-wise or week-wise sales):

- Compute actual ADS from recent history (e.g., trailing 14–30 days, or the report period).
- Compare against the stated/master ADS. Flag any SKU-store where actual demand deviates >20% from stated ADS.
- Detect patterns worth naming: weekend uplift, post-promotion decay, volatile stores (high coefficient of variation), consistent under/over-estimation.
- **Use the corrected ADS for all downstream calculations**, and list every correction in the report. The AI layer adjusts inputs, never the formulas.

If no history is present, use the stated ADS and note that corrections weren't possible.

### Step 3 — Compute buffer statuses

Run every row through the formula engine. Use `scripts/redpill_engine.py` for deterministic computation (pipe the normalized CSV through it), or apply the formulas directly for small datasets. **Full formula spec with evaluation order: `references/formulas.md` — read it before computing.** Summary:

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

Follow the structure in `references/report-template.md`. Deliver as a Markdown file for routine runs; use the xlsx/docx skills if the user asks for those formats. Executive summary first (health score, count by status, top 3 urgent actions), then the detail tables, then the demand plan. Every number must trace back to a formula — no vibes.

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
