# Changelog

## 2.1.0 — 2026-08-14 · "timing honesty" release

Closes the three genuinely-new gaps from the second external review (66-point list,
triaged as batch 6 in roadmap.md — most of its "critical" items were already built).
Engine/schema 2.3.0 → **2.4.0**; snapshot golden re-pinned with reason; suite 53 → **62**.

- **G36 — timing honesty**: `current_cover` (shelf-only days) split from `days_of_stock`
  (pipeline cover); per-row **projected stockout date** — ETA-aware, no-ETA arrival
  assumed at lead time (disclosed), overdue receipt dates warned; rows that go dark
  before their inbound lands carry `stockout_before_inbound_days` (23 such rows in the
  stress fixture, some OPTIMAL-by-pipeline — the blind spot this closes). Transfers get
  `receiver_dry_before_arrival_days` when the truck arrives after the shelf runs dry
  (flagged, not blocked).
- **G37 — financial impact (estimated)**: `daily_revenue_at_risk = ADS × price` on
  out-of-stock/critical rows; `capital_tied_up = (SOH − buffer) × price` on overstock
  rows; totals in `kpis.financial_impact`; null when price missing, never fabricated.
  Cockpit: ₹-at-risk KPI card, "Rank by ₹ at risk" toggle on Today's Actions,
  capital-tied-up total on the Overstock lens.
- **G38 — assumptions & policies layer**: every policy threshold is now a named engine
  constant disclosed in `report.json → assumptions_and_policies` (values + applied
  policies + assumptions in one place); new cockpit **Assumptions** lens; formulas.md
  gains a glossary typing every statement (formula / model estimate / policy /
  assumption) and a classical-inventory-theory vocabulary map (our ROP = lead-time
  demand; Buffer = protection level; BF = the safety-stock policy).
- Edge cases pinned by new tests: stated-ADS-0 never divides (no fake %), reserved >
  SOH floors at zero, past-ETA inbound flagged overdue, cover-split invariants,
  financial totals reconcile, drawer/CSV carry the new fields.

## 2.0.2 — 2026-08-12

Cockpit restyled in Claude's design language (UI only — markup, UX, and behavior untouched;
all 53 tests green, no golden changes):
- Claude web tokens: ivory/charcoal grounds, warm ink, terracotta accent, muted status hues
  tuned for both themes; Claude-style pill toggles, buttons, and radii.
- Pixel-block "RED PILL" wordmark (Claude Code style) as inline SVG — no font files.
- New light/dark toggle (top right): overrides the system theme, persists locally,
  presentation-only.

## 2.0.1 — 2026-08-11

Closes the two post-release partials found by the documentation completeness sweep
(engine 2.3.0, snapshot golden re-pinned with reason):

- **G34 — incoming risk**: INCOMING rows are graded — inbound insufficient (below the
  reorder point / below half of it) or late (known receipt date beyond the lead time);
  rows without a receipt date carry a disclosed assumption. `kpis.incoming_risk_count`.
- **G35 — transfer economics**: per-transfer estimated cost (per-unit flag or per-lane
  `lane_costs` policy) and net benefit (saving − cost); unknown cost stays null, never
  zero. Totals in `kpis.transfers`. Cockpit transfer cards show cost/net when known.
- Gap register: **G1–G35 fully closed.** Test suite: 53.

## 2.0.0 — 2026-08-11 · "the honest cockpit" release

The v2 rebuild: from a markdown-report skill to a deterministic engine + interactive
cockpit + native ask-back, built against SPEC.md's gap register G1–G35 across five phases,
each verified by dry runs and a golden test suite (48 tests).

### Engine (2.2.0)
- Versioned `report.json` data contract — the single source of every displayed number.
- Robust real-world parsing (₹/commas/parentheses/whitespace); unreadable optional values
  warn, never silently drop. Broad retail header aliases with mapping-confidence classes.
- Orders only for actionable rows (fixes a 49% plan inflation), engine-owned gross AND
  net totals, transfer-netted order values.
- Three-level trust: cell quarantine (with inferred answer candidates), plausibility
  verify-first gate, run verdict healthy/degraded/blocked + as-of freshness stamp.
- Run directories: immutable input copy, config/override snapshots, run-manifest hashes,
  `--rerun` byte-identical reproducibility.
- Overrides merge + full rerun (raw file immutable), mapping memory (user-confirmed),
  ADS swing cap.
- Demand module: stockout-censored ADS, promo-week exclusion (suspected spikes need
  confirmation), CV volatility, median for volatile SKUs, confidence-scored correction
  proposals; application only by flag/approval.
- Realism: lane-time gate, case-pack rounding, policies (protected stores/lanes/clearance),
  sellable-stock donor math, overcommit flag, budget within/deferred split, mitigation
  fallbacks, ABC-XYZ segmentation + weighted health, size-curve break detection.

### Cockpit
- Fixed template rendered solely from report.json: "Today's Actions", two-rate KPI strip,
  run-verdict banner, decision-trace drawer with per-store signal fixes, Signal-fixes lens,
  quarantine suggestions, estimated/potential money labels, row-level what-if, CSV exports.

### Plugin
- Five namespaced commands: `/redpill:run · :setup · :template · :policies · :explain`.
- SKILL.md rewritten around seven non-negotiables; README with product boundary + privacy.
- Sample apparel workbook in `examples/`.

## 1.0.0 — 2026-07-29
Initial open-source release: skill + standalone engine + marketplace packaging.
