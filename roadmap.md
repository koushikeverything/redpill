# Red Pill — Suggestion Triage & Forward Roadmap

> Classification of the 47 external suggestions (+1 general workflow proposal) against what Red
> Pill **is today** (an open-source Claude Skill + deterministic engine, per [PLAN.md](PLAN.md))
> and what it **could become**. Each verdict was checked against the actual engine
> (`redpill_engine.py`), the formula spec, and the stress-run evidence in
> [Observations.md](Observations.md) — not just taken at face value.
>
> **Verdicts:**
> ✅ **Genuine** — build it; makes the current product better.
> 🟡 **Genuine (partial)** — a subset is right now; the rest is parked or wrong (see notes).
> 🅿️ **Park** — valid, but not a priority now; most activate only on the SaaS fork (below).
> ❌ **Wrong** — premise or prescription doesn't hold for this product (reason given).

---

## 0. The strategic fork this list forces

About **15 of the 47** suggestions (#8, 9, 24, 25, 28, 29, 34, 36, 38, 39, 42, 46, 47, and half of
#7 and the General Suggestion) are not features — they are one decision wearing different hats:

> **Does Red Pill stay an *analysis skill* (upload MIS → audited plan), or become a *closed-loop
> operations SaaS* (persistent accounts, approvals, execution tracking, outcome learning)?**

Everything needing **persistence across runs, multiple users, or execution tracking** belongs to
the SaaS side. The skill architecture cannot honestly deliver those (a chat session has no PO
lifecycle, no store-manager login, no 14-day outcome loop). They are parked as one cluster —
**not** dismissed — and the roadmap below keeps the engine's data contract (`report.json`) clean
enough that a future service layer can wrap it without a rewrite. That is the correct hedge:
build the analyzer excellently, keep the SaaS door open, decide the fork on real user pull.

---

## 1. Verdict table — batch 1 (model & product issues, #1–15)

| # | Suggestion (condensed) | Verdict | Analysis | Lands in |
|---|---|---|---|---|
| 1 | ADS ignores stockouts, promos, seasonality; add confidence | 🟡 | **Stockout-censoring is the single best model catch in the list**: an empty shelf records zero sales exactly when demand is lost, so our trailing-average "actual ADS" is biased *down* for the worst rows. Verified as a real gap — engine/skill has no censoring adjustment (and our stress generator doesn't even simulate it — test-data gap, now logged). Promo-week exclusion is already *stated* in `formulas.md` but not operational → make it real (see #18). Confidence scores on corrections: genuine. Full seasonality profiles by region/category: park (needs cross-year data most MIS files won't have). | Phase 4 (censoring + confidence); park seasonality |
| 2 | Buffer/target factors 1.5/2.5 are "arbitrary"; derive from service levels | 🟡 | Half right, half philosophically confused. The framing "arbitrary" is wrong — fixed, simple, visible buffer factors are a *deliberate* ToC design choice (react fast to buffer penetration, don't optimize a stochastic model you can't explain). Full service-level/stockout-cost derivation is a different school (statistical safety stock) and would blur the product's identity. **But**: per-segment defaults (basics vs fashion vs clearance) and an impact preview when tuning are genuinely missing. Per-row `buffer_factor` override already exists in the engine — undocumented. | Phase 4 (segment defaults + doc the override); park service-level optimizer |
| 3 | Transfer logic ignores transfer LT, freight, pack sizes, donor future demand, donor QOO | 🟡 | Mostly genuine — this extends our own finding M1. Add: transfer-LT < supplier-LT gate, optional lane cost/economics check, pack-size multiples. Two corrections to the friend's list: (b) "ensure donor stays above buffer" is **already satisfied** (surplus = SOH − Buffer, donor keeps its full buffer by construction); (e) "include donor QOO in surplus" is **debatable, not a defect** — excluding inbound stock from what a donor may give away is deliberately conservative; make it a config flag, not a fix. | Phase 4 |
| 4 | Overstock uses SOH but urgency uses Pipeline — inconsistent | ✅ | Verified real in the logic: a store with modest SOH plus a huge inbound QOO reads OPTIMAL today (pipeline overcommitment invisible). Didn't trigger in the stress run only because the generator never built that shape — added to the stress-data TODO. Fix: keep SOH-based OVERSTOCK (capital-on-shelf is a real, distinct signal) and **add a `PIPELINE_OVERCOMMIT` flag** (Pipeline > 2×Buffer) rather than redefining the status — preserves the six-status semantics. | Phase 4 |
| 5 | Health % treats ₹99 accessory = ₹8k jacket; weight it | 🟡 | Genuine addition, wrong replacement. A value-weighted health view (margin-at-risk, capital freed) is a real improvement for management. But the simple % must stay the *operator* headline — a store associate acts on counts, not weighted composites. We already split action-rate vs excess-rate (M5). Ship weighted as a second lens, not the main KPI. | Phase 4 (needs #22 first) |
| 6 | CRITICAL at ½×ROP too aggressive; make configurable + explain | ✅ | Cheap and right. Threshold becomes a parameter (default unchanged), per-segment once #22 exists. The "explain why critical" ask is **already built** — the cockpit drawer shows plain-language reasons ("Pipeline 12 < ½·ROP 14…"). | Phase 4 (config); explanation done Phase 1 |
| 7 | ADS auto-correction needs governance: run-time vs master-data, approval, caps | ✅ | Genuine and mostly *aligned with existing design* — the skill already separates "corrected ADS used this run" from "proposed master change listed in report". What's missing: explicit approval (fits the Phase-2 native ask-back cards perfectly), max-swing caps per run, and a logged accept/reject. The "log every change" half needs persistence → that slice parks on the fork. | Phase 2 (approval cards + caps); park the audit log |
| 8 | Turn report into an action queue with owners, due dates, ERP export | 🟡 | The queue itself **is Phase 1** — the cockpit's default lens is a ranked Action Queue with CSV export. Owners, statuses, approve/reject persistence, ERP push: SaaS fork. Boundary drawn: v1 ends at "exportable, prioritized queue". | Phase 1 (done in mock); park workflow |
| 9 | Closed-loop measurement: link recommendations to outcomes, ROI | 🅿️ | Valid and important *for a SaaS*. Impossible in a stateless skill run. Cheap interim: a `--compare previous_report.json` diff mode (what changed since last run, which recommendations resolved) gets 20% of the value with no infrastructure. | Park (fork); interim diff mode v2 |
| 10 | Decision trace / auditability per SKU×store | ✅ | Genuine and ~70% already built: the drawer shows raw inputs → recomputed values → status reason → action; the report shows mapping, assumptions, quarantine. Remaining: show the ADS correction step inline (stated → actual → used) and the transfer-choice reasoning. Formalize as a named "decision trace" section of `report.json`. | Phase 0/1 |
| 11 | "Red Pill" name baggage; use neutral market-facing name | 🅿️ | Legitimate for commercialization, irrelevant for an open-source skill today. Merged with #44 (which adds the harder fact: **"Red Pill Analytics" already exists** as a data consultancy). Action now: none. Action *before any* commercial/brand spend: trademark + domain search, then rename. | Park (gate: commercialization) |
| 12 | Crowded market; sharpen wedge to 10–75-store Indian apparel chains | 🅿️ | Sound strategy writing, not a build item. The wedge described (transfers + MIS-first + explainable trace) **is what we're already building** — noted as validation. Adopt the copy when docs are rewritten in Phase 3. | Park (informs Phase 3 docs) |
| 13 | Lifecycle tags (launch/growth/steady/clearance) varying rules | 🅿️ | Real for apparel, but second-order: needs segmentation (#22) and a promo/event notion (#18) first, plus users willing to maintain the tags. Design `report.json` so a `lifecycle` column passes through when present. | Park → v2 |
| 14 | Alert-volume controls: max actions/day, priority filters, top-20 view | 🟡 | The *prioritized top-N view* is genuine and already built (Action Queue, ranked, filterable). The *hard cap* ("max actions per day") is **wrong** — hiding the 21st most-urgent stockout because a quota filled is exactly how operators lose trust. Volume is managed by ranking + filters + segmentation (#22), never by truncation. Our own no-silent-caps rule. | Phase 1 (done); cap: rejected |
| 15 | Phase integrations: files first, APIs later | ✅ | Already the de-facto architecture (CSV in, CSV/JSON out) — costs nothing to declare it. Documented as the "integration ladder" in Phase 3 docs so it reads as intent, not accident. | Phase 3 (docs) |

## 2. Verdict table — batch 2 (competitor-gap list, #16–32)

| # | Suggestion (condensed) | Verdict | Analysis | Lands in |
|---|---|---|---|---|
| 16 | Multi-echelon: model supplier → DC → store early | 🅿️ | Directionally right for the target segment (mid-market chains usually have one warehouse), but "early" is wrong — it doubles the data requirement (DC stock, DC-store LT) before the store-level loop is even trusted. Correct prep: `report.json` rows carry a `node` field so a DC becomes "just another location with lanes" later. | Park → v2 (schema prep in Phase 0) |
| 17 | Probabilistic demand + service-level-driven buffers | 🅿️ | Same school as #2's second half. Our CV-based volatility detection (raise BF when CV > 0.6) is the honest lightweight version. Full probabilistic planning is a different product tier; revisit only with multi-month data and the fork decided. | Park |
| 18 | Promo/markdown/event calendar; exclude promo weeks from baseline | ✅ | Highest-value item in batch 2. Cheap, powerful, and already half-promised: `formulas.md` says "exclude promo-period spikes" but nothing implements it. v1: an optional `promo_weeks` input (or per-week flag column); flagged weeks are excluded from ADS baseline or given a controlled uplift; every exclusion disclosed in the report. Festival calendar presets (Diwali etc.): v2. | Phase 4 |
| 19 | Omnichannel: support inventory node + demand channel; reserve e-com stock | 🅿️ | Premature for an MIS-file product, but the schema hedge is nearly free: accept optional `channel` / `reserved_qty` columns, subtract reservations from transferable surplus when present. Full omnichannel allocation: firmly parked. | Park (schema hedge in Phase 0) |
| 20 | What-if scenario mode (LT doubles, demand +30%, transfer 100 units) | 🟡 | The lightweight version is uniquely cheap for us **because the engine is deterministic pure formulas** — the cockpit can recompute statuses client-side from sliders (BF/TF/LT/ADS deltas) with zero backend. Genuine as a cockpit feature. Full scenario planning (Kinaxis-style) is enterprise scope — park. | Phase 4 (cockpit sliders); park full scenario |
| 21 | Style-family & size-curve intelligence (broken size curves) | ✅ | The single best *differentiator* suggestion in the list. Data already exists (style/color/size columns pass through). Detect: same style-store with M out while S/XL sit → recommend size-level transfer/replen; flag stranded size mixes as effective dead stock. Strong apparel wedge, moderate effort. | Phase 4 (v1.5 flagship) |
| 22 | ABC-XYZ segmentation driving buffers/alerts/approvals | ✅ | Genuine keystone — #5 (weighted health), #6 (per-segment thresholds), #13 (lifecycle), #14 (prioritization) all hang off it. v1: compute ABC (revenue contribution) × XYZ (CV — already computed!) per SKU automatically; surface as a lens + parameter defaults. | Phase 4 |
| 23 | Open-to-buy / cash budget constraint on PO recommendations | 🟡 | Genuine-lite: a `--budget` cap that ranks the replenishment queue by urgency×margin and cuts a "within budget / deferred" line is easy and makes finance trust the output. Full OTB planning (merchandise budgeting by month/category): different product, park. | Phase 4 (cap); park full OTB |
| 24 | Supplier scorecard: promised vs actual LT, fill rate, MOQ | 🅿️ | Needs PO-history data no MIS snapshot contains, and persistence. MOQ/case-pack, the one slice that *is* snapshot-compatible, is covered under #41 policy inputs. | Park (fork) |
| 25 | PO lifecycle: draft → approved → sent → received | 🅿️ | Pure SaaS execution layer. v1 boundary is "exportable PO draft CSV". | Park (fork) |
| 26 | Inventory accuracy / trust score; recommend cycle counts | 🟡 | The full reconciliation loop needs event data → park. But a **plausibility check is genuine and snapshot-compatible**: sold 44/week for 8 weeks yet SOH never moved → data smells; SOH high while sales zero for weeks → phantom stock. Flag "verify count before acting" instead of confidently recommending a transfer built on bad SOH. | Phase 4 (plausibility flags); park trust score |
| 27 | ERP/POS connector ladder | 🅿️ | Duplicate of #15's later rungs. Files-first already true; connectors only after the fork. | Park |
| 28 | Mobile store-execution app (scan, pack, receive) | 🅿️ | Way outside a skill's architecture; belongs to the SaaS fork's execution layer, and even then last (after #8/#25). | Park (fork, late) |
| 29 | Onboarding baseline + monthly "value realised" report | 🅿️ | Commercial-engagement machinery. Needs customers, persistence, and time-series. The *baseline snapshot* idea partially exists already (every run reports health/status mix — comparing two runs is #9's diff mode). | Park (fork) |
| 30 | Positioning: fast-to-value, paid pilot, per-store pricing | 🅿️ | Sensible commercial defaults; zero build implication today. Revisit at commercialization with #38/#46/#47. | Park (commercial cluster) |
| 31 | Build tenant separation, RBAC, encryption, audit logs early | ❌ | **Wrong premise for the current architecture.** There is no hosted service — the engine runs locally/in the user's own Claude session; we never hold the retailer's data, which is a *selling point* ("your MIS never leaves your environment"), not a gap. Building multi-tenant security "early" for a product with no tenant would be pure waste. Becomes 🅿️ (and mandatory) the day a hosted service exists. | Rejected now; auto-revives on fork |
| 32 | Lead with outcome statement, AI behind the scenes | ✅ | Correct and nearly free: the README/skill description should say "stock dump in → approved transfer & replenishment plan out in minutes", with AI cast as mapper/explainer/ask-back. Matches how the product actually works. | Phase 3 (docs) |

## 3. Verdict table — batch 3 (strategy & GTM, #33–47 + general)

| # | Suggestion (condensed) | Verdict | Analysis | Lands in |
|---|---|---|---|---|
| 33 | Real competitor is Excel + a capable planner | ✅ | The sharpest strategy line in the list, and it costs nothing — it's a *design test*, not a feature: every phase must beat "analyst + spreadsheet" on the first file (upload → map once → actionable queue → override in seconds). Phases 1–3 are already aimed at exactly this; adopt it as the explicit acceptance bar for dry runs. | Guiding principle (all phases) |
| 34 | "Claude-native" is a feature not a moat; build persistent product layer | 🅿️ | The challenge ("why not our analyst + ChatGPT?") is fair; the answer today is the deterministic engine + audited trace + zero-variance output — a chat session reproduces none of that reliably. The *persistent* moat (policies, history, learning) is the SaaS fork. Interim hedge worth noting: a skill can persist per-project policy/config files between runs — a mini-moat without a server. | Park (fork); config-file hedge in Phase 4 |
| 35 | Declare build-vs-buy boundary: action layer, not ERP | ✅ | One honest paragraph in the README prevents years of feature-sprawl arguments. "Red Pill sits between your daily data and execution; it does not replace your ERP/WMS." Free. | Phase 3 (docs) |
| 36 | Productized onboarding: diagnostic, mapping template, DQ score, parallel run | 🅿️ | For paying customers — parked with the commercial cluster. Worth noting the skill already contains the seed: quarantine + reasons + fill-in form *is* a data diagnostic; Phase 2's native ask-back makes it better. A formal "data-quality score" per file is a nice cheap addition when convenient. | Park (commercial); DQ score opportunistic |
| 37 | Historical replay / back-testing before live recommendations | 🅿️ | High-value trust builder, honestly labeled by the friend ("simulated, not guaranteed"). Needs multi-snapshot ingestion + a replay harness — real work, and only persuasive with real customer history. Right home: v2, as the flagship "prove it" feature — and the golden-file regression in Phase 5 is its technical seed. | Park → v2 (flagship candidate) |
| 38 | Implementation promise: plan in 48h, outcome in 30 days | 🅿️ | A marketing claim, and the friend's own caveat is the verdict: only after testing against multiple real datasets. Nothing to build. | Park (commercial) |
| 39 | Collaboration roles: planner/approver/store/finance queues | 🅿️ | Correct diagnosis of where single-user tools stall — and pure SaaS. The skill's honest scope is the single planner; multi-role approval belongs to the fork. | Park (fork) |
| 40 | Data freshness visible on every run | ✅ | Trivial and builds exactly the right kind of trust: stamp "data as of <file timestamp / stated period>" on the cockpit header and report; never imply real-time. Add a staleness warning if the snapshot is old. | Phase 0/1 (cheap win) |
| 41 | Plain-language policy engine: protected stores/SKUs, blacklists, MOQ, freezes | 🟡 | The *config* half is genuine and engine-compatible: an optional `policies.yml` (protected stores/SKUs, transfer lane blacklist, MOQ/case-pack multiples, clearance no-replenish) applied as hard constraints, every applied policy disclosed in the report. The *plain-language/NL* layer is where the skill shines anyway (Claude translates English → config). Full policy UI: fork. | Phase 4 (config + disclosure) |
| 42 | Account-level learning moat (transit reliability, override patterns) | 🅿️ | SaaS-fork learning loop. The per-project config/memory hedge (#34) is the skill-scale version. | Park (fork) |
| 43 | Vertical discipline: apparel/lifestyle first, reject grocery/pharma | ✅ | Free, correct, and already implicitly true (sample data, size curves, ₹). Make it explicit in docs and let #21 (size-curve intelligence) be the proof. Grocery/pharmacy have expiry/substitution physics we don't model — say so. | Phase 3 (docs) |
| 44 | Rename before commercial launch; trademark check ("Red Pill Analytics" exists) | 🅿️ | Same as #11, plus a concrete collision that makes the eventual rename near-certain. The only *near-term* action: don't sink money into Red Pill brand assets beyond the repo. Gate: before any commercial spend. | Park (hard gate at commercialization) |
| 45 | Conservative ROI methodology; savings are counterfactual | 🟡 | The labeling half is genuine, cheap, and already started (UX-4: savings marked "estimated"; cockpit footer caveat). Formalize: ranges not points, "estimated vs realised" vocabulary, count only executed actions. The measurement half needs outcome data → parked with #9/#29. | Phase 1 (labeling); park measurement |
| 46 | Partner with ERP/POS integrators and consultants | 🅿️ | Commercial distribution strategy — parked with the cluster, nothing to build. | Park (commercial) |
| 47 | Hybrid pricing: setup fee + per-active-store platform fee | 🅿️ | Same cluster. Noted so future-us doesn't reinvent it. | Park (commercial) |
| GS | Daily closed-loop operating cycle; key screen = "Today's Actions" not a dashboard | 🟡 | Split cleanly in two. **Adopt now:** the framing — the cockpit's default lens *is* "Today's Actions" (rename it exactly that), the priority decision order (trust data → availability risk → transfer first → net PO) is ~80% our existing pipeline, and step 6's mitigation vocabulary (expedite / substitute / markdown / escalate) is a genuine addition to recommendation types. **Fork:** steps 8–12 (execute, reconcile, measure, learn) are the SaaS loop — the honest v1 boundary is steps 1–7 ending in an approved, exportable plan. | Phase 1 (framing) + Phase 4 (mitigations); park 8–12 |

## 3b. Verdict table — batch 4 (viability & adoption risks, #48–63)

| # | Suggestion (condensed) | Verdict | Analysis | Lands in |
|---|---|---|---|---|
| 48 | No proof of willingness to pay; interview 15–20 chains, 3 paid pilots first | 🅿️ | Correct sequencing discipline *for commercialization* — and the strongest argument for not building the SaaS fork speculatively. Nothing to build; it gates the fork itself: no persistent platform until paid pilots exist. Adopted as the fork's entry condition. | Park (becomes the fork's gate) |
| 49 | Quantified ROI baseline at onboarding, success metrics agreed in writing | 🅿️ | Duplicate of #29's machinery with better framing (agree the calculation method up front). Parked with it; the metric list (stockout exposure, aged stock, turns, accuracy) is a ready-made spec when the time comes. | Park (fork, with #29) |
| 50 | Bad SOH makes recommendations harmful; confidence score + verify-count gate | 🟡 | The sharpest risk statement in all four batches — a confidently wrong transfer built on phantom stock damages trust more than no recommendation. The *loop* (cycle counts, reconciliation) is fork territory (#26). But the **gate is buildable now**: when plausibility checks fail (sales ≠ stock movement, stale counts), downgrade that row's recommendation to "verify count first" instead of a transfer/PO — especially above a value threshold. Upgrades #26 from "flag" to "gate". | Phase 4 (with #26) |
| 51 | UOM / product-master complexity: packs, bundles, cases, hierarchy | 🟡 | Full canonical data model is enterprise-integration scope — park. The slices that bite our actual segment now: **case-pack/MOQ multiples** (already slotted via #3/#41) and the **style→variant hierarchy** (already carried, powers #21). Add: validate UOM consistency on ingest (a row selling 44/week from SOH 6 might be a case-vs-unit mismatch — overlaps #26 plausibility). | Phase 4 (slices); park canonical model |
| 52 | Closing stock isn't sellable stock: reservations, damaged, display; use ATP | 🟡 | Genuine-lite upgrade of the #19 schema hedge: when optional `reserved_qty`/`damaged_qty` columns exist, compute **ATP = SOH − reserved − damaged** and use it for surplus/transfer math; when absent, disclose "SOH treated as fully sellable" in assumptions. Cheap, honest, and protects the transfer plan's credibility. Full ATP (safety/protection stock policies) rides #41. | Phase 4 (with schema hedge from Phase 0) |
| 53 | Cannibalisation/substitution ignored; substitute groups later | 🅿️ | Friend's own verdict is "later", and it's right — needs substitute-group master data no MIS carries. Interim honesty already covered by #45/#62 labeling (don't overstate recovery). Natural v2 companion to #21's style-family work. | Park → v2 (after #21) |
| 54 | No evaluation of whether corrected ADS improves decisions | 🅿️ | Real gap, but every metric proposed (acceptance rate, post-action sell-through, regret rate) needs outcomes across runs → fork. The skill-scale seed: #9-lite's run-over-run diff can track ADS-correction bias (was last run's "actual" closer than its "stated"?) with no infrastructure. | Park (fork); bias check rides #9-lite |
| 55 | No safe fallback mode; run-level guards, "do not use this run" | ✅ | Best buildable item in the batch. We quarantine *rows*; nothing guards the *run*. Add a run-level data-quality verdict to `report.json`/cockpit: quarantine % above threshold, mapping confidence low, snapshot stale (#40), or anomalous totals → banner the whole run "degraded — verify before acting" (or refuse, with reasons). Pure engine+template work, no persistence needed. Extends the never-guess invariant from rows to runs. | Phase 0 (verdict) + Phase 1 (banner) |
| 56 | Planner incentives conflict (stores protect stock, finance wants less) | 🅿️ | True and important — and entirely organisational. A skill cannot set district-level incentive structures; even the SaaS fork only *supports* this (network-outcome metrics). Belongs in implementation/change-management material (#63) when that exists. | Park (commercial/change mgmt) |
| 57 | Customer may lack transfer logistics capacity | 🟡 | The build slice is already slotted: #41's policy config (allowed lanes, blacklists) + #3's lane economics = "recommend only feasible transfers". Transfer **batching** (group small moves into one weekly truck per lane) is a genuinely new, snapshot-compatible idea — added to #3's scope. Discovery-stage capacity mapping is commercial. | Phase 4 (batching added to #3); park discovery |
| 58 | Procurement/security pack blocks enterprise sale | 🅿️ | Same territory as #31 but correctly framed as *sales collateral before enterprise pilots* rather than "build it early" — so it parks rather than being rejected. Auto-activates with the fork alongside #31. | Park (fork gate, with #31) |
| 59 | No product/consulting boundary; bespoke requests eat the roadmap | 🅿️ | Commercial governance. The "productise only what ≥3 customers request" rule is worth adopting verbatim when there are customers. Until then the open-source analogue already exists: config over code (#41), no per-user forks. | Park (commercial) |
| 60 | GTM harder than engineering; pick one buyer, one message | 🅿️ | Commercial cluster. The proposed message ("recover availability from existing stock without buying more") is strong — filed with #32's positioning copy for when docs are rewritten. | Park (commercial; copy noted for Phase 3) |
| 61 | No kill criteria; founders keep polishing non-essential products | 🅿️ | The most valuable *discipline* in the batch, nothing to build. Adopted as governance: the fork doesn't open without #48's pilots, and the friend's gates (≥60% weekly review, 30–40% execution, renewal+reference) become the fork's *continuation* criteria. Recorded so future-us can't quietly ignore it. | Park (governance, recorded) |
| 62 | Savings claims: label realised / estimated / potential everywhere | ✅ | Cheap, immediate, and sharpens #45 into a concrete vocabulary. Today a stateless skill can honestly emit only two of the three — **estimated** (modelled effect of recommended actions) and **potential** (unexecuted queue value); **realised** activates with the fork's outcome tracking. Adopt the three-label scheme in `report.json` + cockpit now, with "realised: n/a (no execution tracking)" stated rather than hidden. | Phase 1 (with #45) |
| 63 | Change management under-scoped; 10–20% of cost, 30/60/90 cadence | 🅿️ | Real (adoption beats model quality) and entirely commercial-stage. Files with #36's onboarding product and #56's incentive design as the "implementation as product" bundle. | Park (commercial, with #36/56) |

## 3c. Batch 5 — the implementation action list (P0–P5 plan, master prompt, file tree)

A fifth batch arrived as a full engineering action list rather than feature suggestions. Verdict:
**the strongest batch — ~60% independently confirms decisions already in SPEC.md** (engine-owns-
numbers, report.json, actionable-only ordering, verify gates, run verdicts, labels, goldens),
**and it contributed six genuinely new items**, all adopted into SPEC:

- **G31** — explicit product-boundary + non-goals block (advisory-only; the "does NOT" list).
- **G32** — run directories with immutable raw copy, config/mapping/override snapshots,
  `run-manifest.json`, per-field provenance, and a reproduce-this-run command. The biggest
  single addition: it makes every run auditable and replayable, locally.
- **G33** — mapping-confidence classes + project-local mapping memory (confirmed mappings
  persist per source pattern; low confidence never applied silently).
- **G34** — ETA-aware inbound stock and an INCOMING sufficiency/lateness risk flag (our ladder
  treats any inbound as comfort; "is it enough, and will it arrive in time?" was unasked).
- **G35** — transfer economics split: value *moved* is not value *saved*; report moved / deferral
  / est. cost / net benefit separately.
- **What-if correctness constraint** (amends G11): row-level what-if only, or full engine
  recompute — a slider must never leave stale network-wide totals on screen.

Also adopted: namespaced commands (`/redpill:run` style — matches actual plugin conventions; our
hyphenated names were wrong), numbered-chat-choices as the interaction *baseline* with native
cards as progressive enhancement (amends G13), the Phase-0 entry audit ("no code before a
G1–G35 current-state table"), the ten-point final build gate, and the offline/privacy statement.

**Adapted, not adopted:** the proposed 8-package `src/` tree — over-engineered for a ~500-line
stdlib engine that must stay portable inside a `.skill` bundle; we keep a compact engine +
`tests/` with goldens, and revisit only if the engine outgrows it. `.redpill/` run/config storage
belongs in the **user's project directory**, not the plugin repo. "Days of stock = infinity" for
ADS=0 → we use null/"—" (JSON-safe) instead.

**Declined:** nothing material — this batch contained no wrong prescriptions, only scope we had
already fenced off (its own non-goals list matches our fork shelf almost exactly).

---

## 4. What this does to the build roadmap

**Scorecard (all 63 + GS):** 13 ✅ genuine · 16 🟡 partial · 33 🅿️ parked · 1 ❌ wrong
(+2 wrong-in-part: #2's "arbitrary" framing, #14's hard cap).

### Immediate adds to existing phases (no re-planning needed)
| Item | Source | Phase |
|---|---|---|
| Freshness stamp + staleness warning | #40 | 0/1 |
| **Run-level data-quality verdict + "degraded run" banner** | #55 | 0/1 |
| Decision-trace section formalized in `report.json` | #10 | 0/1 |
| "Today's Actions" naming + realised/estimated/potential labeling | GS, #45, #62 | 1 |
| Schema hedges: `node`, `channel`, `reserved_qty`, `lifecycle` pass-through | #16, 19, 13 | 0 |
| ADS-correction approval via native cards + max-swing caps | #7 | 2 |
| Positioning copy: outcome statement, ERP boundary, apparel-first, integration ladder | #32, 35, 43, 12, 15 | 3 |
| Stress-data gap: add a pipeline-overcommit row and a stockout-censored-sales row to the generator | #4, #1 verification | next dry run |

### Phase 4 grows into the "model realism" release (v1.5)
Ordered by value ÷ effort: **#18 promo flags** → **#1 stockout-censoring + confidence** →
**#22 ABC-XYZ** (unlocks #5 weighted health, #6 segment thresholds) → **#21 size-curve
intelligence** (the apparel differentiator) → **#3 transfer realism** (LT gate, pack sizes, lane
economics, **+ batching per lane from #57**) → **#26+#50 plausibility flags upgraded to a
verify-first gate** on high-value recommendations → **#4 overcommit flag** → **#41 policy config**
→ **#52 ATP when reserved/damaged columns present** → **#23 budget cap** → **#20 what-if sliders**
→ GS mitigation actions → #2 segment defaults → #51 UOM-consistency check.

### v2 candidates (post-v1.5, still skill-shaped)
#37 historical replay (flagship trust feature) · #9-lite run-over-run diff · #16 basic DC node ·
#13 lifecycle rules · full #20 scenario mode.

### The fork shelf (revisit only on a deliberate SaaS decision)
#8 workflow · #9 outcomes · #24 supplier intel · #25 PO lifecycle · #26 trust score · #28 mobile ·
#29/#49 ROI machinery · #31/#58 security & procurement pack (auto-revive, mandatory) · #34/42
learning moat · #36/#56/#63 onboarding & change-management bundle · #38/30/46/47/59/60 commercial
cluster · #39 roles · #53 substitution (v2, after #21) · #54 model evaluation · GS steps 8–12 ·
#11/44 rename (gate).

**Fork governance (from #48/#61, adopted):** the fork does not open without customer proof —
paid pilots first (#48) — and once open, continues only past validation gates (≥60% of
recommendations reviewed weekly, 30–40% of viable actions executed, measurable improvement vs
baseline, a renewing reference customer). Features don't reopen this decision; evidence does.

### Explicitly rejected
- **#31 now** — building multi-tenant security for a product with no server; local execution is a
  privacy *advantage* today.
- **#14's hard cap** — truncating the action queue hides emergencies; rank and filter, never cap.
- **#2's premise** — the fixed factors aren't arbitrary, they're ToC; tune by segment, don't
  replace with a stochastic optimizer.
- **#3(b)** — donor buffer protection already holds by construction; no fix needed.
