#!/usr/bin/env python3
"""Deterministic Shopify Bulk-Operation JSONL fixture (S0, G39/G40).

Emulates the JSONL a Shopify Admin GraphQL Bulk Operation emits for the
redpill snapshot query: Location / Product / ProductVariant / Metafield /
InventoryLevel lines, children linked via __parentId, __typename requested
explicitly. Storyline (mirrors the stress-file discipline):

  - 3 locations, 6 products, 10 variants; 8 active+tracked variants x 3
    locations = 24 candidate rows.
  - All six statuses appear; 3 transfers arise (TEE-M 18, TEE-L 8, CHN 9).
  - Quarantine analogs: blank SKU (x3 rows), missing lead time (jogger, x6),
    negative on_hand (chino Pune, x1)  -> 14 processed / 10 quarantined.
  - Skipped-with-counts: 1 untracked item (cap), 1 archived product (old tee).
  - reserved/committed/damaged on the Mumbai tee donor exercises ATP (G26).
  - Delhi tee: incoming 40 with a receipt date 10d out (> LT 7) -> G34/G36.

Usage: python3 gen_shopify_fixture.py OUTDIR   -> OUTDIR/shopify_bulk_v1.jsonl
"""
import json
import os
import sys

LOC = {
    "mum": ("gid://shopify/Location/1", "Mumbai Flagship"),
    "pun": ("gid://shopify/Location/2", "Pune Kurla"),
    "del": ("gid://shopify/Location/3", "Delhi CP"),
}

PULLED_AT = "2026-08-14T09:00:00+05:30"   # fixture's canonical pull moment
RECEIPT_DATE = "2026-08-24"               # 10 days out; tee lead time is 7


def q(on=None, inc=0, com=0, res=0, dam=0):
    out = []
    if on is not None:
        out.append({"name": "on_hand", "quantity": on})
    out += [{"name": "incoming", "quantity": inc},
            {"name": "committed", "quantity": com},
            {"name": "reserved", "quantity": res},
            {"name": "damaged", "quantity": dam}]
    return out


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(outdir, exist_ok=True)
    lines = []

    for _, (gid, name) in sorted(LOC.items()):
        lines.append({"__typename": "Location", "id": gid, "name": name})

    pid = iter(range(101, 200))
    vid = iter(range(1001, 1200))
    iid = iter(range(2001, 2200))
    lid = iter(range(3001, 3400))

    def product(title, vendor, status="ACTIVE"):
        g = f"gid://shopify/Product/{next(pid)}"
        lines.append({"__typename": "Product", "id": g, "title": title,
                      "vendor": vendor, "status": status})
        return g

    def variant(parent, sku, price, size=None, colour=None, tracked=True,
                lead=None, stated_ads=None, receipt=None):
        g = f"gid://shopify/ProductVariant/{next(vid)}"
        opts = []
        if size is not None:
            opts.append({"name": "Size", "value": size})
        if colour is not None:
            opts.append({"name": "Color", "value": colour})
        lines.append({"__typename": "ProductVariant", "id": g, "sku": sku,
                      "price": price, "selectedOptions": opts,
                      "inventoryItem": {"id": f"gid://shopify/InventoryItem/{next(iid)}",
                                        "tracked": tracked},
                      "__parentId": parent})
        for key, value in (("lead_time_days", lead), ("stated_ads", stated_ads),
                           ("next_receipt_date", receipt)):
            if value is not None:
                lines.append({"__typename": "Metafield", "namespace": "redpill",
                              "key": key, "value": str(value), "__parentId": g})
        return g

    def level(parent, loc, **kw):
        lines.append({"__typename": "InventoryLevel",
                      "id": f"gid://shopify/InventoryLevel/{next(lid)}",
                      "location": {"id": LOC[loc][0]},
                      "quantities": q(**kw), "__parentId": parent})

    # 1. Crew Tee Black — metafield lead time 7, the transfer storyline
    tee = product("Crew Tee Black", "Arrow Apparel")
    s = variant(tee, "TEE-CRW-BLK-S", "799.00", "S", "Black", lead=7, stated_ads=1.5)
    level(s, "mum", on=30, com=2); level(s, "pun", on=8); level(s, "del", on=12)
    m = variant(tee, "TEE-CRW-BLK-M", "799.00", "M", "Black", lead=7, stated_ads=2,
                receipt=RECEIPT_DATE)
    level(m, "mum", on=120, com=8, res=4, dam=2)      # overstock donor, ATP bites
    level(m, "pun", on=3)                              # critical receiver
    level(m, "del", on=0, inc=40)                      # incoming, receipt later than LT
    l = variant(tee, "TEE-CRW-BLK-L", "799.00", "L", "Black", lead=7, stated_ads=1)
    level(l, "mum", on=25); level(l, "pun", on=2); level(l, "del", on=9)

    # 2. Oxford Shirt White — vendor-default lead time; one variant with a blank SKU
    oxf = product("Oxford Shirt White", "Weave & Co")
    om = variant(oxf, "OXF-SHT-WHT-M", "1299.00", "M", "White", stated_ads=1.5)
    level(om, "mum", on=18); level(om, "pun", on=5); level(om, "del", on=0)
    ol = variant(oxf, "", "1299.00", "L", "White")     # blank sku -> quarantine x3
    level(ol, "mum", on=10); level(ol, "pun", on=7); level(ol, "del", on=4)

    # 3. Jogger Grey — no lead time anywhere -> quarantine + ask-back storyline
    jog = product("Jogger Grey", "NoName Mills")
    jm = variant(jog, "JOG-GRY-M", "1599.00", "M", "Grey", stated_ads=3)
    level(jm, "mum", on=22); level(jm, "pun", on=6); level(jm, "del", on=15)
    jl = variant(jog, "JOG-GRY-L", "1599.00", "L", "Grey", stated_ads=2.5)
    level(jl, "mum", on=14); level(jl, "pun", on=9); level(jl, "del", on=11)

    # 4. Chino Khaki 32 — vendor-default lead time; Pune count has gone negative
    chn = product("Chino Khaki 32", "Weave & Co")
    cv = variant(chn, "CHN-KHK-32", "1499.00", "32", "Khaki", stated_ads=1)
    level(cv, "mum", on=30); level(cv, "pun", on=-6); level(cv, "del", on=4)

    # 5. Cap Classic — inventory not tracked -> skipped, counted
    cap = product("Cap Classic", "Arrow Apparel")
    cvr = variant(cap, "CAP-CLS-OS", "499.00", "OS", "Black", tracked=False, stated_ads=1)
    level(cvr, "mum", on=50)

    # 6. Old Tee — archived -> skipped, counted
    old = product("Old Tee", "Arrow Apparel", status="ARCHIVED")
    ov = variant(old, "OLD-TEE-M", "299.00", "M", "Black", lead=7, stated_ads=1)
    level(ov, "mum", on=80)

    path = os.path.join(outdir, "shopify_bulk_v1.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for ln in lines:
            f.write(json.dumps(ln, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"{path}: {len(lines)} lines · pulled_at fixture constant {PULLED_AT}")


if __name__ == "__main__":
    main()
