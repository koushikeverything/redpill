<p align="center">
  <img src="assets/banner.png" alt="Red Pill — Right product, Right place, Right Time" width="100%">
</p>

# Red Pill — Demand-Driven Inventory Cockpit

**Upload your daily stock dump. Get back an approved-ready transfer and replenishment
plan — in minutes, with every number traceable to arithmetic you can check by hand.**

Red Pill turns a raw daily/weekly **MIS report** (the routine stock Excel every retail
chain already produces: one row per `SKU × Store` with stock, on-order, demand rate and
lead time) into:

1. **An interactive cockpit** — "Today's Actions" ranked worst-first, health split into an
   *action rate* (starving rows) and an *excess rate* (frozen cash), a decision-trace drawer
   for every row, and downloadable transfer/order CSVs.
2. **A Demand Plan** — inter-store transfers *first* (a truck beats a supplier lead time and
   costs nothing new), then net replenishment orders, then proposed demand-rate fixes.

Grounded in **Theory of Constraints buffer management**: hold a small dynamic buffer per
SKU-location, watch buffer penetration, react. Stock goes where it *sells*, not where it sits.
Tuned for **apparel / lifestyle retail** (style-colour-size catalogs); other retail works with
generic vocabulary. It is deliberately **not** a forecasting suite — the math stays simple
enough to defend in a store meeting, and all the sophistication goes into making the numbers
fed to that math trustworthy.

## Product boundary (read this before trusting it with money)

Red Pill is a **local planning and decision-support tool. All recommendations are advisory** —
it recommends, you execute. It does **not**: modify ERP/POS/WMS data · submit purchase
orders · dispatch or receive transfers · send messages · claim *realised* savings (order
values are labelled **potential**, transfer savings **estimated**) · require any cloud
service. The deterministic Python engine is the sole source of every number; the AI layer
orchestrates, asks bounded questions, and explains — it never computes business figures.

**Privacy:** the engine and renderer are stdlib Python making **no network calls and
collecting no telemetry**; your stock file never leaves your machine except as part of your
own Claude conversation when you run the skill there.

## ⚡ Install (Claude Code)

This repo **is** a Claude Code plugin marketplace:

```bash
/plugin marketplace add koushikeverything/redpill
```

```bash
/plugin install redpill@koushik-skills
```

> Cloning defaults to SSH; without SSH keys use
> `/plugin marketplace add https://github.com/koushikeverything/redpill.git`.

**Claude desktop/web (no `/plugin`):** copy `skills/redpill-inventory/` into
`~/.claude/skills/`, or upload `dist/redpill-inventory.skill`.

## First run

1. *(Optional, once)* `/redpill:setup` — retail type, currency, which optional fields your
   file tracks, business rules, budget. All skippable; defaults apply.
2. Attach your MIS export and run `/redpill:run` (or just say *"run red pill on this"*).
3. Red Pill maps your real headers ("Closing Stock", "Avg Off-take/Day", "Outlet", "MRP"…),
   parses real-world values (`₹2,499`, `1,240`, blanks), and **quarantines anything it can't
   trust instead of guessing** — then asks you one-tap questions with pre-guessed answers
   ("Oxford Shirt is 7 days in 10 other stores — use 7 for Kolkata?").
4. You get the cockpit + a five-line brief. Approve any proposed master-data fixes.
   Download the plan CSVs for whoever executes.

**Commands:** `/redpill:run` · `/redpill:setup` · `/redpill:template` (blank input form) ·
`/redpill:policies` (business rules) · `/redpill:explain` (walk any recommendation's
arithmetic backwards).

## What the file needs

Required per row: **SKU · Store · stock on hand · average daily sales · lead time (days)**.
Useful extras: on-order quantity (blank = 0, disclosed), unit price (enables ₹ values),
weekly sales history (enables demand-signal checks), reserved/damaged stock, case-pack size.
Get a ready template with `/redpill:template` or `python3 …/redpill_engine.py --template`.

Hard rules the engine enforces: **a blank is never treated as zero** · pre-computed statuses
in your file are ignored, recomputed, and disagreements flagged · duplicate SKU×Store rows —
first occurrence wins, later copies quarantined · a file that's mostly unusable gets a
**degraded/blocked run verdict** instead of a confident wrong answer.

## Standalone engine (no AI at all)

Pure-stdlib Python, deterministic, reproducible:

```bash
python3 skills/redpill-inventory/scripts/redpill_engine.py your_mis.csv \
  --run-dir runs/2026-08-11 --as-of 2026-08-11
python3 skills/redpill-inventory/scripts/render_cockpit.py --run-dir runs/2026-08-11
```

The run directory holds `report.json` (versioned data contract), `cockpit.html`,
`computed.csv`, `quarantine.csv` (a pre-filled fix-me form with suggested answers), an
immutable input copy and a `run-manifest.json` — and `--rerun runs/2026-08-11` verifies the
run reproduces byte-identically. User corrections go in an `overrides.json` (the raw file is
never edited); confirmed header mappings persist in a `mappings.json`.

## Outputs & integration ladder

Files first, by design: cockpit HTML + plan/transfer CSVs you can hand to ops or import
anywhere. No connectors, no API — if Red Pill earns a place in your weekly rhythm, that's
the point at which deeper integration is worth discussing (see `roadmap.md`).

## Known limitations (honest list)

- Lane travel times/costs are opt-in (`--transfer-days`, policies) — unset, transfers assume
  intra-network moves beat supplier lead times.
- Demand corrections are proposals: censoring uses the "currently out of stock" heuristic
  (no per-week availability data exists in an MIS); suspected promo weeks need your
  confirmation. Applied to a run only via `--apply-ads-corrections` or approved overrides.
- The 15% transfer-savings rate is a stated, tunable assumption, always labelled estimated.
- One echelon only (stores); no DC/warehouse node yet. Apparel-first; no grocery/pharmacy
  physics (expiry, substitution). No substitution/cannibalisation modelling.

## Development

```bash
make test    # 46-test suite: goldens, property invariants, reproducibility
make build   # package skills/redpill-inventory -> dist/redpill-inventory.skill
make smoke   # quick engine run on the bundled example
```

`SPEC.md` is the canonical scenario + gap register; `Observations.md` the living defect log;
`roadmap.md` the triage of everything proposed and where it landed. CI runs the suite and
rebuilds the bundle on every push touching the skill. See `CONTRIBUTING.md`.

## Troubleshooting

- **"Missing required columns"** — the engine writes the mapping it *did* find into
  `report.json` and a fill-in template; either rename headers, or pass
  `--mappings mappings.json` with `{"Your Header": "soh"}`.
- **Everything quarantined / blocked verdict** — your file's values aren't parseable as
  numbers; open `quarantine.csv`, each row has the reason and a suggested answer.
- **Numbers differ from your ERP's status column** — by design: Red Pill recomputes from raw
  inputs and flags the disagreements (that's usually how you find the ERP is stale).
- **Plugin won't install over SSH** — use the HTTPS marketplace URL above.

## License

MIT © 2026 — see [LICENSE](LICENSE).
