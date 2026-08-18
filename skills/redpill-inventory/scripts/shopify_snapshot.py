#!/usr/bin/env python3
"""Red Pill for Shopify — snapshot adapter (S-track S0, gaps G39/G40).

Turns a Shopify Admin GraphQL Bulk Operation result (JSONL) into the exact
MIS CSV contract the engine already accepts — an INTAKE SWAP, not a fork.
The adapter maps and normalizes; it never derives a business figure
(SPEC-SHOPIFY §0). Read-only: nothing here writes to Shopify.

Modes:
  replay (default, deterministic, tested):
      python3 shopify_snapshot.py --from-jsonl bulk.jsonl --out-dir DIR \
          --pulled-at 2026-08-14T09:00:00+05:30 [--leadtimes leadtimes.json]
  live (S3 validation; requires a store + token, refuses otherwise):
      python3 shopify_snapshot.py --shop my-store.myshopify.com \
          --token-file ~/.redpill/shopify_token --out-dir DIR

Outputs in --out-dir:
  shopify_mis.csv            normalized rows (engine-ready; sorted, stable)
  pull-manifest.json         api version, query sha-256, pulled_at, counts,
                             artifact checksums (G39)
  adapter-provenance.json    every CSV column -> its Shopify source path (G40)

Row policy (G40): blank SKUs, negative quantities, and missing lead times are
PASSED THROUGH so the engine's quarantine + ask-back own them (never guessed
here). Archived products and untracked inventory items are SKIPPED WITH COUNTS
— skipping silently would violate the no-silent-caps rule.
"""
import argparse
import csv
import hashlib
import json
import os
import sys

API_VERSION = "2026-07"

# The live-mode bulk query. Replay fixtures emulate its JSONL shape; the query
# text is hashed into the manifest either way so a run records what it asked.
BULK_QUERY = """
{
  locations { edges { node { id name } } }
  products {
    edges { node {
      id title vendor status
      variants { edges { node {
        id sku price
        selectedOptions { name value }
        inventoryItem { id tracked
          inventoryLevels { edges { node {
            id location { id }
            quantities(names: ["on_hand","incoming","committed","reserved","damaged"]) {
              name quantity }
          } } }
        }
        metafields(namespace: "redpill") { edges { node { namespace key value } } }
      } } }
    } }
  }
}
""".strip()

CSV_FIELDS = ["sku", "store", "soh", "qoo", "ads", "lead_time", "unit_price",
              "reserved", "damaged", "expected_receipt_date",
              "style", "colour", "size", "vendor"]

PROVENANCE = {
    "sku": "ProductVariant.sku (blank passes through -> engine quarantine)",
    "store": "InventoryLevel.location -> Location.name",
    "soh": "quantities['on_hand'] (negative passes through -> engine quarantine)",
    "qoo": "quantities['incoming'] (open POs + inbound transfers)",
    "ads": "variant metafield redpill.stated_ads | blank -> engine quarantine "
           "(flat per variant until S1 derives per-location rates from orders)",
    "lead_time": "variant metafield redpill.lead_time_days | vendor default "
                 "(leadtimes.json) | blank -> engine quarantine + ask-back",
    "unit_price": "ProductVariant.price",
    "reserved": "quantities['committed'] + quantities['reserved'] (feeds sellable/ATP, G26)",
    "damaged": "quantities['damaged']",
    "expected_receipt_date": "variant metafield redpill.next_receipt_date "
                             "(v0 simplification; PO/transfer ETAs in a later phase)",
    "style": "Product.title", "colour": "selectedOptions['Color']",
    "size": "selectedOptions['Size']", "vendor": "Product.vendor",
}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_jsonl(path):
    """Group bulk JSONL lines by __typename, preserving file order."""
    groups = {"Location": [], "Product": [], "ProductVariant": [],
              "Metafield": [], "InventoryLevel": []}
    with open(path, encoding="utf-8") as f:
        for n, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            obj = json.loads(raw)
            t = obj.get("__typename")
            if t not in groups:
                raise SystemExit(f"line {n}: unknown __typename {t!r} — "
                                 f"snapshot format drifted; refusing to guess (G40)")
            groups[t].append(obj)
    return groups


def qty(level, name):
    for entry in level.get("quantities", []):
        if entry.get("name") == name:
            return entry.get("quantity")
    return None


def normalize(groups, leadtimes):
    locations = {l["id"]: l.get("name", "") for l in groups["Location"]}
    products = {p["id"]: p for p in groups["Product"]}
    meta = {}
    for m in groups["Metafield"]:
        if m.get("namespace") == "redpill":
            meta.setdefault(m["__parentId"], {})[m["key"]] = m["value"]

    counts = {"locations": len(locations), "products": len(products),
              "variants": len(groups["ProductVariant"]),
              "levels": len(groups["InventoryLevel"]),
              "skipped_archived_variants": 0, "skipped_untracked_variants": 0,
              "rows": 0, "unknown_location_levels": 0}

    variants = {}
    for v in groups["ProductVariant"]:
        prod = products.get(v.get("__parentId"), {})
        if prod.get("status") == "ARCHIVED":
            counts["skipped_archived_variants"] += 1
            continue
        if not (v.get("inventoryItem") or {}).get("tracked", False):
            counts["skipped_untracked_variants"] += 1
            continue
        opts = {o["name"]: o["value"] for o in v.get("selectedOptions", [])}
        mf = meta.get(v["id"], {})
        lead = mf.get("lead_time_days", "")
        if lead == "" and prod.get("vendor") in leadtimes:
            lead = leadtimes[prod["vendor"]]
        variants[v["id"]] = {
            "sku": (v.get("sku") or "").strip(),
            "price": v.get("price", ""),
            "style": prod.get("title", ""), "vendor": prod.get("vendor", ""),
            "size": opts.get("Size", ""), "colour": opts.get("Color", ""),
            "ads": mf.get("stated_ads", ""), "lead_time": lead,
            "receipt": mf.get("next_receipt_date", ""),
        }

    rows = []
    for lvl in groups["InventoryLevel"]:
        v = variants.get(lvl.get("__parentId"))
        if v is None:
            continue                        # level of a skipped variant
        loc = locations.get((lvl.get("location") or {}).get("id"))
        if loc is None:
            counts["unknown_location_levels"] += 1
            continue
        committed = qty(lvl, "committed") or 0
        reserved_q = qty(lvl, "reserved") or 0
        on_hand = qty(lvl, "on_hand")
        incoming = qty(lvl, "incoming")
        rows.append({
            "sku": v["sku"], "store": loc,
            "soh": "" if on_hand is None else on_hand,
            "qoo": "" if incoming is None else incoming,
            "ads": v["ads"], "lead_time": v["lead_time"],
            "unit_price": v["price"],
            "reserved": committed + reserved_q,
            "damaged": qty(lvl, "damaged") or 0,
            "expected_receipt_date": v["receipt"] if (incoming or 0) > 0 else "",
            "style": v["style"], "colour": v["colour"], "size": v["size"],
            "vendor": v["vendor"],
        })
    rows.sort(key=lambda r: (str(r["sku"]).lower(), str(r["store"]).lower()))
    counts["rows"] = len(rows)
    return rows, counts


def run_replay(args):
    leadtimes = {}
    if args.leadtimes and os.path.exists(args.leadtimes):
        with open(args.leadtimes, encoding="utf-8") as f:
            leadtimes = json.load(f)
    groups = parse_jsonl(args.from_jsonl)
    rows, counts = normalize(groups, leadtimes)

    os.makedirs(args.out_dir, exist_ok=True)
    csv_path = os.path.join(args.out_dir, "shopify_mis.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)

    prov_path = os.path.join(args.out_dir, "adapter-provenance.json")
    with open(prov_path, "w", encoding="utf-8") as f:
        json.dump(PROVENANCE, f, indent=2, sort_keys=True)
        f.write("\n")

    manifest = {
        "source": "shopify", "mode": "jsonl-replay",
        "api_version": API_VERSION,
        "shop": args.shop or "(replay)",
        "pulled_at": args.pulled_at,
        "query_sha256": hashlib.sha256(BULK_QUERY.encode()).hexdigest(),
        "leadtimes_file": bool(leadtimes),
        "counts": counts,
        "sha256": {"input_jsonl": sha256_file(args.from_jsonl),
                   "shopify_mis.csv": sha256_file(csv_path)},
    }
    man_path = os.path.join(args.out_dir, "pull-manifest.json")
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"normalized {counts['rows']} rows -> {csv_path}")
    print(f"skipped: {counts['skipped_archived_variants']} archived variant(s), "
          f"{counts['skipped_untracked_variants']} untracked variant(s) — counted, never silent")
    print(f"manifest -> {man_path}")
    return manifest


def run_live(args):
    # Live pull (S3 validation): submit bulkOperationRunQuery, poll, download
    # the JSONL, then reuse the exact replay path. Deliberately minimal here —
    # tests never touch the network; a real dev store exercises this in S3.
    sys.exit("live mode lands with S3 validation — pull the bulk JSONL from a "
             "dev store and use --from-jsonl for now (replay and live share "
             "the same normalizer by design, G39)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--from-jsonl", help="recorded Bulk Operation JSONL (replay mode)")
    p.add_argument("--out-dir", default=".")
    p.add_argument("--pulled-at", default=None,
                   help="ISO timestamp of the pull; REQUIRED in replay mode so "
                        "runs stay reproducible (G39)")
    p.add_argument("--leadtimes", help="leadtimes.json: {vendor: days} defaults (G42-lite)")
    p.add_argument("--shop", help="my-store.myshopify.com (live mode)")
    p.add_argument("--token-file", help="file containing an Admin API token (live mode)")
    args = p.parse_args()

    if args.from_jsonl:
        if not args.pulled_at:
            sys.exit("--pulled-at is required in replay mode: a snapshot without "
                     "its pull moment is not reproducible (G39)")
        run_replay(args)
    elif args.shop or args.token_file:
        run_live(args)
    else:
        sys.exit("nothing to do: --from-jsonl (replay) or --shop + --token-file (live)")


if __name__ == "__main__":
    main()
