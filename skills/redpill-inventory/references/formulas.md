# Red Pill Formula Specification

Authoritative logic, ported from `RedPill_Inventory_System.xlsx`. Every derived value is computed fresh from raw inputs — nothing derived is ever stored or trusted from an input file.

## Raw inputs (per SKU × Store)

| Symbol | Field | Notes |
|---|---|---|
| SOH | Stock on hand | Units physically at the store |
| QOO | Quantity on order | Units in transit / open POs |
| ADS | Average daily sales | Units/day, **per SKU × Store** |
| LT | Lead time (days) | **Per SKU × Store**, not per supplier — the same SKU can have a 7-day LT in Mumbai and 14-day in Goa |
| Price | Unit price/cost | Optional; enables order values and savings |
| BF | Buffer factor | Default **1.5**; tunable per SKU × Store (volatile/weekend-heavy stores may need 2.0–2.2) |
| TF | Target factor | Default **2.5**; replenish-up-to level in lead-time-days of demand |
| SR | Savings rate | Default **0.15**; fraction of transfer value saved vs a fresh order |

## Derived values

```
Pipeline       = SOH + QOO
Buffer         = ADS × LT × BF                      (default BF = 1.5)
ROP            = ADS × LT                           (reorder point)
DaysOfStock    = Pipeline / ADS, or 0 if ADS = 0    (IFERROR semantics)
ReorderQty     = MAX(0, ROUNDUP(ADS × LT × TF − SOH − QOO, 0))   (default TF = 2.5)
OrderValue     = ReorderQty × Price
ExpectedDeliv  = TODAY + LT days
```

## Status logic — evaluate strictly in this order, first match wins

| # | Condition | Status | Colour | Meaning |
|---|---|---|---|---|
| 1 | SOH = 0 AND QOO = 0 | **OUT OF STOCK** | ⚫ `#1A1A1A` | Losing sales right now, nothing coming |
| 2 | SOH = 0 AND QOO > 0 | **INCOMING** | 🟣 `#8B5CF6` | Empty shelf but replenishment in transit |
| 3 | Pipeline < 0.5 × ROP | **CRITICAL** | 🔴 `#EF4444` | Will stock out before replenishment can land |
| 4 | Pipeline < ROP | **REORDER** | 🟡 `#F59E0B` | Order now; still time if you act today |
| 5 | SOH > 2 × Buffer | **OVERSTOCK** | 🔵 `#3B82F6` | Capital and shelf tied up; transfer donor |
| 6 | otherwise | **OPTIMAL** | 🟢 `#22C55E` | Buffer healthy; no action |

The order matters: an SOH = 0 row must resolve as OUT OF STOCK or INCOMING before the pipeline checks run, and CRITICAL must be tested before REORDER. (Failing to distinguish rule 1 from rule 2 was a known bug in Excel v1.)

**ADS = 0 convention:** buffer, ROP, and DaysOfStock all become 0, so any row with stock lands in OVERSTOCK (no demand → any stock is excess, making it a legitimate transfer donor for dead-stock rotation), and a row with no stock lands in OUT OF STOCK with ReorderQty 0. Flag ADS = 0 rows in the report's data notes — they usually mean missing master data rather than genuinely zero demand.

Hex codes are the app's defaults; keep the six-status semantics even if the user restyles colours.

## Dashboard metrics

```
HealthScore   = COUNT(status = OPTIMAL) / COUNT(all rows)      → report as %
StatusCounts  = COUNTIF per status
UrgencyRank   = sort actionable rows by DaysOfStock ascending
```

Target health ≥ 70%. Below 50% = same-day action required.

## Transfer pairing (per SKU, dynamic — never pre-built)

```
Surplus(from) = FROM.SOH − FROM.Buffer          (only OVERSTOCK stores donate)
Deficit(to)   = TO.Buffer − TO.Pipeline         (OUT OF STOCK / CRITICAL / REORDER stores receive)
TransferQty   = MAX(0, MIN(Surplus, Deficit))
TransferValue = TransferQty × Price
EstSaving     = TransferValue × SR              (default SR = 0.15)
```

Pair greedily within each SKU: largest deficit matched to largest surplus first; decrement both and continue until either side is exhausted. After pairing, reduce the receiving store's ReorderQty by the transferred units (floor at 0). A snapshot with zero OVERSTOCK rows legitimately produces an empty transfer plan.

## ADS correction (AI layer)

The AI layer changes **inputs only** — never the formulas above.

Given sales history per SKU × Store:

```
ActualADS  = mean(daily sales over trailing window)     (14–30 days, or the report period)
Deviation  = (ActualADS − StatedADS) / StatedADS
CV         = stdev(daily sales) / mean(daily sales)
WeekendIdx = mean(weekend sales) / mean(weekday sales)
```

Correction rules:
- |Deviation| > 20% → recommend updating master ADS to ActualADS (rounded sensibly); use ActualADS for this run's calculations.
- CV > 0.6 → volatile SKU-store; recommend raising BF (e.g., 1.5 → 2.0).
- WeekendIdx > 1.8 → weekend-heavy store; recommend BF 2.0–2.2 or split weekday/weekend replenishment cycles.
- Same SKU in REORDER/CRITICAL across ≥ 4 of 5 stores for 3+ periods → master ADS almost certainly too low; correct globally.
- Post-promotion: exclude promo-period spikes from the trailing window unless the promo continues.

Every correction applied must appear in the Final Report with before → after values and one-line reasoning.
