<p align="center">
  <img src="assets/logo.png" alt="Red Pill logo" width="200">
</p>

# Red Pill — Demand-Driven Inventory Skill

**Right SKU, right place, right time.** Red Pill turns a raw daily/weekly MIS
stock report into two decisions you can act on the same day:

1. **Final Report** — inventory health across every `SKU × Store`: status colours,
   a health score, an urgency ranking, and flagged exceptions.
2. **Demand Plan** — the concrete moves: replenishment orders, inter-store
   transfers, and demand-rate (ADS) corrections.

It's grounded in **Theory of Constraints (ToC) buffer management**: don't forecast
far ahead — hold a small dynamic buffer per SKU-location, watch buffer penetration
daily, and react by replenishing, transferring, or correcting the demand signal.
Stock should go where it *sells*, not where it *sits*.

> **Core invariant:** derived values are never trusted from the input file and
> never stored — everything is recomputed from raw inputs every run. If the report
> carries pre-computed statuses or reorder quantities, Red Pill recomputes them and
> flags any mismatch.

This repository packages Red Pill as a **[Claude Skill](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview)**
you can install into Claude Code, the Claude apps, or the Agent SDK — plus a
standalone Python engine you can run with no AI at all.

---

## What's in the box

```
redpill/
├── README.md                       ← you are here (the brief)
├── LICENSE                         ← MIT
├── Makefile                        ← `make build` / `make sync` / `make test`
├── skill/
│   └── redpill-inventory/          ← the Skill source of truth
│       ├── SKILL.md                ← the workflow Claude follows
│       ├── references/
│       │   ├── formulas.md         ← authoritative formula + status spec
│       │   └── report-template.md  ← Final Report + Demand Plan layout
│       ├── scripts/
│       │   └── redpill_engine.py   ← deterministic calculator (no AI needed)
│       └── assets/
│           └── mis_input_template.csv
├── scripts/
│   ├── build_skill.sh              ← package skill/ → dist/redpill-inventory.skill
│   └── sync_from_skill.sh          ← unpack an edited .skill back into skill/
├── examples/
│   └── sample_mis.csv              ← runnable example data
└── dist/                           ← built .skill package (generated)
```

---

## The model in 60 seconds

Everything is computed **per `SKU × Store`** from raw inputs. Lead time and demand
rate live per SKU-store — the same product can have a 7-day lead time in Mumbai and
14 in Goa.

| Symbol | Field | Notes |
|---|---|---|
| SOH | Stock on hand | units physically at the store |
| QOO | Quantity on order | in transit / open POs (blank → treated as `0`, disclosed) |
| ADS | Average daily sales | units/day, per SKU × Store |
| LT  | Lead time (days) | per SKU × Store, **never** assumed |
| Price | Unit price/cost | optional; unlocks order values + savings |

**Derived values**

```
Pipeline      = SOH + QOO
Buffer        = ADS × LT × 1.5          (buffer factor, tunable)
ROP           = ADS × LT                (reorder point)
Days of Stock = Pipeline / ADS          (0 if ADS = 0)
Reorder Qty   = MAX(0, ROUNDUP(ADS × LT × 2.5 − SOH − QOO))
Transfer Qty  = MAX(0, MIN(donor.SOH − donor.Buffer, receiver.Buffer − receiver.Pipeline))
```

**Status** — evaluated in this exact order, first match wins:

| # | Condition | Status | |
|---|---|---|---|
| 1 | SOH = 0 and QOO = 0 | **OUT OF STOCK** | ⚫ |
| 2 | SOH = 0 and QOO > 0 | **INCOMING** | 🟣 |
| 3 | Pipeline < 0.5 × ROP | **CRITICAL** | 🔴 |
| 4 | Pipeline < ROP | **REORDER** | 🟡 |
| 5 | SOH > 2 × Buffer | **OVERSTOCK** | 🔵 |
| 6 | otherwise | **OPTIMAL** | 🟢 |

**Health Score** = optimal rows ÷ total rows. Target ≥ 70%; below 50% = same-day action.

Transfers are planned **before** fresh orders — moving overstock to a starved store
is faster than a supplier lead time and costs nothing new.

Full spec: [`skill/redpill-inventory/references/formulas.md`](skill/redpill-inventory/references/formulas.md).

---

## Use it as a Claude Skill

Red Pill is designed to run inside Claude. Once installed, just give Claude your MIS
file and say **"run red pill"** — it maps your columns, corrects the demand rate from
sales history, computes every status, and writes the report + demand plan.

**Install into Claude Code:**

```bash
# Personal skills live in ~/.claude/skills
mkdir -p ~/.claude/skills
cp -R skill/redpill-inventory ~/.claude/skills/
```

Then in Claude Code, ask: *"Run red pill on this stock report"* and attach a CSV/XLSX.

**Or hand over the packaged file** (`dist/redpill-inventory.skill`, produced by
`make build`) anywhere that accepts a `.skill` bundle.

**Triggers** — the skill activates on phrases like: *run redpill*, *red pill report*,
*stock health*, *which stores need stock*, *replenishment plan*, *stock transfer plan*,
*inventory health report*, *buffer status*, or any request to turn a `SKU × Store`
stock file into ordering/transfer decisions.

---

## Use the engine standalone (no AI)

The formula engine is pure Python (standard library only — no dependencies):

```bash
# 1. Get the required input format
python skill/redpill-inventory/scripts/redpill_engine.py --template
#    → writes redpill_input_template.csv

# 2. Run it on your data
python skill/redpill-inventory/scripts/redpill_engine.py examples/sample_mis.csv
```

Outputs:

- `computed.csv` — every row with pipeline, buffer, ROP, days-of-stock, status,
  reorder qty (gross + net of transfers), order value, expected delivery.
- `summary.json` — status counts, health score, urgency top-10, transfer plan, and
  a `data_quality` block (assumptions made, warnings, quarantined rows).
- `data_gaps.csv` — any rows with missing/bad data, quarantined with a reason each,
  pre-filled as a fix-and-rerun form (Red Pill **never** silently guesses).

Tunable flags: `--buffer-factor 1.5`, `--target-factor 2.5`, `--savings-rate 0.15`.

**Input columns** (case-insensitive; common aliases like *Closing Stock*, *In Transit*,
*Pending PO* are auto-mapped): `sku, store, soh, qoo, ads, lead_time[, unit_price]`.

---

## Editing the skill & keeping this repo in sync

**This repo is the source of truth.** There are two ways to make changes; both end in
a normal `git commit && git push`.

### A. Edit the files directly (recommended)

Edit anything under `skill/redpill-inventory/`, then:

```bash
make build     # repackages skill/ → dist/redpill-inventory.skill
git add -A && git commit -m "Update skill" && git push
```

### B. You edited the skill inside Claude and have a new `.skill`

If Claude produced an updated `redpill-inventory.skill` bundle, fold it back in:

```bash
make sync SKILL=~/Downloads/redpill-inventory.skill
#   → unpacks it into skill/redpill-inventory/, then `git diff` shows what changed
git add -A && git commit -m "Sync skill edits from Claude" && git push
```

> **Optional automation:** enable the included GitHub Action (see
> [CONTRIBUTING.md](CONTRIBUTING.md)) to rebuild `dist/redpill-inventory.skill`
> automatically on every push that touches `skill/`, so the packaged download is
> always current without you running `make build`.

---

## Contributing

Issues and PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the layout, the
build/sync commands, and the one rule that matters: **never store or trust derived
values — recompute from raw inputs every run.**

## License

[MIT](LICENSE) © 2026 Koushik
