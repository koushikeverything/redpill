# Red Pill — Canonical Scenario & Build Basis (SPEC)

> **What this document is.** The single agreed description of how Red Pill works when finished —
> logically consistent, verified by simulation, and the basis every future fix and phase is built
> against. It consolidates [Observations.md](Observations.md) (all dry-run defects incl. the
> self-audit), [roadmap.md](roadmap.md) (the 63-suggestion triage), and the current build.
> **It supersedes PLAN.md's phasing** (PLAN.md retained for history).
>
> Every number in the walkthrough was produced by re-running the 361-row stress MIS through the
> corrected rules (simulation script: `.tmp/stress-run/` — see §7). Nothing here is aspirational
> arithmetic.

---

## 0. Product boundary & non-goals (non-negotiable)

Red Pill is a **local inventory-planning and decision-support plugin**. It accepts
retailer-provided MIS files, validates them, computes explainable recommendations, asks for
missing information, and generates execution-ready artifacts. **All recommendations are
advisory.** It does **not**: modify ERP/POS/WMS data · submit purchase orders · dispatch or
receive transfers · send messages (WhatsApp/email/Slack) · claim *realised* savings or cash
released · require cloud storage, integrations, or cross-customer data. Explicit non-goals
(create nothing, not even placeholders): live inventory sync, PO submission, transfer
dispatch/receipt workflow, cloud/multi-tenant anything, login/RBAC/billing, cross-run outcome
attribution, probabilistic forecasting, multi-echelon optimisation, verticals beyond
apparel/lifestyle, autonomous execution of any kind.

**The architecture invariant behind everything:** deterministic code is the source of truth for
parsing, validation, math, statuses, transfers, ordering, totals, and report generation.
**Claude never computes or re-derives a business number** — it orchestrates, asks bounded
questions, and explains structured engine output. Every number a user sees originates in the
engine's `report.json`. (This rule was earned, not theorized: the one material error in the dry
run — the ₹1.73 cr inflation, finding R1 — happened exactly where the model re-derived a total
the engine should own.) The raw uploaded MIS is immutable; every run is reproducible from
raw file + config + session overrides + engine version.

---

## 1. Verified reference numbers (old run vs corrected rules, same input file)

| Measure | Old dry run (buggy) | Corrected rules | Why it changed |
|---|---|---|---|
| Rows processed / quarantined | 351 / 10 | 351 / 10 | unchanged — quarantine was already right |
| Status counts & 45% health | ⚫24 🟣17 🔴47 🟡62 🔵43 🟢158 | identical | the 6-status ladder was never wrong |
| Action rate / excess rate | 42.7% / 12.3% | identical | split metric confirmed |
| **Net new order value** | **₹1.73 cr (inflated)** | **₹1.16 cr** | R1/S1: orders only for actionable rows |
| Gross before transfers | ₹2.20 cr (all rows) | ₹1.63 cr (actionable) | same scope fix |
| Transfers | 83, ₹45.8L moved, ₹6.87L saved, 2 valueless | 83, **₹46.9L moved, ₹7.04L saved, 0 valueless** | B1: `₹2,499` now parses |
| Dead-stock rows in urgency | possible | excluded | R4 |
| Hoodie Chandigarh correction | shown +149% (SKU aggregate) | **+186% (per-store)** | R2/R3 display rules |

---

## 2. The end-to-end scenario (the "finished product" walkthrough)

*Terms are defined at first use. The worked example is an apparel chain: 30 SKUs × 12 stores.*

**Cast:** Priya, planning head of a 12-store Indian apparel chain. Every Sunday night her
point-of-sale system emails her the **MIS report** — "Management Information System" report,
i.e. the routine stock Excel: one row per **SKU** (stock-keeping unit — one exact product
variant, e.g. *black crew-neck t-shirt, size M*) per store.

### Stage 0 — One-time setup (`/redpill:setup`, ~3 minutes, done once)

Claude walks Priya through native selection cards (single-select, multi-select, short text —
never a form to fill offline):

1. *"What kind of retail?"* → *Apparel / lifestyle* (single-select) — sets vocabulary and enables
   size-curve analysis.
2. *"Currency?"* → ₹ (single-select with Other).
3. *"Which of these does your stock file track?"* → multi-select: *reserved online stock ·
   damaged stock · supplier · case-pack size · promotions* — so the engine knows what it may use
   and what to disclose as assumed.
4. *"Business rules I should never break?"* → multi-select seeded with common ones (*never drain
   the flagship store · no transfers between certain cities · clearance items get no fresh
   orders*) plus free text. Saved to a plain `policies` config, applied every run, each
   application disclosed.
5. *"Weekly purchase budget, if any?"* → text field (skippable).

Everything is stored in the project (a config the skill reads each run); `/redpill:setup` re-opens
it any time. **Nothing here is required** — a user who skips setup gets sensible defaults and
slightly more questions later.

### Stage 1 — Trigger

Monday 9 AM: Priya attaches `MIS_11Aug.xlsx` and types **`/redpill:run`** (or just "run red pill on
this"). One contract, every run, no variation: *the output is the interactive cockpit page +
approvals; long markdown reports only on explicit request.*

### Stage 2 — Reading the file as it actually is

- **Header mapping.** Real headers (`Closing Stock`, `Avg Off-take/Day`, `Outlet`, `MRP`,
  `Lead Time (Days)`) map automatically — normalization strips punctuation and knows retail
  aliases. If a column is genuinely ambiguous, ONE native card asks: *"Does 'Stk Qty' mean stock
  on hand?"* [Yes / It's something else / Ignore column]. The mapping used is always disclosed.
- **Value parsing.** `1,240` → 1240; `₹2,499` → 2499; `"  8 "` → 8; blank on-order → 0
  (disclosed). A value that *still* can't be read is never silently dropped — it either
  quarantines the row or (for optional fields like price) is disclosed as a warning.
- **Freshness.** The run is stamped *"data as of Sun 10 Aug, 8 PM"*; a stale file triggers a
  visible warning. Red Pill never implies real-time.

### Stage 3 — Trust, checked at three levels

1. **Cell level.** Rows with unusable required values (blank sales rate, missing lead time,
   `N/A` stock, negatives, duplicates) are **quarantined** — set aside with a per-row reason.
   The iron rule: *a blank is not a zero.* All other rows continue. (Verified: the stress file's
   10 bad rows → exactly 10 quarantines, 0 false catches.)
2. **Plausibility level.** Rows that parse but can't be true — e.g. "sold 40/week for 8 weeks"
   while stock never moved — are flagged, and any **expensive recommendation on them is replaced
   by "physically count this shelf first."** A confident transfer built on phantom stock is the
   fastest way to lose an operator's trust; this gate exists for that.
3. **Run level.** If the file as a whole is suspect (too many quarantines, ambiguous mapping,
   stale snapshot), the entire output carries a **"degraded run — verify before acting"** banner,
   or Red Pill declines with reasons. The never-guess rule applies to runs, not just rows.

### Stage 4 — Missing info: asked natively, with the answer pre-guessed

For each quarantined row, Red Pill infers a candidate from Priya's own data, then asks with
one-tap cards, batched by problem type (all missing lead times together, capped per run so it
never becomes an interrogation):

> *"Oxford Shirt takes 7 days in your 10 other stores. Use 7 for Kolkata?"*
> **[ Use 7 ] [ Different number… ] [ Skip row ]**

Free values keep a text path; nothing is applied without a tap; answered rows are merged and the
**whole analysis re-runs** — corrections are never patched into stale output.

### Stage 5 — The honest sales rate

Each row's stated **ADS** ("average daily sales" — the master number typed into the system long
ago) is tested against recent weekly sales, with three distortions corrected *before* comparing:

- **Empty-shelf weeks don't count** (stockout censoring): Chennai's t-shirt "sold only 46" the
  week its shelf was empty half the time — that's missing demand, not low demand.
- **Promo weeks don't count** (unless the promo continues): one card asks *"Week of 28 Jul spiked
  3× — was that a promotion?"* [Yes, exclude / No, real demand].
- **Jumpy products use the median, not the mean**, and get a bigger cushion instead of a chased
  average. Jumpiness is measured by **CV** ("coefficient of variation" = how big weekly swings
  are relative to the average week; CV > 0.6 = volatile).

Result, per row: an honest rate + a **confidence level** (8 steady weeks ≫ 3 noisy ones). Then
the governance split — **today's math silently uses the honest rate (capped swing per run); the
master record changes only by approval card:**

> *"Hooded Sweatshirt, Chandigarh: file says 2/day; last 4 weeks say 5.7/day (+186%), climbing
> steadily, high confidence. Update master to 6?"* **[ Approve ] [ Reject ] [ All 12 stores… ]**

### Stage 6 — What's actually usable, and your rules

- **Sellable stock** = shelf stock − reserved-for-online − damaged (when those columns exist;
  when they don't, the report states "shelf stock treated as fully sellable").
- **Policies** from Stage 0 are applied as hard constraints, each application disclosed.
- The catalog is auto-classed **ABC×XYZ** (A/B/C = revenue contribution; X/Y/Z = demand
  stability via CV) and classes tune the dials — an A-X basic gets tighter protection than a C-Z
  long-tail item.

### Stage 7 — The math (all of it)

Per row, five numbers (worked on the Chennai t-shirt: rate 8/day, lead time 9 days):

| Formula | Chennai | Meaning |
|---|---|---|
| **Pipeline** = shelf + on-order | 0 | all you have or have coming |
| **ROP** = rate × lead time | 72 | the danger line: what you'll sell while a delivery travels |
| **Buffer** = ROP × 1.5 | 108 | danger line + 50% cushion for bad luck |
| **Days of stock** = pipeline ÷ rate | 0 | time until empty; sorts the action list |
| **Order qty** = (rate × LT × 2.5) − pipeline, **only if the row is actionable**, round UP, min 0 | 180 | refill to 2.5 lead-times when you do order |

The bolded clause is the corrected rule (fix S1): rows that haven't hit their danger line get
**no order** — previously a "top-up" was computed for healthy rows too, which inflated the total
plan by 49% (₹1.73 cr vs the true ₹1.16 cr). You order when you cross the reorder point; that's
the whole ToC discipline.

The **status ladder** (checked top-down, first match wins — order is load-bearing):

1. ⚫ **Out of stock** — shelf 0, nothing coming (losing sales *now*)
2. 🟣 **Incoming** — shelf 0, delivery en route (watch; don't double-order)
3. 🔴 **Critical** — pipeline < ½ × ROP (will run dry before any order lands)
4. 🟡 **Reorder** — pipeline < ROP (order today, still time)
5. 🔵 **Overstock** — shelf > 2 × buffer (frozen cash; a transfer *donor*)
6. 🟢 **Healthy** — none of the above

Plus one flag outside the ladder: **over-committed** (pipeline > 2 × buffer while the shelf looks
normal — an inbound order about to bury the store; catch it while the order can be trimmed).

Headline metrics: **Action rate** (⚫🟣🔴🟡 share — starving) and **Excess rate** (🔵 share —
frozen cash), reported separately because they are opposite problems. Stress file: 42.7% / 12.3%.
Any verdict already written *in the file* is ignored and recomputed; disagreements are flagged
(32 found in the stress file — that's how you learn your legacy system lies).

### Stage 8 — The plan, in money-saving order

**8a. Transfers first.** Within each SKU: overstocked stores give (never below their own buffer
— guaranteed by construction: givable = sellable shelf − buffer), starving stores receive
(need = buffer − pipeline), quantity = the smaller of the two, biggest need paired with biggest
surplus first. Each candidate passes real-world gates: the truck must beat the supplier lead
time; quantities round to whole **case-packs** (shipping boxes); small moves on one lane are
**batched** into one weekly truck; lane cost sanity-checked. *Estimated* saving = value × 15%
(a stated, tunable assumption). Stress file: **83 transfers, ₹46.9L moved, ~₹7.04L saved.**

**8b. Fresh orders, net of transfers.** Chennai needed 180, receives 108 from Mumbai → order
**72** (₹57,528, arriving in 9 days). Ranked by days-of-stock (who dies first, acts first);
rows with nothing to order don't occupy urgency slots. With a budget, the queue is cut into
*within budget* / *deferred* — visibly, never silently. Stress file: **₹1.63 cr gross → ₹1.16 cr
net** (transfers avoided ₹46.9L of buying — and note the cross-check: that equals the transfer
value moved, as it must when donor and receiver share a price).

**8c. When nothing arrives in time:** the row still gets a *named* fallback — expedite,
substitute, hold remaining stock for full price, or escalate. No dead-end red flags.

**8d. Apparel-specific: broken size runs.** Styles are analyzed as families: "M and L sold out,
S and XL stranded" = a broken rack customers walk past; the stranded sizes are flagged as
effective dead stock and size-level moves recommended.

**8e. Master-data fixes** from Stage 5 ride along as approval cards — fixing causes while
transfers fix symptoms.

### Stage 9 — What Priya sees (every run, identical shape)

One interactive page (the **cockpit**), rendered from a single machine-produced data file
(`report.json`) so its structure never varies:

- **Top strip:** action rate · excess rate · net order ₹ · transfer savings · freshness stamp ·
  the run-quality verdict from Stage 3.
- **"Today's Actions"** — the default list, most urgent first, never truncated; other lenses one
  tap away (By Store / Transfers / Orders / Signal Fixes / Overstock / Quarantine); search and
  status filters.
- **Click any row → the decision trace:** file values → corrections applied → the five numbers →
  the verdict in plain words → the action, with *this store's* figures (never a cross-store
  aggregate presented as local). Every % shown is computed from the numbers displayed beside it.
- **What-if sliders:** drag lead time 7→14 or demand +30%, statuses recompute live.
- Every ₹ labeled **estimated** (modelled effect) or **potential** (unexecuted queue) — never
  claimed as banked cash.
- **Download:** the full plan as CSV for whoever executes it.

Priya taps through ~6 approval cards, downloads the transfer list for her ops WhatsApp group,
and is done in about 15 minutes. Next Sunday, the loop repeats — and the corrected master
numbers she approved make next week's run smarter.

---

## 3. The user-experience map (diagram + commands)

*(A visual version of this diagram is published as an artifact; ASCII master below.)*

```
             ┌──────────────────────── ONE-TIME (3 min) ────────────────────────┐
             │                                                                  │
  Install    │   /redpill:setup                                                 │
  /plugin ─▶ │   ┌─ card: retail type (single-select)                           │
  install    │   ├─ card: currency (single-select + other)                      │
  redpill    │   ├─ card: which fields your file tracks (multi-select)          │
             │   ├─ card: business rules to never break (multi-select + text)   │
             │   └─ card: weekly budget (text, skippable)   → saved profile     │
             └──────────────────────────────┬───────────────────────────────────┘
                                            ▼
      ┌──────────────────────────── WEEKLY LOOP ────────────────────────────────┐
      │                                                                         │
      │  POS exports MIS ─▶ attach file + /redpill                              │
      │                                                                         │
      │  CLAUDE: map headers ──ambiguous?──▶ card: "Does 'Stk Qty' = stock?"    │
      │  CLAUDE: parse, stamp freshness, 3-level trust check                    │
      │        │                                                                │
      │        ├─ bad rows ──▶ ask-back cards (batched, pre-guessed answers)    │
      │        │               "Use 7-day lead time for Kolkata?" [Use 7|Other] │
      │        ├─ fishy rows ─▶ "count this shelf first" (no risky recs)        │
      │        └─ bad file ───▶ DEGRADED banner or decline with reasons         │
      │                                                                         │
      │  CLAUDE: honest sales rate ──spike?──▶ card: "Was W-3 a promo?"         │
      │  CLAUDE: policies + sellable stock + ABC-XYZ classes                    │
      │  CLAUDE: 5 formulas → 6-status ladder → plan (transfers→orders→fixes)   │
      │        ▼                                                                │
      │  COCKPIT artifact (always):  Today's Actions · lenses · drawer trace    │
      │        │                     · what-if sliders · run verdict · CSV ⬇    │
      │        ▼                                                                │
      │  USER: approval cards ── master-ADS fixes [Approve|Reject|All stores]   │
      │        ▼                                                                │
      │  Execute: transfer list → ops team · PO list → purchasing               │
      │        └────────────────── next week ──────────────────────────────────┘
      └─────────────────────────────────────────────────────────────────────────┘

  Anytime:  /redpill:template  → blank MIS with one example row
            /redpill:policies  → view/edit rules via cards
            /redpill:explain   → "why did you recommend X?" plain-language trace
```

**Slash commands (plugin):**

| Command | Does | Native-UI moments inside |
|---|---|---|
| `/redpill:run` | Runs the analysis on the attached / most recent MIS (plain "run red pill" also triggers via the skill). Strict contract: cockpit artifact every time. | mapping-confirm cards · ask-back cards · promo cards · ADS approval cards |
| `/redpill:setup` | First-run onboarding, or revisit any answer later. | 5 cards: type, currency, tracked fields, rules, budget |
| `/redpill:template` | Emits a blank MIS template (xlsx/csv) with one worked example row and column meanings. | none |
| `/redpill:policies` | Shows current rules; add/remove via cards. | multi-select + free text |
| `/redpill:explain` | Explains the model, or one specific recommendation's decision trace, in plain words. | none |

**Where native cards are used (and where they aren't):** cards handle every *bounded* choice
(confirm an inferred value, approve a change, pick from options — as in Claude's standard
single/multi-select prompt UI, always with an "Other/skip" escape). Genuinely free values
(an arbitrary lead time nobody can infer) use the card's text path. The **guaranteed baseline
is plain numbered choices in chat** — it works on every surface; native cards are progressive
enhancement on top, and an interactive form artifact covers multi-answer batches — same
questions, same never-guess rule either way.

---

## 4. Gap register — current build → this scenario

Everything that must change, consolidated from Observations.md (B/C/R/M/AV/UX) and roadmap.md
(#n), deduplicated, each mapped to a phase. **This is the authoritative fix list.**

| ID | Fix | Source | Phase |
|---|---|---|---|
| G1 | Parse currency/format noise in prices; warn (never silently drop) on unparseable | B1 | 0 |
| G2 | Orders only for actionable rows (`reorder=0` otherwise); actionable-only totals | R1/S1 | 0 |
| G3 | `order_value_net` + net totals emitted by engine, not re-derived by model | B2, UX-1 | 0 |
| G4 | Broaden header normalization + aliases (real MIS ingests unaided) | B3, UX-2 | 0 |
| G5 | Pass through all input columns (attributes, sales history, reported status) | B4 | 0 |
| G6 | Rich `report.json`: KPIs (both rates), per-row trace fields, per-store ADS data, discrepancy inputs, quarantine+candidates, freshness, run verdict, schema hedges (`node`,`channel`,`reserved_qty`,`damaged_qty`,`lifecycle`,`case_pack`) | UX-1, D1, #16/19/13/52 | 0 |
| G7 | Run-level data-quality verdict (quarantine %, mapping confidence, staleness) | #55, #40 | 0 |
| G8 | Urgency excludes nothing-to-do rows; duplicate handling made deterministic and documented (incl. quarantined-first case); integer-stock warning; consistent empty sentinel; precise quarantine wording; **ADS=0 ⇒ days-of-stock is null/"—", never 0** | R4, R5, C1–C3, batch-5 | 0 |
| G9 | Stress generator v2: add overcommit row, censored-sales row, implausible row, case-pack + reserved/damaged columns, promo spike, lane-gate case | self-audit gaps | 0 |
| G10 | Cockpit from fixed template + report.json; "Today's Actions"; two-rate KPI; degraded banner; estimated/potential labels; per-store drawer figures; %-from-displayed-numbers rule; explicit row grid; dark-legible status colors; CSV export | Phase-1 set, R2, R3, AV1–3, #45/62, GS | 1 |
| G11 | What-if sliders — **row-level only, or a full engine recompute; the page must never display stale network-wide transfer/order totals** | #20, batch-5 | 1 |
| G12 | Setup flow (`/redpill:setup`) via native cards → stored profile | onboarding | 2 |
| G13 | Ask-back via cards with inferred candidates, batched + capped; mapping-confirm card; merge→full rerun. **Baseline is numbered chat choices (works everywhere); native cards are progressive enhancement — never the sole path** | Phase-2 set, UX-3, batch-5 | 2 |
| G14 | ADS governance: run-rate cap, master-change approval cards, per-store basis | #7, R3 | 2 |
| G15 | SKILL.md rewrite: strict cockpit contract, pipeline order, elicitation protocol | Phase-3 set | 3 |
| G16 | Namespaced plugin commands (`/redpill:run` ·`:setup` ·`:template` ·`:policies` ·`:explain`) in `commands/` per plugin convention | this SPEC, batch-5 | 3 |
| G17 | Docs: outcome positioning, product boundary + non-goals (§0), apparel-first, integration ladder, **offline/privacy statement (no network calls, no telemetry, files never leave the machine)** | #32/35/43/15/12, batch-5 | 3 |
| G18 | Promo-week flags/calendar-lite (operationalize what formulas.md promises) | #18 | 4 |
| G19 | Stockout-censored ADS + confidence scores | #1 | 4 |
| G20 | ABC-XYZ classes driving per-segment dials + weighted-health second view | #22, #5, #6, #2 | 4 |
| G21 | Size-curve / style-family intelligence | #21 | 4 |
| G22 | Transfer realism: lane-time gate, case-packs, batching, lane economics; donor-QOO config flag | #3, #57 | 4 |
| G23 | Plausibility checks → verify-first gate on high-value recs | #26, #50 | 4 |
| G24 | Overcommit flag | #4 | 4 |
| G25 | Policy config applied + disclosed (`/redpill:policies`) | #41 | 4 |
| G26 | Sellable-stock (ATP) math when reserved/damaged present | #52 | 4 |
| G27 | Budget cap → within-budget/deferred split | #23 | 4 |
| G28 | Mitigation actions (expedite/substitute/hold/escalate) | GS | 4 |
| G29 | Median-for-volatile + SKU-family rollup rules codified in formulas.md | M3, M4 | 4 |
| G30 | Test hardening: per-storyline goldens **asserting traces/statuses/actions, not just totals**; property tests for invariants (no negative orders, donors never dip below buffer, case-pack multiples respected, totals reconcile, no action from a quarantined row); versioned `report.json` schema with validation that fails the build; deterministic snapshot tests (controlled timestamps); cold-start tests (5 phrasings + commands); anonymised real-file fixtures pipeline; release checklist; sample workbook shipped | Phase-5 set, batch-5 | 5 || G31 | Product boundary + non-goals block (§0) surfaced in README and SKILL.md; every recommendation labelled advisory | batch-5, #35 | 0 (docs 3) |
| G32 | **Run directories + reproducibility + provenance**: each run stores an immutable copy of the raw MIS, config/mapping/overrides snapshots, engine version, all artifacts (`report.json`, cockpit, CSVs) and a `run-manifest.json`; a rerun-from-directory command reproduces identical output (timestamps aside); every transformed field carries raw value → parsed value → source column → warnings/overrides applied. Session answers write to `overrides.json`; the raw file is never touched | batch-5 | 0 |
| G33 | Mapping confidence classes in `report.json` (exact / high-confidence / ambiguous / unmapped / user-confirmed) + project-local **mapping memory** — confirmed mappings saved per source pattern, reviewable, low-confidence never applied silently | batch-5 | 0 (memory: 2) |
| G34 | ETA-aware inbound stock: use `expected_receipt_date` when present (else disclose the assumption + lower confidence); add an INCOMING companion risk flag — *inbound covers near-term demand* vs *insufficient/late* | batch-5 | 4 |
| G35 | Transfer economics as separate figures: value moved · estimated purchase deferral · estimated transfer cost (if known) · estimated net benefit — **inventory value moved is never labelled "savings"** | batch-5, #45/62 | 1 + 4 |

---

## 5. Build plan v2 (supersedes PLAN.md phasing)

Every phase ends the same way: **dry run on the stress file → findings appended to
Observations.md → fixed → re-run clean → gate passed.** No phase starts while the previous
phase's findings are open.

### Phase 0 — Engine truth & the data contract  *(G1–G9, G31–G33)*

**Entry step (before any change):** a current-state audit of every gap G1–G35 —
`done / partial / missing / differs from SPEC`, with file evidence — plus the exact files to
change and the test for each. No implementation until that table exists.
The engine becomes the single source of every number. All correctness fixes, the corrected
ordering rule, `report.json`, run verdict, stress-generator v2.
**Dry run/eval:** stress v2 through the engine; assert the §1 reference numbers exactly; golden
`report.json` frozen. **Exit:** zero known engine defects; every §2 stage has its data available
in `report.json`.

### Phase 1 — The cockpit  *(G10–G11)*
Fixed HTML template rendering `report.json`. All display-honesty rules (per-store figures,
%-from-shown-numbers, labels, banner).
**UI check:** browser screenshots — light/dark/mobile at 350+ rows; drawer + all lenses clicked
through; focus states; no horizontal page scroll. **UX eval:** 3 tasks answerable in <10s each
from the page: "what do I do first?", "why this row?", "what's the total spend?". **Exit:** all
three pass + zero rendering defects logged open.

### Phase 2 — Native onboarding & ask-back  *(G12–G14)*
Setup cards, inferred-candidate ask-back, ADS approval cards, merge-and-rerun.
**Dry run:** the messy stress file with *no* manual pre-cleaning — the entire gap must close via
cards alone. **Evals:** ≤10 cards per run (batching works); every inferred candidate correct or
safely skippable; Cowork/chat fallback renders. **Exit:** a fresh user reaches a complete run
without ever editing a table by hand.

### Phase 3 — Contract, commands, docs  *(G15–G17)*
SKILL.md rewrite, the five commands, positioning docs, rebuilt plugin bundle.
**Dry run:** cold start as a brand-new user (fresh session): install → setup → run, five
different trigger phrasings; artifact-always verified each time. **Exit:** cold-start success
without author intervention; docs match observed behavior exactly.

### Phase 4 — Model realism (v1.5)  *(G18–G29, in value÷effort order)*
Ship in clusters, each with its own engineered eval case added to stress v2:
promo (G18) → censoring+confidence (G19) → segmentation (G20) → size curves (G21) → transfer
realism (G22) → verify-gate (G23) → overcommit (G24) → policies (G25) → ATP (G26) → budget (G27)
→ mitigations (G28) → codified rules (G29).
**Eval harness (all must pass to exit):** the 12 storyline detections — chronic under-forecast
proposed · volatile→bigger-buffer · dead stock→donor · censored weeks excluded · promo excluded
on confirm · broken size curve flagged · overcommit flagged · implausible row gated to
"count first" · transfer passes all gates · all 10 quarantine reasons caught · duplicate caught
both orders · degraded-run banner on a mass-broken file.

### Phase 5 — Hardening & release  *(G30)*
Golden regression suite, sample workbook into `examples/`, README with cockpit screenshots,
version bump, publish; optional Anthropic directory submission.
**Final build gate (all ten must hold before "ready"):** (1) a messy MIS produces deterministic,
reproducible output; (2) the §1 reference figures match exactly; (3) every cockpit and CSV number
reconciles to `report.json`; (4) every recommendation has a complete decision trace; (5) no
missing/invalid/ambiguous/low-trust input can silently create a risky recommendation; (6) mappings
and overrides survive future runs locally; (7) a first-time user completes setup → run → questions
→ cockpit → downloads without ever editing raw Excel; (8) the product states plainly that it
recommends but does not execute; (9) full tests + goldens + schema + artifact QA pass; (10) docs
describe observed behaviour, not aspirations.

**Feedback loop (standing):** every run's verdict + a "report an issue" pointer in the cockpit
footer; user-reported files become new stress cases; Observations.md remains the living defect
log; roadmap.md governs anything new (incl. the SaaS fork gates — paid pilots before any
persistent-platform work).

---

## 6. What deliberately does NOT change

The five formulas, the six-status ladder and its evaluation order, transfers-before-orders,
round-up-never-down, recompute-everything-trust-nothing, quarantine-never-guess. Every fix in
§4 is about honest inputs, honest constraints, and honest presentation around that unchanged
core. Declined by design: stochastic service-level optimizers, probabilistic forecasting,
multi-echelon networks (schema-hedged only), and anything requiring cross-run persistence
(parked behind the SaaS fork gates in roadmap.md §3b/#48/#61).

## 7. Reproduce the verification

```bash
cd .tmp/stress-run
python3 gen_stress_mis.py                # deterministic messy MIS (seed 7)
# corrected-rules simulation (inline script, see session notes / Observations §5c):
#   parses ₹-prices, orders actionable-only, nets transfers, excludes dead stock from urgency
# expected: 351/10 · statuses ⚫24 🟣17 🔴47 🟡62 🔵43 🟢158 · 83 transfers ₹46.9L/₹7.04L
#           gross ₹1.63cr → net ₹1.16cr · hoodie Chandigarh +186%
```
