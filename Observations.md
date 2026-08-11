# Red Pill — Dry-Run Observations & Fix Backlog

> **What this is.** A stress-test dry run of the Red Pill skill on a deliberately *ugly*
> synthetic MIS, logging everything worth fixing — engine defects, doc-vs-behavior gaps,
> model/metric design questions, and UX friction. Ordered by severity within each section.
> Every engine reference is `file:line` against `skills/redpill-inventory/scripts/redpill_engine.py`.
>
> **Run date:** 2026-08-10 · **Engine runtime:** 0.07s for 361 rows (fast, no crash).

---

## 0. The test harness (what was thrown at it)

- **Scale:** 30 SKUs × 12 stores = **360 rows** (+1 duplicate) in a raw weekly MIS.
- **Real-world-ugly headers:** `SKU Code`, `Outlet`, `Closing Stock`, `In Transit`,
  `Avg Off-take/Day`, `Lead Time (Days)`, `MRP`, `System Status`, `Sold W-8 … W-1`,
  plus British `Colour` and passthrough `Style/Category/Size/Supplier`.
- **10 intentionally broken rows:** negative SOH, `LT=0`, `LT="7 days"`, blank ADS, `ADS="abc"`,
  `SOH="N/A"`, negative QOO, blank store, duplicate SKU+Store, fractional `SOH=12.5`.
- **Number-format noise on valid rows:** thousands separator (`1,240`), currency symbol
  (`₹2,499`), whitespace padding (`  8 `), blank QOO.
- **Engineered storylines:** chronic under-forecast (Hooded Sweatshirt), volatile demand
  (Denim Jacket), dead stock `ADS=0` (Winter Scarf), real transfer pairs, and an `~8%`-wrong
  legacy `System Status` column to test discrepancy detection.

**Outcome:** 351 processed · 10 quarantined · health 45% · 83 transfers · ADS layer flagged 8 SKUs.
Everything ran; the findings below are about *correctness, honesty of the numbers, and friction* —
not about it falling over.

---

## 1. Engine defects (fix these — they silently corrupt the numbers)

### 🔴 B1. Unit price with a currency symbol is silently dropped → blank order/transfer value, understated savings, **no warning**
- **Where:** `fnum()` `:95-99` strips commas but not `₹`/symbols/stray text. Price flows through
  `:199` → `None`; `order_value` becomes `""` (`:55`); transfer `value`/`est_saving` become `None`
  (`:79-84`) and are **excluded from `total_transfer_savings`** (`:282`).
- **Seen this run:** `JNS-SLM-IND-32 / Mumbai` had `₹2,499`. Result: its `order_value` blank, and
  **2 transfers from that donor reported no value** — savings understated with zero disclosure.
- **Why it matters:** blank QOO gets an assumption logged (`:207`), but a *present-but-unparseable
  price* is dropped **silently**. A user sees blank rupees and can't tell if it's "free" or "broken".
- **Fix options:** (a) in `fnum`, strip leading currency symbols / non-numeric prefix before
  `float()`; and/or (b) when a non-empty price fails to parse, push a `warnings`/`assumptions`
  entry (`"price '₹2,499' unreadable → order/transfer value omitted"`).

### 🔴 B2. `order_value` is **gross**, never net of transfers → totals overstate spend
- **Where:** `compute_row` sets `order_value = reorder_qty × price` (`:55`) using **gross**
  `reorder_qty`. `reorder_qty_net` is only computed later in `build_transfers` (`:89`) and there is
  **no `order_value_net`**.
- **Seen this run:** 74 rows were transfer-netted, yet summing engine `order_value` gives
  **₹2.20 cr** vs the true net **₹1.73 cr** — a **~₹47L overstatement** if anyone trusts the column.
  The report had to recompute `reorder_qty_net × price` by hand.
- **Fix:** emit `order_value_net` (and/or a `total_order_value_net` in `summary.json`) so the report
  doesn't silently double-count units already covered by a transfer.

### 🟠 B3. Built-in column aliases are too narrow → a real raw MIS fails hard on ingest
- **Where:** alias maps `:165-171`; header normalization `:157` only does lower / trim /
  space→`_` / dash→`_` (keeps `(`, `)`, `/`).
- **Seen this run:** piping the raw file returned
  `Missing required columns: ['ads', 'lead_time']` because `Avg Off-take/Day` → `avg_off_take/day`
  (alias is only exact `offtake`) and `Lead Time (Days)` → `lead_time_(days)`.
- **Contradiction:** `SKILL.md:34` lists **"Avg Off-take"** as an example it maps intelligently, and
  the README/handoff tell users to **"run the engine directly"** on their file — but these common
  headers bounce.
- **Fix:** in header normalization, also strip `()`/`/`/`.` and collapse to alnum+`_`; broaden
  aliases (`off_take`, `avg_off_take`, `lead_time_days`, `leadtime_days`). Keep the graceful
  template fallback it already has.

### 🟡 B4. Passthrough columns are **not** passed through to `computed.csv` (doc says they are)
- **Where:** `out_fields` is a fixed 15-column list written with `extrasaction="ignore"`
  (`:261-268`), so `style/category/colour/size/supplier/reported_status/sold_w*` are **dropped**.
- **Contradiction:** handoff §5 / README say *"extra columns pass through untouched."* They don't.
- **Consequences downstream (all hit this run):**
  1. Report can't show product attributes (style/colour/size) without re-joining the raw input.
  2. **Discrepancy detection** vs the file's own status column is impossible from engine output
     alone (had to re-join `reported_status` — found **32/351** mismatches).
  3. **ADS correction** needs `sold_w*`, also dropped — the AI layer must re-read the raw file.
- **Fix:** carry unmapped input columns through to `computed.csv`, or write a `passthrough.csv`
  keyed by `(sku, store)`. This is the single change that most reduces model re-work (see UX-1).

---

## 2. Model / metric design (judgment calls currently left implicit)

### 🟠 M1. Transfers have no geography or transfer-cost awareness
- Pairing is per-SKU greedy on surplus/deficit only (`build_transfers :59-92`). This run proposed
  e.g. **Kolkata → Kochi, 56 units** and **Kochi → Delhi, 74 units** — cross-country moves treated
  as equivalent to same-city ones. Real transfer cost/lead-time can exceed the modeled saving.
- **Consider:** an optional distance/zone or per-lane cost input; at minimum, document that
  transfers assume intra-network moves are cheap and fast.

### 🟠 M2. Flat 15% savings rate produces eye-catching but unverified rupee "savings"
- `est_saving = value × 0.15` uniformly (`:84`). Large-value lanes (a ₹2.2L blazer transfer) yield a
  headline "₹33k saved" that isn't grounded in anything lane-specific. Fine as an illustrative
  default — but the report should label it *estimated / illustrative*, and the rate ideally scales
  with the lead-time gap avoided.

### 🟡 M3. ADS-correction window is a model judgment call, unstable for volatile SKUs
- The skill picks the trailing window; on volatile SKUs (Denim Jacket, CV 0.6–0.8) a 4-week **mean**
  swung **−37% to +73%** across stores. The report worked around it by using **median across
  stores**, but nothing in `formulas.md` encodes "use median / longer window when CV is high."
- **Fix:** codify it — `CV > 0.6` → use median and/or a longer window before recommending an ADS change.

### 🟡 M4. Corrections don't scale as a per-row table
- Raw ADS-deviation hits **113 SKU-store rows** (>20%). `report-template.md §3c` shows a per-row
  table — unusable at this volume. The report rolled them up to **8 SKU families**; that roll-up
  rule should be explicit in the skill, not improvised.

### 🟡 M5. Health score conflates "needs action" with "capital tied up"
- `Health = OPTIMAL / total` (`:271`) counts OVERSTOCK (43 rows here) against health the same as
  OUT_OF_STOCK. A store full of excess reads as "unhealthy" identically to one that's starved.
- **Consider:** report two rates — an **action rate** (out/incoming/critical/reorder) and an
  **excess rate** (overstock) — so 45% doesn't blur two very different problems.

---

## 3. Minor / cosmetic

- **C1. Fractional SOH accepted silently.** `SOH=12.5` processed with no flag (`fnum` returns a
  float). Physical unit stock should be integer — consider warning on non-integer SOH/QOO.
- **C2. Inconsistent "empty" `order_value`.** `0.0` for zero-reorder rows vs `""` for missing-price
  rows — trips naive downstream parsing. Pick one sentinel.
- **C3. Quarantine reason wording.** A row with a valid SKU but blank store still reads
  `"blank sku/store"` (`:190`). Name the actual empty field.
- **C4. `expected_delivery` — correct.** `today (2026-08-10) + LT` computed right (`:242`). ✅

---

## 4. Experience / workflow observations

### UX-1. Assembling the Final Report is entirely the model's job, and it re-derives engine work
- The engine emits `computed.csv` + `summary.json`; everything a human actually reads — discrepancy
  section, ADS corrections, net order value, product attributes, store-health ranking, exec summary
  prose — is re-computed by the model from re-joined raw data. This is the main source of run-to-run
  variance and token cost. A **richer `summary.json`** (net order-value totals, per-store health,
  discrepancy inputs) or a thin **`--report` mode** would cut model work and stabilize output.

### UX-2. The engine cannot ingest a real MIS unaided — the skill/human normalization step is mandatory
- Raw file → engine failed on headers (B3). In practice the model *must* rename columns first. That's
  fine, but README/handoff frame the engine as directly runnable ("run it on your file"); it should
  say plainly that non-canonical headers require the skill's mapping pass (or fix B3).

### UX-3. Quarantine + fill-in-form UX is a genuine strength — keep it
- All 10 bad rows got a **precise, actionable, per-row reason**, valid rows still produced a full
  (clearly-marked-partial) report, and the quarantine file doubles as a pre-filled correction form.
  This is the best-feeling part of the run and matches the "never silently guess" invariant exactly.

### UX-4. The two headline rupee numbers need a confidence caveat in the exec summary
- "₹6.87L saved" and "₹1.73cr net order" are the numbers an operator will screenshot. Given B1
  (dropped prices), M1/M2 (transfer realism), they should carry a one-line "estimated; excludes N
  rows with unreadable prices" note so they're not over-trusted.

---

## 5. Prioritized fix list

| # | Sev | Item | Effort |
|---|---|---|---|
| B1 | 🔴 | Currency-symbol price dropped silently — parse it or warn | S |
| B2 | 🔴 | `order_value` gross, not net — emit `order_value_net` / net total | S |
| B4 | 🟡 | Carry passthrough columns into engine output (unblocks attributes, discrepancies, ADS) | M |
| B3 | 🟠 | Broaden header normalization + aliases so real MIS headers map | S–M |
| M3/M4 | 🟡 | Encode ADS window/median-on-volatile + SKU-level roll-up rules in the skill | M |
| M1/M2 | 🟠 | Document (or model) transfer geography/cost + label savings as estimated | M |
| M5 | 🟡 | Split health into action-rate vs excess-rate | S |
| UX-1 | 🟡 | Richer `summary.json` (net totals, store health, discrepancy inputs) or `--report` mode | M |
| C1–C3 | ⚪ | Integer-stock warning, consistent empty sentinel, precise quarantine wording | S |

---

## 5b. Cockpit mock dry run (interactive output preview)

Built a clickable HTML cockpit from the stress data (`.tmp/stress-run/redpill_cockpit.html`) to
pressure-test the proposed output UX before Phase 1. What it validated and surfaced:

- **Validated:** KPI strip with the action-rate/excess-rate split (M5) reads well; the single
  list + lens toggle (Action queue · By store · Transfers · Reorders · Signal fixes · Overstock ·
  Quarantine) holds 351 rows without a wall of tables; the per-SKU drawer (reason → recommended
  action → inputs → recomputed values → signal/discrepancy notes) is the right drill-down. Search,
  status-chip filters, and CSV export all work.
- **AV1 (fixed in mock):** row grid had 5 children in 4 columns → the order-qty cell wrapped to a
  second line. Lesson for Phase 1: lock the row template to explicit columns and test at 350+ rows.
- **AV2 (fixed in mock):** OUT-OF-STOCK status color `#1A1A1A` is invisible on the dark ground —
  the *most urgent* status vanished. Phase 1 must give `--s-out` a legible dark-theme value while
  keeping the six-status semantics; audit every semantic color on both grounds.
- **AV3 (design note):** brand red collides conceptually with CRITICAL red — resolved by reserving a
  deep oxblood/crimson for chrome only and always labeling status chips. Carry this rule into the
  bundled template so restyles don't reintroduce the clash.
- **Data-contract confirmation:** the mock needed per-row attributes, recomputed values, plain-text
  status reason, net order value, discrepancy inputs, transfers in/out, and ADS-by-SKU — i.e. exactly
  the `report.json` Phase 0 will emit. Building the mock first de-risked that schema.

---

## 5c. Self-audit of the dry run (mistakes in MY output, found on re-verification)

A deliberate audit pass over the run's own numbers found four genuine issues — three mine, one
engine-design ambiguity. Ranked:

- **R1 (🔴, mine + spec ambiguity): the headline "net new order ₹1.73cr" is inflated ~49%.**
  The engine computes a refill-to-target `reorder_qty` for *every* row — including 🟢 OPTIMAL rows
  sitting between ROP and target (147 such rows here). SKILL.md's replenishment plan is defined as
  **actionable rows only** (out/incoming/critical/reorder). My report and the cockpit KPI summed
  net order value over ALL rows: ₹1.73cr, of which **₹56.7L is top-up orders for perfectly healthy
  rows**. Correct actionable-only figure: **₹1.16cr**. The cockpit "Reorders" lens has the same
  scope bug (294 rows shown vs 150 actionable). ToC-wise, a row that hasn't hit its reorder point
  shouldn't trigger an order at all. **Fixes:** (a) engine should emit `reorder_qty = 0` (or a
  separate `topup_qty`) for non-actionable rows, or the report layer must filter; (b) Phase 0's
  `report.json` must carry the actionable-only total so this is decided once, in one place.
  *This error is the strongest possible argument for D1/UX-1 (engine-owned report.json): it
  happened precisely because the model re-derived a total the engine should own.*
- **R2 (🟡, mine): ADS-correction table is internally inconsistent.** SKU-level rows aggregate by
  median across stores, then display the stated median with `:.0f` — so `SWT-HOD-GRY-M` printed
  "stated 2 → actual 6.2, +149%", but 2 → 6.2 implies +212%; the +149% was computed on the
  unrounded median stated 2.5. Displayed numbers must be the ones the percentage was computed from.
- **R3 (🟡, mine): the cockpit drawer presents the SKU-level aggregate correction as if it were
  store-specific.** Chandigarh's drawer says "stated 2 vs actual 6.2 (+149%)"; Chandigarh's own
  actual is 5.7 (+186%). Drawer should show the per-store correction (or label the figure
  "across 12 stores").
- **R4 (⚪, engine, latent): dead-stock rows can occupy urgency slots.** An ADS=0 out-of-stock row
  has days-of-stock 0 and reorder 0 — "most urgent, nothing to do." None leaked into this run's
  top-10, but the sort guarantees they'd sit at the top of the full urgency table. Exclude
  reorder_net=0 rows from urgency ranking.
- **R5 (⚪, engine, latent): duplicate handling is order-dependent.** If the *first* copy of a
  duplicated SKU+store row is quarantined, the second is processed silently with no duplicate
  flag (`seen` is only updated on valid rows). Not triggered in this data.
- **(minor, presentation): the three explainers quoted +149% / +186% / +200% for the same hoodie
  story** — each defensible (SKU median / per-store / rounded teaching numbers) but they should
  be reconciled to one figure with its basis stated.

---

## 6. Reproduce this run

Artifacts live in `.tmp/stress-run/` (git-ignored):

```bash
cd .tmp/stress-run
python3 gen_stress_mis.py          # -> stress_mis_raw.{csv,xlsx}  (seed=7, deterministic)
# raw -> engine fails on headers (B3):
python3 ../../skills/redpill-inventory/scripts/redpill_engine.py stress_mis_raw.csv
# skill maps headers -> normalized_mis.csv, then:
python3 ../../skills/redpill-inventory/scripts/redpill_engine.py normalized_mis.csv \
        --out computed.csv --summary summary.json --gaps data_gaps.csv
python3 build_report.py            # -> final_report.md
```


---

## 7. Phase 0 entry audit (G1–G35 current state, per SPEC §5)

Evidence file: `skills/redpill-inventory/scripts/redpill_engine.py` (engine, "E:"), repo root.
Statuses: ✅ done · 🟠 partial · ❌ missing · ⚠ differs from SPEC.

| Gap | State | Evidence |
|---|---|---|
| G1 currency parsing + warn | ❌ | E:95-99 `fnum` strips commas only; silent None |
| G2 actionable-only ordering | ⚠ | E:34 computes reorder for every row |
| G3 engine-owned net values | ⚠ | E:55 order_value uses gross qty; no net total anywhere |
| G4 header aliases | 🟠 | E:157-171 alias map too narrow (`offtake` exact only; `( ) /` kept) |
| G5 passthrough columns | ❌ | E:261-265 fixed 15-col output, `extrasaction="ignore"` |
| G6 report.json (versioned) | ❌ | only ad-hoc `summary.json`; no schema/version |
| G7 run verdict + freshness | ❌ | no run-level check; no as-of stamp |
| G8 urgency/dup/int/sentinel/ADS-0 | 🟠 | quarantine wording good; dup order-dependent (E:186-193,238); days=0 for ADS=0 (E:33); `""` vs `0.0` sentinel mix (E:55) |
| G9 stress gen v2 | 🟠 | v1 generator exists, git-ignored in .tmp/, lacks the 6 new storyline rows |
| G10–G11 cockpit | 🟠 | mock exists (scratch), not template-from-report.json |
| G12–G14 onboarding/ask-back | ❌ | Phase 2 |
| G15 SKILL rewrite | ❌ | Phase 3 (current SKILL.md describes old pipeline) |
| G16 namespaced commands | ❌ | no commands/ dir (verified) |
| G17 docs/positioning/privacy | ❌ | Phase 3 |
| G18–G29 model realism | ❌ | Phase 4 |
| G30 test hardening | ❌ | no tests/ dir exists |
| G31 boundary block | 🟠 | in SPEC §0; not yet in README/SKILL (Phase 3 docs) |
| G32 run dirs/reproducibility/provenance | ❌ | engine writes loose files in cwd |
| G33 mapping confidence (+memory P2) | ❌ | mapping silent; no classes |
| G34–G35 ETA-inbound / transfer economics | ❌ | Phase 4 / 1+4 |

**Phase 0 will change:** `skills/redpill-inventory/scripts/redpill_engine.py` (rewrite to v2),
new `tests/` (generator v2 fixture + golden + property tests), `references/formulas.md` (corrected
ordering rule, ADS-0 convention, report.json note). **Tested by:** golden assertions on the SPEC §1
reference numbers + property invariants + reproducibility re-run.

---

## 8. Phase 0 exit record (2026-08-11)

**Shipped:** engine v2 (`redpill_engine.py`, ENGINE_VERSION 2.0.0 / SCHEMA_VERSION 2.0.0)
closing G1–G5, G7, G8, G32 and the confidence half of G33; committed stress generator
(`tests/fixtures/gen_stress_mis.py`) with v1 **byte-identical** to the original dry-run file
(verified by diff) + 6 new deterministic storyline rows in `stress_mis_v2.csv` (G9); test suite
(`tests/test_engine.py`, 23 tests — goldens pinning every SPEC §1 reference number exactly,
property invariants, reproducibility, blocked-run, parsing units). Makefile `test` now runs the
suite; CI gates the bundle rebuild on it; `formulas.md` synced to the corrected rules;
`.gitignore` covers new artifacts; `dist/` bundle rebuilt.

**Dry-run result:** all 23 tests green — 351/10 split, exact status counts, 45.0/42.7/12.3
rates, ₹1.63 cr gross → ₹1.16 cr net (actionable-only), 83 transfers ₹46,91,490 moved /
₹7,03,723.50 est. saving / 0 valueless, urgency top-3 exact, verdict *healthy*,
`--rerun` reproducibility MATCH.

**New findings this phase:** none blocking. Two notes for later phases: (a) engine still writes
loose artifacts to cwd in legacy (no `--run-dir`) mode — fine for compatibility, cockpit flow
(Phase 1) should always pass `--run-dir`; (b) `summary.json` is now a strict subset of
`report.json` kept for compatibility — retire it in Phase 3 when SKILL.md is rewritten.

**Gate:** Phase 0 exit criteria met (zero known engine defects; every §2 stage's data present in
`report.json`). Phase 1 (cockpit template) may start.


---

## 9. Phase 1 exit record (2026-08-11)

**Shipped:** `assets/cockpit_template.html` (fixed template, ~zero variance) +
`scripts/render_cockpit.py` (stdlib injector, validates JSON before injecting) closing **G10**
and **G11**. The cockpit renders exclusively from `report.json` — verified by test: the template
contains no business constants, and the embedded blob is asserted equal to the engine's report.
Features: run-verdict banner (degraded/blocked), "Today's Actions" default lens, the two-rate KPI
strip, **estimated/potential money labels** (G35's display half: "₹7.0L estimated · ₹46.9L
moved" are separate figures), per-row drawer with decision trace (inputs → computed → reason →
action → data notes), discrepancy chip (string-compare only vs the file's own status column),
empty-states for all lenses (Signal fixes honestly says it's not populated yet), plan + transfers
CSV export, and **row-level what-if sliders** labeled "this row only — plan totals unchanged"
(the G11 staleness constraint honored by scope).

**QA performed:** functional JS audit (all 7 lenses, drawer, sliders, search/filters — clean, no
NaN/undefined in output); visual: dark desktop, light desktop, mobile 375px (no horizontal
overflow, compact 3-col rows, drawer fits). One defect found and fixed in-phase: **AV4 — the
5-KPI grid left an empty tinted cell on mobile** (last KPI now spans the row).

**UX eval (three <10s questions):** "what do I do first?" → top of Today's Actions on load ✓;
"why this row?" → one tap, reason sentence first ✓; "what's the total spend?" → KPI strip,
labeled *potential* ✓.

**Tests:** suite grew to 26 (renderer: placeholder replaced, blob === report, labels present,
no hard-coded plan numbers in template). All green. Bundle rebuilt with template + renderer.

**Gate:** Phase 1 exit criteria met. Phase 2 (native onboarding & ask-back) may start.
