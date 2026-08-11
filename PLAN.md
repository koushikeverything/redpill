# Red Pill — Build Plan (v2: interactive output + native onboarding)

> **⚠ Superseded:** the canonical scenario, gap register, and phasing now live in
> [SPEC.md](SPEC.md). This file is retained for history.

> Phased roadmap to take Red Pill from "markdown report" to "operator cockpit + native ask-back",
> folding in the dry-run defects from [Observations.md](Observations.md). Every phase ends with a
> **dry run on the stress MIS** and a logged observation pass, so fixes compound instead of piling up.
>
> **Shipping shape:** stays a **skill distributed as a plugin** (see Decision D0). No re-architecture.

---

## Decisions locked in

- **D0 — Packaging:** keep the current *skill-in-a-plugin*. The interactive artifact and native
  elicitation are skill-driven (instructions + bundled template/engine); the plugin adds only
  distribution + an optional `/redpill` command. Hooks are **not** used to enforce output.
- **D1 — Single source of truth:** the engine emits one rich `report.json`; the artifact template
  renders it. Deterministic data + fixed template ⇒ identical output every run. This also fixes
  B2/B4/UX-1 from Observations.
- **D2 — Default output is the interactive artifact**, always, downloadable. Markdown/xlsx only on
  explicit request.
- **D3 — Ask-back uses native selection UI** (AskUserQuestion in Claude Code; native cards in
  Cowork where available) with **inferred candidate values**; text/artifact form is the fallback.

---

## Phase 0 — Engine correctness + the `report.json` data contract

**Goal:** one trustworthy data object the artifact can render, with the silent-corruption bugs gone.

**Scope**
- **B1** — parse prices with currency symbols/text (`fnum` strips `₹`/symbols); if a present price
  still won't parse, log a `warnings` entry instead of silently blanking value.
- **B2** — add `order_value_net` (= `reorder_qty_net × price`) and `total_order_value_net` to output.
- **B3** — broaden header normalization (strip `()`/`/`/`.`, collapse to alnum+`_`) and aliases
  (`off_take`, `avg_off_take`, `lead_time_days`, …) so real MIS headers map.
- **B4** — carry unmapped passthrough columns (style/colour/size/supplier/reported_status/`sold_w*`)
  into the output so attributes, discrepancies, and ADS survive.
- **New `report.json`** = superset of `summary.json`: KPIs (incl. action-rate vs excess-rate),
  per-row detail with attributes + plain-language status reason + net order value, transfers,
  reorders, ADS inputs, discrepancy inputs, quarantine, assumptions/warnings, parameters.
- **C1–C3** — integer-stock warning, consistent empty sentinel, precise quarantine wording.

**Deliverables:** updated `redpill_engine.py`, `report.json` schema doc, updated `formulas.md` notes.

**Dry run:** re-run the 361-row stress MIS; assert `report.json` contains every field the artifact
needs; confirm currency price now parses and net totals are correct.

**Observations logged → fixed in-phase:** append a "Phase 0 dry run" section to Observations.md;
anything new (e.g., schema gaps) fixed before Phase 1 starts.

---

## Phase 1 — The interactive artifact ("cockpit")

**Goal:** the single-page, drill-down output described in the proposal.

**Scope**
- Bundled `assets/report_template.html` (self-contained, CSP-safe, theme-aware, no external deps),
  data injected as an inline JSON blob.
- **KPI strip**: action-rate + excess-rate split (M5), rows processed/quarantined, net order value,
  transfer savings, actions-today; Top-3 action chips (clickable → drawer).
- **Segmented view toggle over one list**: Action Queue (default) · By Store · Transfers · Reorders ·
  Signal fixes · Overstock/Dead-stock · Quarantine. Search box + status filter chips.
- **SKU drawer**: raw inputs, computed pipeline/buffer/ROP, plain-language status reason, concrete
  action(s), ADS correction, discrepancy, expected delivery, order value.
- **Download**: page is already shareable; add "download plan CSV" (client-side from the JSON blob).

**Deliverables:** the template + a tiny renderer path (model publishes via Artifact from `report.json`).

**Dry run:** render the stress data; click through drawer + every lens; resize mobile/desktop;
light + dark. Capture screenshots.

**Observations logged → fixed in-phase:** UX pass (legibility, tap targets, empty states, big-list
perf at 350+ rows, horizontal-scroll containment).

---

## Phase 2 — Native onboarding / missing-info elicitation

**Goal:** ask-back via native selectors with inferred candidates, chat- and Cowork-safe.

**Scope**
- **Inference layer** (engine or skill): for each quarantined field, propose candidates —
  lead time from the same SKU at other stores / same store's other SKUs; SOH "N/A" → offer 0 vs
  re-count; blank ADS → offer ADS from sales history. Emit candidates into `report.json`.
- **Ask-back protocol in SKILL.md:** batch by reason; use AskUserQuestion (single/multi-select +
  Other) where available; fall back to an interactive artifact form, then a chat table. On reply,
  **merge + full rerun** (never patch old output).
- Keep the never-guess invariant: no card auto-applies a value the user didn't confirm.

**Deliverables:** updated Step 1.5 in SKILL.md; candidate-inference code; fallback form template.

**Dry run:** feed the messy file with no pre-answers; verify the model asks via cards with inferred
options, applies answers, reruns, and the once-quarantined rows now compute.

**Observations logged → fixed in-phase:** question fatigue (cap N, group), bad inferences, Cowork
fallback behavior.

---

## Phase 3 — Strict skill workflow + plugin packaging

**Goal:** make the cockpit the guaranteed default and give an explicit trigger.

**Scope**
- Rewrite SKILL.md Step 5: **always** produce the artifact; markdown/xlsx only on request; wire the
  Phase-2 elicitation; state the "downloadable cockpit every run" contract.
- Add `.claude-plugin` **`/redpill` command** that restates the strict contract and points at the skill.
- Update README/handoff/CONTRIBUTING; rebuild `.skill` bundle via CI.

**Deliverables:** new SKILL.md, `/redpill` command, refreshed docs, rebuilt bundle.

**Dry run:** cold, as a user — attach the stress xlsx, say "run red pill" → expect artifact-by-default
+ native asks, no markdown wall. Repeat via `/redpill`.

**Observations logged → fixed in-phase:** trigger reliability, does-it-always-artifact, doc accuracy.

---

## Phase 4 — Model / metric refinements

**Goal:** make the numbers defensible.

**Scope**
- **M1** — transfers: optional zone/lane-cost input; otherwise label transfers as intra-network and
  savings as *estimated*.
- **M2** — savings rate scales with lead-time gap avoided (or clearly labelled illustrative).
- **M3** — volatile SKUs (CV>0.6): use median / longer window before recommending an ADS change;
  encode in `formulas.md`.
- **M4** — ADS corrections roll up to SKU family by default (per-store on drill-down only).
- **M5** — finalize action-rate vs excess-rate (mostly done in Phase 1; lock semantics in docs).

**Deliverables:** engine + formulas + report changes.

**Dry run:** re-run stress MIS; confirm corrections are aggregated, volatile SKUs use median, health
split reads sensibly.

**Observations logged → fixed in-phase:** over/under-correction, transfer realism edge cases.

---

## Phase 5 — Hardening & release

**Goal:** lock behavior and ship.

**Scope**
- Golden-file regression: freeze `report.json` for the stress MIS; test asserts stability.
- Finish the in-progress **sample workbook** (Observations/handoff §9) → `examples/`.
- Version bump, README refresh (artifact GIF/screenshot), publish; consider Anthropic official directory.

**Deliverables:** test suite, sample workbook shipped, release.

**Dry run:** full cold end-to-end + regression green.

**Observations logged:** final pass; close out the backlog.

---

## Carry-over defect backlog (from the first dry run)

| ID | Sev | Item | Lands in |
|---|---|---|---|
| B1 | 🔴 | Currency-symbol price dropped silently | Phase 0 |
| B2 | 🔴 | `order_value` gross, not net | Phase 0 |
| B4 | 🟡 | Passthrough columns dropped from output | Phase 0 |
| B3 | 🟠 | Header aliases too narrow | Phase 0 |
| C1–C3 | ⚪ | Integer-stock warning, empty sentinel, quarantine wording | Phase 0 |
| M5 | 🟡 | Health conflates starved vs excess | Phase 1 |
| M3/M4 | 🟡 | ADS window/median + roll-up | Phase 4 |
| M1/M2 | 🟠 | Transfer geography/cost + savings labelling | Phase 4 |
| UX-1 | 🟡 | Rich `report.json` so model stops re-deriving | Phase 0 |
| UX-2 | 🟡 | Engine can't ingest raw headers unaided | Phase 0 (B3) |
| UX-3 | ✅ | Quarantine/fill-in UX is a strength — preserve | Phase 2 |
| UX-4 | 🟡 | Confidence caveat on headline ₹ numbers | Phase 1 |
