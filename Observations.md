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


---

## 10. Phase 2 exit record (2026-08-11)

**Shipped (G13, G14, G33-memory, engine 2.1.0 / schema 2.1.0):**
- **Candidate inference** — every quarantined row now carries `ask` (plain-language question)
  and `candidates` (deterministic pre-guessed answers with basis + confidence): peer lead times
  ("used in N other stores"), numbers extracted from text ("7 days" → 7), ADS derived from the
  file's own sales history, qoo→0, duplicate-resolution options.
- **Overrides mechanism** — `--overrides overrides.json` (`rows[].set/skip` + `mappings`):
  answers merge onto the immutable input, the whole analysis reruns, every override is
  provenance-logged per row and counted in `run.overrides_applied`. Run dirs copy the overrides
  file; the manifest hashes it; `--rerun` reproduces override runs identically.
- **Mapping memory** — `--mappings mappings.json`: user-confirmed header→target maps applied
  with confidence `user_confirmed` (tested with a fully alien header set).
- **ADS governance cap** — an override swinging ADS >±50% (`--max-ads-swing`) is applied but
  flagged for review; master-data changes remain propose-and-approve only (protocol in SKILL).
- **SKILL.md Step 1.5 rewritten** to the v2 elicitation protocol (batch by type, ≤10 questions,
  numbered-chat baseline + native cards as enhancement, overrides.json + full rerun, never edit
  the raw file); Steps 3/5 synced to engine v2 + cockpit-always. Cockpit quarantine lens now
  shows the suggested answers as chips.

**Dry run (the closed loop, automated):** stress v1 with *no* manual cleaning → 10 quarantined
with 9 inferred candidate values → overrides built from the engine's own candidates (simulating
card taps; 2 values "typed" where nothing could be inferred: a counted shelf and a store name)
→ rerun → **360 processed / 0 quarantined / verdict healthy / reproducibility MATCH**.
Question-batching eval: 10 gaps collapse into **6 question groups** (3 lead-time, 2 ADS,
2 stock, 1 qoo, 1 store, 1 duplicate) — under the ≤10 cap. Candidate chips verified rendering
in the cockpit ("suggest 7 · number found in '7 days'").

**Tests:** 26 → **30**, all green. Bundle rebuilt.

**Notes for Phase 3:** G12 (the `/redpill:setup` card flow) is protocol + a stored config the
engine already accepts (`--config`); it ships with the commands in Phase 3 where it belongs.

**Gate:** Phase 2 exit criteria met — a fresh user's messy file closes its gap entirely via
question-answers, no raw-Excel editing. Phase 3 (contract, commands, docs) may start.


---

## 11. Phase 3 exit record (2026-08-11)

**Shipped (G15, G16, G17, G31 + the G12 protocol):**
- **`commands/`** — the five namespaced plugin commands (`/redpill:run`, `:setup`,
  `:template`, `:policies`, `:explain`), each a bounded prompt that enforces the contract
  (engine computes, cockpit always, advisory-only, report.json-verbatim numbers).
  `/redpill:setup` implements G12 as protocol: five skippable questions → `.redpill/config.json`
  + `.redpill/policies.json`, nothing written unconfirmed.
- **SKILL.md fully rewritten** — leads with seven Non-negotiables (no LLM arithmetic,
  cockpit-every-run, immutable raw file, never-guess, money labels, advisory-only,
  approval-gated master data), then the operational workflow wired to engine v2
  (`--run-dir .redpill/runs/<as-of>`, verdict triage, Step 1.5 elicitation, five-line chat
  brief), plus explicit error handling. Step 4 honestly marks demand commentary as
  model-side-until-Phase-4 with hard guardrails.
- **README rewritten** — outcome-first ("stock dump in → approved-ready plan out"), the §0
  product boundary + privacy statement (no network calls, no telemetry), first-run guide,
  file requirements, standalone-engine usage, integration ladder (files first), an honest
  known-limitations list, dev/test instructions, troubleshooting. CONTRIBUTING gains the two
  standing rules; report-template.md marked on-request-only. Plugin version → 2.0.0.

**Dry run / evals:**
- **Bundle cold-start (automated):** `dist/redpill-inventory.skill` unzipped into a bare temp
  dir runs engine + renderer on the bundled example with stdlib only — self-containment proven
  in-suite. Command files validated (frontmatter + description).
- Docs accuracy pass: every command/flag/file named in README + SKILL now exists and was
  exercised by the suite this phase.
- **Manual item (logged, not self-testable in this session):** live trigger-phrasing eval —
  five natural phrasings ("run red pill", "stock health check", etc.) against a fresh install
  in a clean Claude Code session. To be run on the next real-user session; SKILL description
  unchanged from the version that triggered reliably in earlier sessions.

**Tests:** 30 → **32**, all green. Bundle rebuilt.

**Gate:** Phase 3 exit criteria met to the extent verifiable in-session; the trigger eval is
queued as the first item of the next live session. Phase 4 (model realism v1.5) may start.


---

## 12. Phase 4 exit record (2026-08-11) — model realism v1.5

**Shipped (engine 2.2.0 / schema 2.2.0), all golden-safe (v1 reference numbers unchanged):**
- **Demand module in the engine** (G18/G19/G29): weekly history parsed (week number = weeks
  ago), stockout-censoring (zero-sale weeks excluded when currently OOS, confidence lowered),
  promo weeks excluded via config + *suspected* promo spikes flagged for confirmation (never
  auto-excluded), CV volatility, median-not-mean for volatile SKUs, confidence scores, and
  plain-language correction proposals. **Verify-first gate** (G23/G50): stock-vs-sales
  contradictions get "verify count first" and no ADS proposal.
- **Governed application** (G14): corrections are proposals; `--apply-ads-corrections`
  applies non-low-confidence ones capped at ±max-ads-swing, provenance-logged.
- **Realism gates** (G22/G24/G25/G26): lane-time gate with disclosure ("supplier 2d beats the
  truck 3d — order fresh"), case-pack rounding, policy enforcement (protected stores, blocked
  lanes, no-reorder clearance SKUs), sellable-stock (ATP) donor math, overcommit flag,
  transfer-lane batching summary.
- **G23 budget split** (within/deferred by urgency, reconciles to net order value),
  **G28 mitigations** (expedite/substitute/hold when supply lands after stockout),
  **G20 ABC-XYZ + weighted health** second view, **G21 size-curve breaks** (10 found in the
  fixture — broken racks with stranded sibling sizes).
- **Cockpit**: Signal-fixes lens is now real (stated→actual, dev%, confidence, censoring/promo
  annotations, approval reminder); drawer shows the per-store correction (R3 honored) and
  mitigation fallbacks.
- Docs synced: formulas.md v1.5 appendix, SKILL Step 4 rewritten (engine-owned corrections,
  approval protocol), README limitations updated honestly.

**Dry run / eval — the 12-storyline harness (SPEC §5 Phase 4 exit):**
chronic under-forecast proposed (+186% high conf, "2 → 6") ✓ · volatile→median+buffer advice
(16 SKU-stores, all CV≥0.6) ✓ · dead stock→donor (Phase 0) ✓ · censored weeks excluded (3, low
conf) ✓ · promo excluded on confirm (correction disappears with config) ✓ · broken size curves
(10) ✓ · overcommit flagged (1, the engineered row) ✓ · implausible row gated to count-first
(exactly 1, no ADS proposal) ✓ · transfer gates honored with disclosure ✓ · all 10 quarantine
reasons (Phase 0) ✓ · duplicate both orders (Phase 0 rule) ✓ · degraded/blocked banner
(Phase 0 verdicts) ✓. **12/12.**

**Tests:** 32 → **46**, all green (one in-phase test fix: CV rounding boundary — assertion
matched to report precision). Bundle rebuilt.

**Gate:** Phase 4 exit criteria met. Remaining for Phase 5: golden-per-storyline freeze,
sample workbook into examples/, README screenshots, release.


---

## 13. Phase 5 exit record (2026-08-11) — hardening & release

**Shipped (G30):**
- **Frozen snapshot golden**: the full v1 `report.json` is sha256-pinned in the suite — any
  behavior change now breaks a test *by design* (change SPEC + pin together, with a reason).
- **Schema contract test**: every field the cockpit reads (report/kpis/row/run level) is
  asserted present — the build fails if the contract drifts.
- **Sample workbook shipped**: `examples/RedPill_Sample_MIS_Apparel.xlsx` + its deterministic
  generator (seed 42), README download line added.
- **CHANGELOG.md** created (1.0.0 → 2.0.0 "the honest cockpit").
- **Feedback loop**: cockpit footer links to the repo's issues; run verdict + warnings were
  already user-visible per run.
- Test suite final count: **48, all green.**

**Final build gate (SPEC §5, ten points): ALL PASS** — deterministic+reproducible ·
reference figures exact · every surface reconciles to report.json · complete decision traces ·
no silent risky recommendations · local mapping/override persistence · first-run path with
zero raw-Excel edits · advisory-only stated on the page · full test/golden/schema/artifact QA ·
docs match observed behavior.

**Deferred (logged, honest):** README cockpit *screenshots* (needs a manual capture session);
the live five-phrasing trigger eval (first item of the next real-user session); optional
submission to the Anthropic plugin directory.

**The SPEC gap register G1–G35 is now closed** for everything scoped v1/v1.5. Remaining gaps
are the deliberate v2/fork-shelf items (roadmap.md §3b–3c): historical replay, run-diff mode,
DC node, lifecycle rules, substitution — plus the commercial cluster behind the paid-pilot
gate. Red Pill v2.0.0 is release-ready.


---

## 14. Post-release errata (found writing HOW-IT-WORKS.md, 2026-08-11)

Documenting the build end-to-end surfaced two gap-register overstatements in §13's
"G1–G35 closed" claim:

- **G34 — partial.** The `expected_receipt_date` column is parsed and carried (schema hedge),
  but the INCOMING sufficiency/lateness risk flag ("is the inbound enough, and will it arrive
  in time?") was never implemented. Open item → next minor release.
- **G35 — partial.** Value *moved* vs value *saved* are separated everywhere (engine +
  cockpit labels), but per-lane estimated transfer cost and net-benefit fields don't exist.
  Open item → pairs naturally with lane costs when a user supplies them.

Neither affects any shipped number's correctness; both are absence-of-feature, disclosed in
README's limitations by implication. Gap register status: **33 closed, 2 partial.**


---

## 15. Partials closed (2026-08-11, engine 2.3.0 / plugin 2.0.1)

- **G34 closed**: INCOMING rows graded for sufficiency (inbound < ROP → "top-up needed";
  < ½ROP → "order more now") and lateness (parsed `expected_receipt_date` beyond lead time →
  "later than a fresh order would be"; unreadable dates flagged); rows without a date roll up
  into one disclosed run assumption. `kpis.incoming_risk_count`; risks surface in row
  warnings/drawer.
- **G35 closed**: per-transfer `est_transfer_cost` (flat `--transfer-cost-per-unit` or
  per-lane `policies.lane_costs [[from,to,cost]]`) and `net_benefit` = saving − cost; unknown
  cost stays **null, never zero** (an honest unknown beats a fake number); totals in
  `kpis.transfers`; cockpit transfer cards render cost/net when known.
- Snapshot golden intentionally broke and was re-pinned with the reason in the same commit —
  the freeze discipline working exactly as designed. Suite: 48 → **53 green**.
- **Gap register final: G1–G35 all closed.**


---

## 16. Cockpit Claude-UI restyle (2026-08-12, plugin 2.0.2)

User-approved restyle of the cockpit template to Claude's design language. **Style layer
only** — markup, JS, and behavior byte-compatible; renderer tests unchanged and green (53).
Tokens matched to claude.ai's shipped web design system (the referenced community Figma file
is view-only, so the Figma MCP could not export values — the file's token tables visibly
mirror the shipped tokens; a pixel-match pass is possible if the user duplicates the file to
an editable copy). Additions: pixel-block RED PILL wordmark (inline SVG, theme-aware,
accessible label), and a persistent light/dark toggle (data-theme override + localStorage,
presentation-only). QA: both themes, toggle both directions + persistence, drawer/lenses/
what-if functional, production-rendered output verified in-browser.


---

## 17. Batch-6 triage + timing-honesty release (2026-08-14, engine 2.4.0 / plugin 2.1.0)

A second 66-point external review (same source as batches 1–5) was triaged **against the
running 2.3.0 build, not the spec**. Verdict: ~26 points already built or "keep"
confirmations, 8 genuinely new (adopted as G36–G38), ~26 parked onto the existing shelf,
~6 rejected as core-disturbing or fake precision. Full record: roadmap.md §3d. Notable:
the list's one "critical defect" claim (stated-ADS-0 division by zero) was **false** —
the guard existed; it is now pinned by a test so it can never silently regress.

Shipped (user approved the A–E batch before build):
- **G36 timing honesty** — `current_cover` vs `days_of_stock` (pipeline cover) split;
  per-row `projected_stockout_date` (ETA-aware; no-ETA arrival assumed at LT, disclosed;
  overdue receipt dates warned, treated as landing now); `stockout_before_inbound_days`
  gap flag; transfers carry `receiver_dry_before_arrival_days` under `--transfer-days`
  (flagged, never blocked). Stress fixture: **23 rows** go dark before inbound lands —
  several OPTIMAL-by-pipeline (e.g. TSH-CRW-WHT-L Pune, cover 5.1d, dry 0.9d early);
  the exact blind spot the reviewer predicted, invisible until this release.
- **G37 financial impact (estimated only)** — `daily_revenue_at_risk = ADS × price`
  (OOS/CRITICAL), `capital_tied_up = (SOH − buffer) × price` (overstock);
  `kpis.financial_impact`; null when price missing. Stress: ₹4,96,507/day at risk,
  ₹77,53,955 tied up. Sample workbook: ₹2,22,257/day, ₹39,79,488, 12 dry-before-inbound.
- **G38 assumptions & policies** — policy thresholds became named engine constants
  (math and disclosure share one definition, cannot drift); one consolidated
  `assumptions_and_policies` report section; cockpit **Assumptions** lens (policy cards
  + applications + assumptions); formulas.md glossary typing every statement
  (formula / model estimate / policy / assumption) + classical-vocabulary map
  (our ROP ≡ lead-time demand; Buffer ≡ protection level; BF = safety-stock policy).
- Cockpit additions: 6th KPI card (₹ at risk/day), "Rank by ₹ at risk" toggle on
  Today's Actions, per-row ₹/d in the pen bar, capital total on Overstock lens,
  too-late warning on transfer cards, drawer shows shelf-vs-pipeline cover + projected
  dry date + timing-gap note; Plan CSV gains 4 columns. Verified via headless-Chrome
  screenshots (action lens value-ranked; Assumptions lens) — renders clean, both lenses.
- **Rejected on purpose** (guarding the core): `ROP = LTD + SS` restructure (identical
  arithmetic — delivered as glossary instead, zero golden churn), day-by-day simulation
  (one aggregate QOO cannot honestly support it), donor future-demand forecasting,
  ATP-for-statuses (parked as possible config flag).
- Dry runs: stress v1 351/10, all §1 reference figures byte-identical (health 45.0%,
  net ₹1,16,40,751, 83 transfers); sample workbook 197 rows, prior figures unchanged.
  Snapshot golden intentionally broke; re-pinned with reason in the same change.
  Suite **53 → 62 green**, incl. new edge-case pins (stated-ADS-0, reserved > SOH,
  past-ETA overdue, cover invariants, financial reconciliation, null-price honesty).
- Self-caught during test design (not in the reviewer's list): a past-due
  `expected_receipt_date` on an open PO was silently treated as on-time comfort — now
  warned as "inbound overdue" and projected as landing today at earliest.
- UI refinement after user review of the artifacts: (a) the action-queue sort chips
  restyled as a subtle secondary segmented control (they visually competed with the lens
  pills); (b) the two CSV buttons merged into one "↓ Download CSV" button with a
  Drive-style dropdown (Plan CSV / Transfers CSV, with one-line descriptions; closes on
  choose / outside click / Esc). Template-only; suite stays 62 green; verified live
  (menu open/choose/close, sort toggle, dark theme).


---

## 18. S-track Phase S0 — Shopify adapter truth (2026-08-14, G39/G40)

S-track opened (user-approved; SPEC-SHOPIFY.md is canonical, roadmap §3e records the
strategy). S0 delivers the intake swap's foundation with the engine untouched:

- `scripts/shopify_snapshot.py` — stdlib adapter: Shopify Bulk-Operation JSONL →
  `shopify_mis.csv` (the exact engine contract) + `pull-manifest.json` (API version,
  query sha-256, pulled_at, counts, artifact checksums) + `adapter-provenance.json`
  (every column → its API path). Replay mode only; live mode deliberately lands with
  S3 validation — both share one normalizer by design.
- `tests/fixtures/gen_shopify_fixture.py` — deterministic Bulk JSONL storyline:
  3 locations × 8 active tracked variants = 24 rows; all six statuses; 3 transfers;
  blank-SKU (×3), missing-lead-time (×6), negative-count (×1) analogs; 1 archived +
  1 untracked variant skipped **with counts**.
- Policy proven by the dry run: adapter never guesses — bad rows pass through and the
  UNCHANGED engine quarantines them (24 → 14 processed / 10 quarantined, verdict
  honestly DEGRADED at 41.7% quarantine). ATP consumed committed+reserved (donor
  sellable 106 of 120). The Delhi incoming row exercised G34+G36 on connector data:
  receipt 2026-08-24 > LT 7 → "later than a fresh order" + 10-day dark-shelf gap.
  Transfers matched the designed storyline exactly (18/8/9 units, Mumbai donating).
- Lead time confirmed as THE missing Shopify input: metafield → vendor default
  (`leadtimes.json`) → quarantine + ask-back. Jogger rows produced the ask correctly;
  vendor-sibling candidates are S2 scope.
- Suite 62 → **79 green** (17 adapter tests: CSV golden sha-pinned, byte-identical
  rerun, manifest contract, provenance coverage, skip counts, pass-through analogs,
  vendor defaults, receipt-only-with-inbound, and 8 engine-integration assertions).
  Engine goldens untouched — the S-track adds beside, never inside.


---

## 19. Domain stress pack — the messy-MIS gauntlet (2026-08-17, engine 2.4.1)

User asked for messy MIS sheets for every retail domain the setup question serves —
varied SKUs, medium-to-many stores, mostly-right data with a few planted problems —
so anyone can stress-test the pipeline on data shaped like their own. Shipped as
`examples/stress/` (8 domain files + 25k-row mega mix + corrupted refusal demo),
generated deterministically by `gen_stress_pack.py`: ~92% clean rows, traps on fixed
row schedules, a different header dialect / SKU convention / store count (8 → 50)
per file. Grocery & pharmacy deliberately absent (SPEC §0 non-goals).

The dry run did its job — it broke things:

- **Mapper tie-break bug (real)**: `item` was an *exact* sku alias while
  `product_code` was only *high*, so home & decor's generic `Item` name column beat
  its `product_code` column → SKU = product name → 735/849 rows (86%) falsely
  quarantined as duplicates, verdict BLOCKED. Fixed by promoting `product_code` to
  exact; the file now runs DEGRADED with the honest disclosure "1 ambiguous column
  mapping — confirm before trusting" (`product_code` chosen, `Item` listed) and 8.2%
  quarantine — the disclosure itself is now the file's storyline.
- **Alias gaps (real)**: `ISBN/SKU`, `Design Code`, `Showroom`, `Incoming`,
  `Tag Price` — all common trade headers — hard-failed the mapping. Added as 2.4.1
  aliases. `Value` deliberately NOT added as a price alias (in real MIS files it
  usually means stock *value*, qty × price — guessing it would be wrong-guess
  behavior); the jewellery generator uses `Tag Price` instead.
- **Golden discipline held**: engine 2.4.0 → 2.4.1 broke the frozen-report sha on
  purpose; re-pinned with reason after proving the report byte-identical modulo the
  version string — zero business figures moved. Suite 79 green; pack regenerates
  byte-identical (two-run diff).
- Balance verified per file: HEALTHY verdicts at ~8% quarantine (beauty 17.4% — all
  planted-trap fallout, reasons audited from quarantine.csv), corrupted file refuses
  with mapping report + fill-in template, mega mix (25,258 rows) in ~2.6 s.
- Engine also confirmed to write `data_gaps.csv` / `redpill_input_template.csv` into
  the CWD on bare runs (no `--run-dir`) — noted as a future wart, not fixed here.
  **Closed in 2.4.2 (§20).**


---

## 20. CWD-pollution wart closed (2026-08-17, engine 2.4.2 / plugin 2.1.2)

The §19 wart, fixed: one `aux_out_path()` rule sends side outputs (`data_gaps.csv`,
blocked-run `redpill_input_template.csv`) next to `--out` — falling back to
`--report` — whenever either carries a directory, so a run pointed at another
directory never drops files into the caller's CWD. Bare defaults (no directory
anywhere) keep the old CWD behavior; an explicit `--gaps` path is always honored;
`--rerun`'s `os.devnull` sinks are excluded as anchors. Under `--run-dir` nothing
moves except the blocked-run template, which now lands inside the run dir — it was
the one file that still leaked to the CWD even in run-dir mode.

Discipline held: golden intentionally broke on the version string; re-pinned after
proving the report byte-identical modulo `"version"` (normalized sha matched the
2.4.1 pin exactly — zero business figures moved). Suite 79 → **81 green**: two new
placement pins (gap file next to `--out`; blocked-run template next to `--report`),
each also asserting the caller's CWD stays empty.
