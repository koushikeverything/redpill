# How Red Pill Works — the complete walkthrough (v2.0.0)

> Every step of the shipped pipeline, in the exact order it executes, with every formula and
> rule explained in plain terms and worked on real numbers. The running example is the test
> fixture this build is verified against: **Priya**, planning head of a 12-store Indian
> apparel chain, and her Sunday-night stock file — 30 SKUs × 12 stores = 361 rows, complete
> with real-world mess. Every headline number below is pinned by the 48-test golden suite.

---

## 0. The scenario

Priya's point-of-sale system emails her an **MIS report** every Sunday night ("Management
Information System" — retail jargon for *the routine stock Excel*). One row per **SKU**
("stock-keeping unit" — one exact variant: *black crew-neck t-shirt, size M*) per store:

| SKU Code | Outlet | Closing Stock | In Transit | Avg Off-take/Day | Lead Time (Days) | MRP | System Status | Sold W-8 … W-1 |
|---|---|---|---|---|---|---|---|---|
| TSH-CRW-BLK-M | Delhi (CP) | 0 | 0 | 8 | 7 | 799 | OUT OF STOCK | 55 … 95 |

Her file is *realistically ugly*: a stock value of `1,240` (thousands comma), a price of
`₹2,499` (currency symbol), an ADS of `"  8 "` (whitespace), a lead time of `"7 days"`
(text), an `N/A`, a `-6`, blanks, and one duplicated row. Ten rows are genuinely broken.

Monday 9 AM she attaches the file and types **`/redpill:run`** (or just *"run red pill on
this"*). Everything below happens from that one action.

---

## 1. One-time setup (before any of this — 3 minutes, optional)

`/redpill:setup` asks five skippable questions (numbered choices in chat; selection cards
where the surface supports them) and stores the answers **in Priya's project, locally**:

| File | Holds | Used for |
|---|---|---|
| `.redpill/config.json` | retail type, currency, tracked fields, `promo_weeks_ago` | display + demand analysis |
| `.redpill/policies.json` | protected stores, blocked lanes, no-reorder (clearance) SKUs | hard constraints on the plan |
| `.redpill/mappings.json` | header maps she has confirmed before | silent mapping next week |
| `.redpill/runs/<date>/` | every run's complete, reproducible record | audit + rerun |

Nothing here is required. Skipping means engine defaults plus a couple more questions later.
Nothing is ever written that she didn't explicitly confirm.

---

## 2. Reading the file as it actually is

The deterministic engine (`redpill_engine.py` — pure standard-library Python, no network,
no telemetry) takes over. **Rule zero of the whole system: this engine computes every
number; the AI layer only orchestrates, asks, and explains.** The raw file is copied into
the run directory and never modified.

### 2a. Header mapping — logic

Each header is **normalized**: lowercased, every run of non-letters/digits collapsed to one
underscore. `"Avg Off-take/Day"` → `avg_off_take_day`; `"Lead Time (Days)"` →
`lead_time_days`. The normalized name is looked up in a two-tier alias table:

- **exact** aliases (`closing_stock` → stock on hand; `outlet` → store; `mrp` → price;
  `in_transit` → on-order …) → confidence **exact**
- **high** aliases (`avg_off_take_day`, `supplier_lead_time`, `run_rate` …) → confidence
  **high**
- a mapping Priya confirmed previously (from `mappings.json`) → confidence
  **user_confirmed**, wins over everything
- two columns matching the same target → confidence **ambiguous** → the run is marked
  *degraded* until she confirms with one bounded question
- a **required** column not found at all (SKU, store, stock, ADS, lead time) → the run is
  **blocked**: a `report.json` with the reasons + a blank fill-in template, and it stops.
  No numbers are shown from a blocked run, ever.

Columns that map to nothing (Style, Colour, Size, Supplier, the file's own "System Status",
the eight "Sold W-n" history columns) are **passed through untouched** — later stages need
them.

*Example:* all 21 of Priya's headers map automatically — 5 required + optional price/on-order
at exact/high confidence, 13 passthrough.

### 2b. Value parsing — logic

One parser handles every real-world number format:
strip a leading currency marker (`₹`, `Rs.`, `INR`, `$`, `€`, `£`) → treat `(500)` as
−500 (accounting style) → remove commas and internal spaces → parse.

*Examples:* `"1,240"` → 1240 · `"₹2,499"` → 2499 · `"  8 "` → 8 · `"(500)"` → −500 ·
`"N/A"`, `"abc"`, `"7 days"` → *unparseable* (handled next stage, never silently zeroed).
Every cleaned value gets a **provenance note** on its row: `price: parsed '₹2,499' -> 2499`.

An unreadable *optional* value (like a price) keeps the row but logs a **warning** — because
a blank rupee column must be distinguishable from a broken one. An unreadable *required*
value quarantines the row.

### 2c. Freshness

The run is stamped with an **as-of date** (`--as-of`, asked if not evident). Every
"expected delivery" date is computed from it, and the cockpit displays *"data as of Sun 10
Aug"* — Red Pill never implies the data is live.

---

## 3. The trust layer — three levels of "can I believe this?"

### 3a. Row quarantine — the rules

A row is **set aside (quarantined), never guessed at**, when:

| Rule | Priya's file example | Why |
|---|---|---|
| blank SKU or store | store missing on a chinos row | can't place the stock |
| stock not a number / negative | `N/A`, `-6` | physical stock can't be negative |
| on-order not a number / negative | `-10` | same |
| ADS blank or non-numeric | blank, `abc` | **blank is NOT zero demand** — it's "you forgot to tell me" |
| lead time missing / ≤ 0 / text | blank, `0`, `"7 days"` | the whole model runs on it |
| duplicate SKU × store | the doubled Pune t-shirt row | **first occurrence wins**; every later copy is quarantined with a reason naming the first line (deterministic regardless of file order — even when the first copy was itself quarantined, the reason says so) |

Special conventions: blank on-order → assumed **0** and disclosed (that one *is* safe);
ADS stated as **0** → row kept but flagged (zero demand means any stock is excess — the
dead-stock convention); fractional stock (`12.5`) → kept with a warning (physical units
expected).

*Result on Priya's file: 351 rows processed, exactly the 10 broken ones quarantined.*

### 3b. Pre-guessed answers (candidates) — logic

Every quarantined row gets an `ask` (plain-language question) and **candidates** — answers
the engine inferred deterministically, each with a basis and confidence:

- **Peer lead time**: the most common lead time for the same SKU at other stores —
  *"suggest 8 · used in 4 other stores for this SKU"*.
- **Number found in text**: `"7 days"` → *suggest 7*.
- **History-derived ADS**: last 4 weeks of the row's own sales columns ÷ 28 —
  *"suggest 3.2 · ≈ recent 4-week sales history"*.
- **Negative on-order** → *suggest 0 ("if nothing is actually in transit")*.
- **Duplicate** → *keep first* / *use this row's values*.

This is what makes the ask-back **one-tap**: the AI layer batches the questions by problem
type (≤ ~10 per run), presents candidate-first choices, writes the answers to an
`overrides.json` — `{"rows":[{"line":164,"set":{"lead_time":7}},{"line":362,"skip":true}]}`
— and **reruns the whole analysis**. The raw file is untouched; every override is
provenance-logged; an ADS override swinging more than ±50% is applied but flagged for
review. *Verified end-to-end: answering Priya's 10 gaps (9 from candidates, 2 typed) yields
360 processed / 0 quarantined / byte-identically reproducible.*

### 3c. The run verdict — logic

The **whole run** is graded before anything is trusted:

```
ambiguous column mapping        → DEGRADED  ("confirm before trusting")
> 20% of rows quarantined       → DEGRADED  ("fill the gaps and rerun")
> 60% of rows quarantined       → BLOCKED   ("do not act on this run")
otherwise                       → HEALTHY
```

Degraded runs carry a visible banner on the cockpit; blocked runs show no plan at all.
The never-guess rule, applied to files, not just cells. *(Priya: 10/361 = 2.8% → healthy.)*

---

## 4. The core math — five numbers and a ladder, per row

Worked on the **Chennai t-shirt**: stock 0, on-order 0, ADS 8/day, lead time 9 days
(and its Mumbai sibling: stock 300, ADS 12/day, lead time 4).

| Formula | In words | Chennai | Mumbai |
|---|---|---|---|
| **Pipeline** = stock + on-order | everything you have or have coming | 0 | 300 |
| **ROP** = ADS × lead time | the *danger line*: what you'll sell while a delivery travels — dip below it and you must act | 8×9 = **72** | 12×4 = **48** |
| **Buffer** = ROP × 1.5 | danger line + 50% cushion for bad luck (late trucks, demand wobble) | **108** | **72** |
| **Days of stock** = pipeline ÷ ADS | time until empty; sorts the action list. **null ("—") when ADS = 0** — never a fake zero | 0 | 25 |
| **Reorder qty** = (ADS × LT × 2.5) − pipeline, **only if the row is actionable**, rounded UP, min 0 | refill to 2.5 lead-times *when you order at all*. Healthy rows get **zero** — you order when you cross the danger line, that's the entire ToC discipline. Round up because 71.3 shirts can't be bought and rounding down shaves the cushion | **180** | 0 |

The **status ladder** — checked top-down, first match wins, order is load-bearing:

| # | Condition | Status | Plain reason (stored per row) |
|---|---|---|---|
| 1 | stock 0 and on-order 0 | ⚫ OUT OF STOCK | "losing sales now" |
| 2 | stock 0, on-order > 0 | 🟣 INCOMING | "SOH 0 but N in transit" |
| 3 | pipeline < ½ × ROP | 🔴 CRITICAL | "will stock out before replenishment lands" |
| 4 | pipeline < ROP | 🟡 REORDER | "order today" |
| 5 | stock > 2 × buffer | 🔵 OVERSTOCK | "capital tied up; transfer donor" |
| 6 | otherwise | 🟢 HEALTHY | "within buffer" |

Chennai stops at rule 1 (⚫). Mumbai passes 1–4, then 300 > 2×72 → 🔵, with surplus
300 − 72 = **228** above its buffer. The multipliers in words: *½ × ROP* = "below half the
danger line — even ordering today won't land in time"; *2 × buffer* = "double the
comfortable level — that's parked cash, not a cushion."

Any status the *file itself* claimed is ignored, recomputed, and disagreements are flagged
(32 found in Priya's file — how you discover a legacy system lies).

**Headline rates** (two, because they're opposite problems):
`Action rate` = ⚫🟣🔴🟡 share = **42.7%** (starving) · `Excess rate` = 🔵 share = **12.3%**
(frozen cash) · classic health (🟢 share) = **45.0%**, target ≥ 70%.

---

## 5. The demand module — is the file's sales rate even true?

The stated ADS is a **master number** someone typed long ago. If the file carries weekly
sales history (column name contains "sold"/"sale" + a number = *weeks ago*), the engine
tests it — correcting three distortions *before* comparing:

**Censoring (empty-shelf weeks).** A week with zero sales while the row is *currently out
of stock* is missing demand, not low demand — those weeks are excluded and confidence drops.
*Example: the Surat hoodie (stock 0) has weeks 28, 31, 34, 0, 0, 38, 41, 0 → the three zero
weeks are excluded; correction marked low confidence.*

**Promo weeks.** Weeks listed in `config.promo_weeks_ago` are excluded. A week towering
**> 2.5 × the median** of the others is flagged *suspected promo* — **never auto-excluded**;
Priya gets one question ("was the week of 28 Jul a promotion?"). *Example: the Surat white
tee sold 41, 43, 40, 42, **126**, 41, 44, 42 → week-4 flagged; unconfirmed it inflates the
rate to +51%; confirmed as promo, the deviation collapses and the correction disappears.*

**Volatility (CV).** `CV = standard deviation ÷ mean` of weekly sales — "how big are the
swings relative to a typical week". `CV < 0.25` steady · `< 0.6` variable · `≥ 0.6` jumpy.
For jumpy SKUs the engine uses the **median** week (not the mean — you can't chase an
average that doesn't exist) and recommends a bigger buffer factor (~2.0) instead of an ADS
change.

Then:

```
Actual ADS  = mean(last 4 usable weeks) ÷ 7        (or median of all usable ÷ 7 if CV ≥ 0.6)
Deviation   = (actual − stated) ÷ stated           → a correction is proposed when |dev| > 20%
Confidence  = high (≥6 usable weeks, CV<0.4, nothing excluded) / medium / low
```

*The flagship example: the Chandigarh hoodie — stated **2**/day, actual (34+40+42+44)÷28 =
**5.7**/day → **+186%, high confidence → "raise master ADS 2 → 6 (under-forecast)"**.
Same shelf of 12 units: at ADS 2 it reads 🟡 order-23; at the honest 6 it's 🔴 order-93.
One wrong master number was hiding a crisis and under-ordering four-fold.*

**The verify-first gate.** If deviation > +100% **and** the shelf holds more than 1.5× the
entire 8 weeks of claimed sales, the numbers contradict each other — stock that never moves
can't be selling 40/week. That row gets **"verify count first"**, no ADS proposal, and no
expensive recommendation. *Example: the Surat polo — "sells 5.8/day" yet 500 on the shelf →
flagged, exactly once, exactly there.* A confidently wrong transfer built on phantom stock
is the fastest way to lose an operator; this gate exists for that.

**Governance.** Corrections are **proposals**. They enter the math only two ways: Priya
approves and the run is redone with `--apply-ads-corrections` (low-confidence ones are
skipped; swings capped at ±50%; every application provenance-logged) — or she writes the
approved value into her master system herself. Nothing is applied silently, ever.

---

## 6. Rules and reality — before any recommendation

- **Sellable stock (ATP).** If the file tracks reserved (online orders) or damaged units,
  a donor's givable stock = `stock − reserved − damaged`. *Example: Thane shorts, stock 60,
  10 reserved + 2 damaged → 48 sellable, disclosed on the row.*
- **Policies** (from `.redpill/policies.json`) are hard constraints, each application
  disclosed in the report: *protected stores* never donate · *blocked lanes* never carry a
  transfer · *no-reorder SKUs* (clearance) get fresh orders suppressed.
- **Incoming risk.** An 🟣 INCOMING row isn't automatically safe — the engine grades the
  inbound: below the danger line → *"top-up order needed"*; below half of it → *"order more
  now"*; a known receipt date arriving later than the lead time → *"later than a fresh order
  would be"*; and rows with no receipt date carry one disclosed assumption ("inbound assumed
  to arrive within its lead time — lower confidence").
- **Overcommit flag.** A row whose *pipeline* exceeds 2 × buffer while the shelf looks
  normal is quietly drowning in inbound orders — flagged "trim the open order" while it
  still can be. *(Example: Surat tee — 40 on the shelf, 400 on trucks, reads 🟢 by the
  ladder; the flag catches what the ladder can't.)*

---

## 7. The plan — in money-saving order

### 7a. Transfers first (logic)

Per SKU, across stores:

```
Donor surplus   = sellable stock − buffer      (only 🔵 OVERSTOCK stores donate —
                                                and never below their own buffer, by construction)
Receiver need   = buffer − pipeline            (⚫🔴🟡 stores receive)
Transfer        = the smaller of the two, biggest need paired with biggest surplus first,
                  quantities decrementing until either side runs dry
```

*Worked: Mumbai surplus 228, Chennai need 108 → transfer **108** Mumbai → Chennai.*
Why first: a 2-day truck beats a 9-day supplier and costs no new money.

Each candidate transfer then passes the reality gates (each skip disclosed in
`transfer_notes`):
- **Lane-time gate** (`--transfer-days T`): a receiver whose *supplier* is faster than the
  truck orders fresh instead — *"JNS → Thane: supplier (2d) beats the truck (3d)"*.
- **Case packs**: quantities floor to whole shipping cartons; below one carton → skipped.
  *(27 needed, packs of 12 → send 24.)*
- **Policy lanes / protected donors** (§6).
- **Estimated saving** = transfer value × 15% — a stated, tunable assumption, and the value
  *moved* is reported separately from the value *saved*, always.
- **Transfer cost & net benefit**: give a per-unit cost (`--transfer-cost-per-unit`, or
  per-lane in policies `lane_costs`) and each transfer shows *cost = qty × rate* and
  *net benefit = saving − cost*. **Unknown cost stays null, never zero** — an honest unknown
  beats a fake number.
- Transfers on the same route are summarised per lane (`transfer_lanes`) for batching one
  weekly truck instead of five couriers.

*Priya's file: **83 transfers, ₹46.9L moved, ~₹7.04L estimated saving.***

### 7b. Fresh orders, net of transfers

```
Net order = reorder qty − units arriving by transfer      (floor 0)
Net order value = net qty × price                          (the number you'd actually spend)
Expected delivery = as-of date + lead time
```

*Chennai: 180 − 108 = order **72** (₹57,528, lands in 9 days).*
Totals cover **actionable rows only**: gross ₹1.63 cr → **net ₹1.16 cr** (and the ₹46.9L
gap between them exactly equals the transfer value — the numbers reconcile by construction).
With **`--budget`**, the order queue (most-urgent first) is cut into *within budget* /
*deferred* — visibly, never silently — and the two parts sum exactly to the net total.

### 7c. The urgency queue

Actionable rows needing a human move, sorted by days-of-stock ascending (file order breaks
ties — deterministic). Rows with *nothing to do* — like a dead-stock item that's out but has
zero demand — are excluded rather than clogging the top of the list.

### 7d. Mitigations — no dead-end red flags

An ⚫/🔴 row with no transfer inbound and supply arriving *after* the projected stockout gets
a named fallback: **"expedite, substitute, or hold remaining stock for full price."**
Verify-first rows get **"verify count first."** Every red flag comes with a next move.

---

## 8. The insight layers

- **ABC-XYZ classes.** ABC = revenue-rate contribution (ADS × price ranked; first 70%
  cumulative = A, to 90% = B, rest = C). XYZ = demand stability from CV (<0.25 X, <0.6 Y,
  else Z). An A-X basic and a C-Z long-tail item deserve different attention.
- **Weighted health** = share of daily *revenue* (not rows) sitting in 🟢 — the management
  view beside the operator's simple row-count rates. *(Priya: 45.0% of rows healthy but only
  46.1% of revenue-rate — her problems skew toward money-making SKUs.)*
- **Size-curve breaks.** Per store × style × colour: some sizes ⚫/🔴 while sibling sizes
  sit → a **broken rack** — customers who can't find their size don't buy the sizes that
  remain, so the stranded ones are effectively dead stock. *(10 breaks found in Priya's
  file, e.g. Denim Jacket Blue with M gone and L sitting.)*

---

## 9. What Priya actually sees

The renderer (`render_cockpit.py`) injects `report.json` into a **fixed template** —
identical layout every run, zero AI variance, no calculations of its own (a test proves the
template contains no business numbers). The **cockpit**:

- **Banner** if the run is degraded/blocked, with reasons.
- **KPI strip**: health (with the ≥70% target mark) · action rate · excess rate · net new
  order (labelled **potential**) · transfer saving (labelled **estimated**, beside the value
  moved) · freshness stamp · engine version.
- **Seven lenses over one list**: **Today's Actions** (default, urgency-ranked, never
  truncated) · By Store (worst health first) · Transfers (execute-first, per-pair value +
  saving) · Reorders (net of transfers, with the missing-price caveat when it applies) ·
  **Signal fixes** (stated → actual, deviation %, confidence, censoring/promo annotations,
  "requires your approval" reminder) · Overstock (the donors) · Quarantine (each row's
  reason + the suggested answers as chips). Plus search and status-count filter chips.
- **Click any row → the drawer**: status reason in plain words → recommended action (order
  n / receive n from X / donate to Y, with values and dates) → mitigation fallback if any →
  raw inputs → recomputed values → *this store's* signal fix → discrepancy vs the file's own
  status → data notes (every parse/override provenance line) → **what-if sliders** (drag
  ADS/lead-time/buffer-factor and watch this row's status recompute — labelled *"this row
  only — plan totals unchanged"*, because a row-slider must never leave stale network totals
  on screen).
- **Downloads**: plan CSV + transfers CSV, generated verbatim from the same report data.
- Footer: advisory-only statement, money-label legend, assumptions, report-an-issue link.
- Works in light and dark themes and on a phone (no horizontal scrolling, compact rows).

In chat, the AI layer gives only a **five-line brief** — verdict, the two rates, net order
(potential), savings (estimated), top-3 actions — plus any questions (promo confirmations,
correction approvals). Long markdown reports exist only on explicit request.

---

## 10. The paper trail — why every run can be trusted later

Every run directory contains: the **immutable copy** of the input file · `report.json`
(versioned schema — the single source of every displayed number) · `computed.csv` (with all
passthrough columns) · `quarantine.csv` (doubles as a fill-in form) · `summary.json`
(compat subset) · snapshots of config/overrides/mappings/policies used · and
`run-manifest.json` with SHA-256 hashes of everything.

`--rerun <run-dir>` replays the run from its own stored inputs and verifies the output is
**byte-identical**. Every transformed value carries provenance (raw → parsed → source column
→ overrides applied). Result: any number on the cockpit, any week later, can be traced to
the exact file, config, and engine version that produced it.

---

## 11. The guarantees (how we know all of the above is true)

- **53-test golden suite**, run by CI before every bundle build: the full Priya-file
  reference numbers pinned exactly (351/10 · status counts · 42.7/12.3/45.0 · ₹1.63 cr →
  ₹1.16 cr · 83 / ₹46.9L / ₹7.04L / 0 valueless · urgency top-3 · healthy verdict) ·
  property invariants (donors never dip below buffer, healthy rows never ordered, totals
  reconcile, nothing recommended from quarantined rows) · a **sha256-pinned snapshot** of
  the entire report (any behavior change breaks a test *on purpose*) · a schema-contract
  test (every field the cockpit reads must exist) · reproducibility · the shipped `.skill`
  bundle unzipped into a bare directory and run standalone · 12/12 storyline detections
  (chronic, volatile, censored, promo, verify-first, overcommit, size curves, lane gate,
  quarantine, duplicates, degraded runs).
- **Product boundary**: advisory only — recommends, never executes; no ERP writes, no PO
  submission, no messages, no cloud; order values *potential*, savings *estimated*, nothing
  *realised*. **Privacy**: stdlib Python, no network calls, no telemetry.

## 12. Every dial in one table

| Dial | Default | Meaning |
|---|---|---|
| Buffer factor | 1.5 (per-row overridable) | cushion above the danger line |
| Target factor | 2.5 | refill level when ordering |
| Critical line | ½ × ROP | "too deep to save by ordering" |
| Overstock line | 2 × buffer | "parked cash" |
| Deviation tolerance | ±20% | when a master ADS counts as wrong |
| Volatility threshold | CV 0.6 | when a SKU is "jumpy" (median + bigger buffer) |
| Suspected-promo trigger | > 2.5 × median week | flag for confirmation |
| Verify-first trigger | dev > +100% and stock > 1.5 × 8-wk sales | count before acting |
| ADS swing cap | ±50% | max applied correction/override per run |
| Transfer savings rate | 15% | stated estimate vs a fresh order |
| Transfer cost | off (opt-in per-unit / per-lane) | enables cost + net-benefit per transfer |
| Incoming risk lines | < ROP · < ½ROP · ETA > lead time | grades inbound stock |
| Lane time | off (opt-in `--transfer-days`) | truck-vs-supplier gate |
| Budget | off (opt-in `--budget`) | within/deferred split |
| Quarantine verdicts | >20% degraded · >60% blocked | run-level trust |

**The one-line summary:** *a stock file goes in; a deterministic engine refuses to guess,
asks with pre-filled answers, corrects the demand signal it can prove wrong, applies your
rules, runs five small formulas and one strict ladder over every row, moves stock before
buying stock, labels every rupee honestly, and hands back one identical-shaped cockpit page
whose every number can be traced, reproduced, and checked by hand.*
