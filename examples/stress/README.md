# Domain stress pack — messy MIS files for every retail type

One deliberately messy stock file per retail domain that `/redpill:setup` serves, so
anyone can stress-test the full pipeline — mapping → quarantine → ask-back → engine →
cockpit — on data shaped like their own. Every file is **mostly right on purpose**:
roughly 92% of rows are clean, honest retail data; the planted traps sit on
deterministic row schedules so the same problems appear in the same places every time.
Grocery & pharmacy are deliberately absent: SPEC §0 declares them non-goals (expiry /
substitution physics Red Pill does not model).

## How to use

Drop any file into a conversation and say "run redpill on this", or run the engine
directly:

```bash
python3 skills/redpill-inventory/scripts/redpill_engine.py examples/stress/apparel_mis_messy.csv --as-of 2026-08-17 --run-dir /tmp/redpill_stress_run
```

Use `--as-of 2026-08-17` — the electronics ETAs and demand storylines are anchored to
that date. Every file also exists as an `.xlsx` workbook beside its CSV (same data,
same traps — verified cell-for-cell; the engine produces identical results from
either). Regenerate the whole pack (CSVs byte-identical, seeded, no OS randomness)
with:

```bash
python3 examples/stress/gen_stress_pack.py
```

```bash
python3 examples/stress/make_xlsx_pack.py
```

## The files

| File | Domain | Stores | Rows | Verdict (engine 2.4.1) | Quarantined |
|---|---|---:|---:|---|---:|
| `apparel_mis_messy.csv` | Apparel / lifestyle (the tuned default) | 24 | 2,328 | HEALTHY | 194 (8.3%) |
| `footwear_mis_messy.csv` | Footwear | 30 | 4,365 | HEALTHY | 349 (8.0%) |
| `electronics_mis_messy.csv` | Electronics & accessories | 18 | 1,455 | HEALTHY | 120 (8.2%) |
| `beauty_mis_messy.csv` | Beauty & personal care | 36 | 1,455 | HEALTHY | 253 (17.4%) |
| `home_decor_mis_messy.csv` | Home & decor | 12 | 849 | DEGRADED (by design — see below) | 70 (8.2%) |
| `sports_mis_messy.csv` | Sports & fitness | 20 | 1,819 | HEALTHY | 152 (8.4%) |
| `books_stationery_mis_messy.csv` | Books & stationery | 10 | 2,021 | HEALTHY | 167 (8.3%) |
| `jewellery_mis_messy.csv` | Jewellery & watches | 8 | 388 | HEALTHY | 32 (8.2%) |
| `mega_mix_mis.csv` | Mega mix — scale test | 50 | 25,258 | HEALTHY (~2.6 s) | 2,038 (8.1%) |
| `corrupted_mis.csv` | Corrupted — refusal demo | — | 83 | **Refuses to run** | — |

Every file uses a different header dialect on purpose ("Closing Stock" vs "Qty On
Hand" vs "shelf_stock"; "Outlet" vs "Branch" vs "Showroom"; "MRP" vs "Rate" vs
"Tag Price") to exercise the alias mapper, plus a different SKU convention and store
count. Shared traps on all files: currency strings (₹ / Rs. / commas), padded numbers,
accountant-style negatives `(500)`, blank ADS (blank ≠ zero), lead times as text
("7 days"), blank lead times, negative stock and on-order, "N/A" prices, fractional
units, blank SKUs, occasional duplicate rows.

## What each file is testing

- **Apparel** — promo-spike weeks, censored zero-sale weeks on stockouts, understated
  stated ADS (history ≈ 2.5× the claim → deviation checks), volatile rows, a lying
  "System Status" column the engine must ignore, size/colour attributes for size-curve
  intelligence.
- **Footwear** — size runs everywhere (UK6–UK11); core sizes (UK8/UK9) zeroed on a
  schedule to break curves; the longest lead times.
- **Electronics** — inbound with expected receipt dates (G34/G36 timing honesty),
  case packs, over-committed inbound (pipeline ≫ buffer), high-value units.
- **Beauty** — fast movers, promo-heavy history, reserved-online and damaged stock
  columns (ATP), kiosk-style location names.
- **Home & decor** — slow movers and genuine dead stock (zero demand with shelf
  quantity). Its `product_code` + `Item` headers both plausibly mean "sku": the engine
  now picks `product_code`, discloses the ambiguity, and **honestly degrades the
  verdict** — "confirm before trusting". That disclosure *is* the test.
- **Sports** — weekend-volatile demand (CV checks), a per-row buffer-factor column,
  minimal header dialect.
- **Books & stationery** — 200-SKU long tail, tiny margins, many near-zero movers;
  `ISBN/SKU` header dialect.
- **Jewellery** — high value, low velocity, 45-day lead times; verify-first bait rows
  (stock claims ≫ sales history: check the shelf before trusting the file).
- **Mega mix** — 500 SKUs × 50 stores ≈ 25k rows; scale + runtime honesty.
- **Corrupted** — company banner rows above junk headers, no usable columns. The right
  answer is a refusal with a mapping report and a fill-in template, **not** a guess.
  Failure is part of the demo.

## Provenance

This pack found real weaknesses on its first dry run — the mapper preferred a generic
`Item` column over `product_code` for sku (86% false quarantine on home & decor), and
`ISBN/SKU` / `Design Code` / `Showroom` / `Incoming` / `Tag Price` were unmapped —
fixed as engine 2.4.1 (alias hardening; golden re-pinned, business figures verified
byte-identical). That is exactly what it exists to do.
