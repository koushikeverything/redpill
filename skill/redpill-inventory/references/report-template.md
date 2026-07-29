# Final Report + Demand Plan — Structure

Output as Markdown by default. Use the xlsx skill if the user wants a workbook, docx for a formal document. Keep the executive summary on one screen — an operator should know their three most urgent moves in ten seconds.

---

## 1. Executive Summary

```
RED PILL — INVENTORY HEALTH REPORT
Period: <report date / week>          Scope: <N SKUs × M stores = R rows>

HEALTH SCORE: 45%  (target ≥ 70%)  ▼ vs last period if known

⚫ Out of Stock   2      🔴 Critical   6      🟡 Reorder   8
🟣 Incoming       1      🟢 Optimal   18      🔵 Overstock 5

TOP 3 ACTIONS TODAY
1. TRANSFER 50 × Vitamin C: Goa → Bangalore (saves ₹2,400, lands in 2 days vs 10)
2. ORDER 270 × Face Serum for Mumbai (0.3 days of stock left)
3. ORDER 120 × Protein Powder for Delhi (1.1 days of stock left)
```

## 2. Status Detail (all rows)

Table sorted by urgency (Days of Stock ascending), columns: SKU · Store · SOH · QOO · Pipeline · Buffer · ROP · Days of Stock · Status. Group or filter to actionable rows first if >50 rows; put the full table in an appendix or separate sheet.

If the input file carried its own status column, add a **Discrepancies** subsection listing every row where recomputed status ≠ reported status, with the reason.

## 3. Demand Plan

### 3a. Transfer Plan (execute first)

| SKU | From (status) | To (status) | Qty | Value | Est. Saving | Why |
|---|---|---|---|---|---|---|
| Vitamin C | Goa 🔵 200 vs buffer 112 | Bangalore ⚫ | 50 | ₹16,000 | ₹2,400 | 2-day truck beats 10-day supplier |

State totals: units moved, value, total estimated savings. If empty: "No overstock donors this period — transfer plan empty (this is a healthy sign, not an error)."

### 3b. Replenishment Plan (net of transfers)

| SKU | Store | Status | Reorder Qty | Order Value | Expected Delivery | Days of Stock |
|---|---|---|---|---|---|---|
| Face Serum | Mumbai | 🔴 | 270 | ₹1,21,500 | <today+7> | 0.3 |

Ranked by Days of Stock ascending. Show total order value, and per-supplier subtotals if supplier data exists. Note explicitly which rows had quantities reduced by incoming transfers.

### 3c. ADS Corrections & Parameter Tuning (weekly reports)

| SKU | Store | Stated ADS | Actual ADS | Deviation | Action |
|---|---|---|---|---|---|
| Protein Powder | All | 4 | 6.2 | +55% | Raise master ADS to 6; chronic REORDER in 4/5 stores |
| Face Serum | Goa | 8 | 8.3 | +4% | Keep ADS; raise buffer factor 1.5 → 2.2 (weekend index 2.1×) |

## 4. Insights (weekly cadence only)

- Store health ranking (health score per store).
- Chronic statuses: any SKU-store in the same non-optimal status 3+ periods → parameter problem, name the fix.
- Right-SKU-right-place summary: which stores are systematically over-bought vs starved, in plain language.

## 5. Assumptions & Data Notes

Always close with: column mapping used, missing fields and how they were handled (e.g., "QOO absent — assumed 0"), buffer/target/savings factors used, ADS window used, and any rows excluded (bad data) with reasons.
