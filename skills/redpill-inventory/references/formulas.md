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
ROP            = ADS × LT                           (reorder point = lead-time demand)
DaysOfStock    = Pipeline / ADS, or null ("—") if ADS = 0 — never fabricated as 0
                 (= PIPELINE COVER: counts inbound that has not landed yet)
CurrentCover   = SOH / ADS, or null if ADS = 0      (shelf-only days — v2.4/G36)
ReorderQty     = MAX(0, ROUNDUP(ADS × LT × TF − SOH − QOO, 0))   (default TF = 2.5)
                 …but ONLY for actionable rows (OUT OF STOCK / INCOMING / CRITICAL /
                 REORDER). A row that has not crossed its reorder point gets
                 ReorderQty = 0 — you order when you cross ROP, that is the whole
                 ToC discipline. Order totals therefore cover actionable rows only.
ReorderQtyNet  = ReorderQty − units arriving via transfers (floor 0)
OrderValue     = ReorderQty × Price        (gross)
OrderValueNet  = ReorderQtyNet × Price     (what you actually spend)
ExpectedDeliv  = AS-OF date + LT days      (as-of = the data snapshot date, stamped per run)
```

**Engine ownership rule (SPEC §0):** every derived number above is computed by
`scripts/redpill_engine.py` and emitted in its versioned `report.json`. No other layer —
including the model — may re-derive or total these values.

**Duplicate rows:** the first occurrence of a SKU × Store key wins; every later copy is
quarantined with a reason naming the first occurrence's line (and whether it was itself kept or
quarantined). Deterministic regardless of file order.

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


## v1.5 demand & realism rules (engine-computed, G18–G29)

**Demand analysis** (needs ≥4 weeks of sales-history columns; week number = weeks ago):
```
Weekly rates   = units / 7 per usable week
Censoring      : if current SOH = 0, zero-sale weeks are excluded (empty shelf ≠ no
                 demand) and confidence drops              (G19)
Promo weeks    : weeks listed in config promo_weeks_ago are excluded; a week
                 > 2.5 × median of the others is flagged "suspected promo" and
                 needs user confirmation — never auto-excluded          (G18)
CV             = stdev / mean of usable weekly units       (volatility)
ActualADS      = mean(last 4 usable)/7, or median(all usable)/7 when CV > 0.6 (G29)
Correction     when |deviation| > 20% or CV > 0.6; confidence high/medium/low from
               weeks used, CV, and exclusions. Corrections are PROPOSED — applied to
               a run only via --apply-ads-corrections (capped ±max-ads-swing) or an
               approved override. Master data changes by approval only.  (G14)
Verify-first   : deviation > +100% AND SOH > 1.5 × 8-week sales ⇒ stock and sales
                 disagree — the row gets "verify count first" and NO ADS proposal (G23/G50)
```

**Realism gates** (each application disclosed in the report):
```
Overcommit     : pipeline > 2 × Buffer while not OVERSTOCK ⇒ flag (trim the open order) (G24)
Sellable (ATP) = SOH − reserved − damaged (when columns exist); donors give from
                 sellable, never below their buffer                     (G26)
Lane gate      : with --transfer-days T, a receiver whose supplier LT ≤ T orders
                 fresh instead of receiving a slower truck              (G22)
Case packs     : transfer quantities floor to whole packs; below one pack ⇒ skipped (G22)
Policies       : protected donor stores · blocked lanes · no-reorder SKUs (clearance) (G25)
Budget         : --budget B splits net orders (urgency order) into within / deferred (G23)
Incoming risk  : INCOMING rows are graded — inbound below ½×ROP ("order more now") or
                 below ROP ("top-up needed"); a known receipt date later than the lead
                 time ⇒ "later than a fresh order would be"; no receipt date ⇒ disclosed
                 assumption, lower confidence                            (G34)
Transfer cost  : per-unit cost via --transfer-cost-per-unit or per-lane policies
                 lane_costs; est cost and net benefit (saving − cost) emitted per
                 transfer and in totals; unknown cost stays null, never zero (G35)
Mitigation     : OOS/CRITICAL with no inbound and supply landing after the stockout ⇒
                 "expedite, substitute, or hold remaining for full price" (G28)
Segments       : ABC by revenue-rate share (70/90 cumulative), XYZ by CV
                 (<0.25 / <0.6); weighted health = revenue-rate share in OPTIMAL (G20)
Size curves    : per store × style × colour: some sizes OUT/CRITICAL while siblings
                 sit ⇒ broken size run, stranded sizes are dead stock   (G21)
```

## v2.4 timing & impact rules (G36–G38)

**Projected stockout (G36)** — the honest arithmetic version, not a simulation (with one
aggregate QOO and at most one ETA per row, this IS the projection):
```
ProjectedStockout : shelf burns at ADS. Inbound extends the date only if it lands
                    before the shelf runs dry — receipt date used when present,
                    else arrival at LT is ASSUMED (disclosed); a receipt date in
                    the past ⇒ "inbound overdue" warning, treated as landing now.
DryGap            : when inbound lands AFTER the shelf runs dry, the row carries
                    stockout_before_inbound_days and a warning — a row can be
                    OPTIMAL on pipeline quantity yet dark for days in between.
Transfer timing   : with --transfer-days T, a transfer whose receiver runs dry
                    before day T is still recommended but flagged
                    (receiver_dry_before_arrival_days) — expedite or bridge.
```

**Financial impact (G37)** — always labeled *estimated*; price missing ⇒ null, never 0:
```
DailyRevenueAtRisk = ADS × Price       (OUT OF STOCK / CRITICAL rows only)
CapitalTiedUp      = (SOH − Buffer) × Price   (OVERSTOCK rows: stock above protection)
```

**Assumptions & policies (G38):** `report.json → assumptions_and_policies` lists every
policy value, applied policy, and disclosed assumption for the run, in one place.

## Glossary — what kind of statement is each number?

Every value Red Pill emits is one of four kinds. The report keeps them separate; so
should any conversation about the model.

| Kind | Meaning | Examples |
|---|---|---|
| **Formula** | Pure arithmetic from inputs — deterministic, reproducible | `Pipeline = SOH + QOO` · `ROP = ADS × LT` · `TransferQty = min(surplus, deficit)` |
| **Model estimate** | Computed from data, carries uncertainty — confidence-scored or labeled | ActualADS · CV · projected stockout date · revenue-at-risk · transfer savings |
| **Policy** | A configurable business choice — defensible, tunable, never "proven" | BF 1.5 · TF 2.5 · SR 0.15 · ½×ROP critical line · 2×Buffer overstock line · ±20% correction trigger · CV 0.6 volatility line · ±50% swing cap |
| **Assumption** | A stated guess where data is missing — always disclosed in the report | blank QOO = 0 · no-ETA inbound arrives within LT · SOH fully sellable when reserved/damaged columns are absent |

### Vocabulary map (classical inventory theory ↔ Red Pill)

| Classical term | Red Pill equivalent | Relationship |
|---|---|---|
| Lead-time demand | **ROP** = `ADS × LT` | identical — our reorder line *is* lead-time demand |
| Safety stock | the buffer margin above ROP | `Buffer − ROP = ADS × LT × (BF − 1)` — BF is the safety-stock policy in one visible knob |
| Protection level | **Buffer** = `ADS × LT × BF` | the ToC buffer folds lead-time demand + safety stock into one number |
| Order-up-to / target stock | `ADS × LT × TF` | TF is the order-up-to policy factor |
| Inventory position | **Pipeline** = `SOH + QOO` | commitments subtracted where the data exists (sellable/ATP governs donor math) |
| Reorder trigger vs order quantity | status ladder vs `ReorderQty` | "when to order" = crossing ROP; "how much" = target − pipeline; computed separately, never conflated |
| Days of cover | CurrentCover vs DaysOfStock | shelf-only vs including inbound — two different safety statements |

Using fixed, visible buffer factors instead of a stochastic safety-stock model is a
deliberate Theory-of-Constraints design choice (react fast to buffer penetration,
stay explainable), not an oversight. Tune BF per SKU × Store; don't replace it silently.

### Statistical definitions (implementation-exact)

- **CV** = *population* standard deviation ÷ mean of usable weekly units (n divisor,
  not n−1). Zero-sale weeks count unless excluded by stockout-censoring (empty shelf)
  or a confirmed promo week.
- **ActualADS** = mean(last 4 usable weeks) ÷ 7, switching to median(all usable) ÷ 7
  when CV > 0.6.
- **Deviation** = `(Actual − Stated) / Stated`, defined only when Stated > 0; a stated
  ADS of 0 with real sales gets its own "set master ADS" recommendation instead of a
  fabricated percentage.
