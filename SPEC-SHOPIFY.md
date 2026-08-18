# Red Pill for Shopify — S-track specification

> The Sunday MIS Excel replaced by a Shopify connector; everything downstream unchanged.
> This is an **intake swap, not a product fork**: the deterministic engine, cockpit, trust
> layer, and advisory boundary ship exactly as they are. Governance: this track is NOT the
> SaaS fork — no server, no persistence beyond the user's machine, no execution, so the
> fork gates (roadmap #48 paid pilots / #61 kill criteria) remain closed and untouched.
> A public App Store listing would be a separate decision and triggers the rename gate (#44).
>
> UX + strategy artifact: https://claude.ai/code/artifact/068ce71e-d61f-4cd3-993c-830c07623f31

## 0. Boundaries (inherit SPEC §0, plus)

- **Read-only in v1.** The adapter reads Shopify; it never mutates it. The only write ever
  contemplated (lead-time metafields, S2) is approval-gated and deferrable.
- **Engine owns all numbers** — the adapter maps and normalizes; it never derives a business
  figure. Derived demand (S1) is raw arithmetic on order rows, emitted as *input* columns
  (`sold_wk_N`), which the existing demand module then analyzes.
- **The pulled snapshot is the immutable run input** — same reproducibility contract as an
  uploaded Excel (G32): `--rerun` replays byte-identical from the stored snapshot.
- Tokens live in a local file, never in chat, never in the repo.

## 1. Field mapping (Shopify → existing engine contract)

| Engine field | Shopify source | Note |
|---|---|---|
| `sku` | ProductVariant.sku | variant granularity preserved |
| `store` | Location.name | native multi-location |
| `soh` | inventory quantity `on_hand` | physical units |
| `reserved` | `committed` + `reserved` states | ATP/G26 becomes default-on |
| `damaged` | quality-control states | when tracked |
| `qoo` | `incoming` quantity | open POs + inbound transfers |
| `expected_receipt_date` | transfer/PO expected arrival (v0: `redpill.next_receipt_date` metafield) | powers G34/G36 |
| `price` | variant price | order values, ₹-at-risk |
| `sold_wk_1..8` | Orders API trailing 8 weeks (S1) | demand module runs on real history |
| `lead_time` | **absent in Shopify** → `redpill.lead_time_days` metafield → vendor default (`leadtimes.json`) → quarantine + ask-back | the one missing input |
| stated ADS | `redpill.stated_ads` metafield, else blank (quarantine) / last derived rate (S1+) | keeps deviation checks meaningful |
| `style/colour/size` | product title + variant selectedOptions | size-curve intelligence (G21) native |

Skipped with counts (never silently): archived products, untracked inventory items.
Passed through for quarantine (never guessed): blank SKUs, negative quantities.

## 2. Gap register — S-track (continues G38)

| # | Gap | Phase | Status |
|---|---|---|---|
| G39 | Snapshot contract: deterministic pull → normalized CSV + `pull-manifest.json` (API version, query sha-256, pulled_at, row counts, artifact checksums); recorded-JSONL replay fixtures; live and replay modes share one normalizer | S0 | in progress |
| G40 | Mapping & provenance: every CSV column traceable to its API path (`adapter-provenance.json`); quarantine analogs: blank SKU, negative quantities pass through to engine quarantine; archived/untracked skipped with counts | S0 | in progress |
| G41 | Demand from orders: trailing 8 weeks → `sold_wk_N` per variant×location; returns excluded + disclosed; discount/price-rule windows auto-suggested as promo weeks (confirm-only, G18 discipline) | S1 | open |
| G42 | Lead-time layer: metafield read; vendor defaults; ask-back candidates from vendor siblings; answers persist locally across pulls; metafield write-back approval-gated or deferred | S2 | open |
| G43 | Freshness semantics: "pulled at HH:MM TZ" stamp; staleness warning when acting on an old pull; pull-vs-act drift disclosed | S3 | open |
| G44 | Scale honesty: Bulk Operation lifecycle (submit/poll/download), rate-limit backoff with disclosed waits, multi-currency normalization, partial pull ⇒ run verdict degraded/blocked (extends G7 to the intake) | S4 | open |
| G45 | Release: adapter goldens in CI beside (never inside) the engine suite; ten-point gate run on both intakes; docs in the plain-language voice | S5 | open |

## 3. Build plan

Phase discipline unchanged: **dry run → Observations entry → fixed → re-run clean → gate.**

- **S0 — Adapter truth** *(G39/G40)*: `scripts/shopify_snapshot.py` (stdlib), deterministic
  fixture generator (`tests/fixtures/gen_shopify_fixture.py`), adapter golden tests.
  **Exit:** byte-identical normalization from recorded fixtures; provenance per field;
  engine suite untouched and green.
- **S1 — Demand from orders** *(G41)*. **Exit:** derived weekly history pinned by tests;
  censoring verified on a fixture with real zero-sale gaps.
- **S2 — Lead times & the closed loop** *(G42)*. **Exit:** zero-lead-time store goes
  quarantine → one-tap answers → healthy; answers survive the next pull.
- **S3 — Command & UX** *(G43)*: `/redpill:shopify` = pull + run + cockpit; docs; live-pull
  validation against a real dev store. **Exit:** five-phrasing trigger eval.
- **S4 — Scale & realism** *(G44)*. **Exit:** synthetic 50k-variant × 20-location store
  within stated time budget; honest verdicts throughout.
- **S5 — Release** *(G45)*: one plugin, two intakes (Excel or Shopify), one engine.

## 4. Ecosystem expansion (after Shopify, ranked)

1. **Shopify + POS** — this track; closest ICP match (3–20 physical stores).
2. **BigCommerce** — native multi-location API; cleanest second adapter.
3. **WooCommerce** — huge long tail; replenishment-first (no core multi-location).
4. **India aggregators (Unicommerce / EasyEcom / Increff)** — highest ICP overlap; partner-shaped.
5. **Zoho Inventory / Commerce** — India SMB, clean APIs.
6. **Magento / Adobe Commerce MSI** — enterprise, heavier lift, later.
7. **Amazon SP-API (FBA)** — different slice ("how much to send Amazon, when"); no transfers.
— Wix / Squarespace: skip (weak inventory APIs, single-location).
