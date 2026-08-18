#!/usr/bin/env python3
"""Red Pill domain stress pack — deterministic messy-MIS generator.

One deliberately filthy stock file per retail domain the /redpill:setup
question serves, so anyone can stress-test the full pipeline (mapping →
quarantine → ask-back → engine → cockpit) on data shaped like their own.
Grocery & pharmacy are deliberately ABSENT: SPEC §0 declares them non-goals
(expiry/substitution physics Red Pill does not model).

Every file differs on purpose:
  - header DIALECT (exercises the alias mapper: "Closing Stock" vs "SOH" vs
    "Qty On Hand", "Outlet" vs "Branch", "MRP" vs "Rate"...)
  - SKU convention, attribute columns, store count (8 → 50), SKU count
  - planted traps on deterministic row indices (currency strings, blanks,
    "7 days", N/A, negatives, duplicates, fractional units, padded numbers)
  - domain storylines: promo spikes, censored zero-weeks, understated ADS,
    volatile demand, dead stock, broken size curves, verify-first bait,
    disagreeing system-status columns, reserved/damaged/case packs, ETAs
  - one mega-scale file (~25k rows) and one corrupted file that SHOULD end
    in a BLOCKED verdict (banner row + junk headers) — failure is part of
    the demo.

Deterministic: same output every run (seeded per file; no time, no OS
randomness). Regenerate with:  python3 gen_stress_pack.py [outdir]
"""
import csv
import os
import random
import sys

AS_OF = "2026-08-17"   # suggested --as-of for engine runs on this pack

CITIES = ["Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Kolkata",
          "Pune", "Ahmedabad", "Jaipur", "Lucknow", "Surat", "Indore",
          "Nagpur", "Kochi", "Chandigarh", "Bhopal", "Patna", "Vadodara",
          "Ludhiana", "Agra", "Nashik", "Meerut", "Rajkot", "Varanasi",
          "Amritsar", "Noida", "Gurugram", "Coimbatore", "Madurai", "Guwahati"]
SUFFIX = ["Central", "City Mall", "High St", "Phoenix", "Forum", "Outlet",
          "Express", "Galleria", "Junction", "Arcade"]


def stores(rng, n, style):
    out = []
    i = 0
    while len(out) < n:
        c = CITIES[i % len(CITIES)]
        s = f"{c} {SUFFIX[(i // len(CITIES)) % len(SUFFIX)]}" if i >= len(CITIES) else c
        out.append({"city": s, "label": style(s)})
        i += 1
    return out


# ---------------------------------------------------------------- messiness
def fmt_money(rng, v):
    r = rng.random()
    if r < 0.30:
        return f"₹{v:,.0f}"
    if r < 0.45:
        return f"Rs. {v:,.0f}"
    if r < 0.55:
        return f"{v:,.2f}"
    return f"{v:.0f}"


def fmt_int(rng, v):
    r = rng.random()
    if v < 0:
        return f"({abs(v)})" if r < 0.5 else str(v)
    if r < 0.06:
        return f" {v} "
    if r < 0.10 and v >= 1000:
        return f"{v:,}"
    return str(v)


class Traps:
    """Deterministic trap injection + a ledger of what was planted."""

    def __init__(self):
        self.ledger = {}

    def hit(self, idx, every, name):
        if idx % every == (every // 2):
            self.ledger[name] = self.ledger.get(name, 0) + 1
            return True
        return False


# ---------------------------------------------------------------- domains
def hist_weeks(rng, base, promo_at=None, censored=False, volatile=False):
    """8 trailing weekly-unit columns, oldest first (wk8 ... wk1)."""
    out = []
    for w in range(8, 0, -1):
        if censored and w <= 2:
            out.append(0)
            continue
        if volatile:
            u = rng.choice([max(0, int(base * 0.2)), int(base * 2.2),
                            max(0, int(base * 0.4)), int(base * 1.8)])
        else:
            u = max(0, int(round(base * rng.uniform(0.75, 1.25))))
        if promo_at is not None and w == promo_at:
            u = int(u * 3.2)
        out.append(u)
    return out


def make_file(path, seed, headers, store_style, n_stores, skus, row_fn,
              history=None, dup_every=97):
    """Generic writer: skus is a list of dicts; row_fn(rng,sku,store,idx,traps)
    returns the value list matching `headers` (minus history columns)."""
    rng = random.Random(seed)
    sts = stores(rng, n_stores, store_style)
    traps = Traps()
    rows = []
    idx = 0
    for sku in skus:
        for st in sts:
            idx += 1
            rows.append(row_fn(rng, sku, st, idx, traps))
            if traps.hit(idx, dup_every, "duplicate row (same SKU+store)"):
                rows.append(rows[-1])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)
    return len(rows), traps.ledger


def base_values(rng, sku, st, idx, t, money_col=True):
    """Common numeric block with the shared trap schedule. Returns dict."""
    ads = round(rng.uniform(*sku["ads_range"]), 1)
    lt = rng.choice(sku["lt_choices"])
    soh = int(ads * lt * rng.uniform(0.0, 3.4))
    qoo = rng.choice([0, 0, 0, int(ads * lt * rng.uniform(0.4, 1.4))])
    price = sku["price"]

    v = {"soh": fmt_int(rng, soh), "qoo": fmt_int(rng, qoo) if qoo else "0",
         "ads": str(ads), "lt": str(lt),
         "price": fmt_money(rng, price) if money_col else f"{price:.0f}",
         "_soh_n": soh, "_ads_n": ads, "_lt_n": lt}

    if t.hit(idx, 89, "negative stock"):
        v["soh"] = fmt_int(rng, -rng.randint(1, 9))
    if t.hit(idx, 83, "blank daily-sales (blank ≠ zero)"):
        v["ads"] = ""
    if t.hit(idx, 79, 'lead time as text ("7 days")'):
        v["lt"] = f"{lt} days"
    if t.hit(idx, 73, "blank lead time"):
        v["lt"] = ""
    if t.hit(idx, 71, "negative on-order"):
        v["qoo"] = str(-rng.randint(1, 20))
    if t.hit(idx, 59, 'unreadable price ("N/A")'):
        v["price"] = "N/A"
    if t.hit(idx, 53, "fractional stock units"):
        v["soh"] = f"{soh}.5"
    if t.hit(idx, 101, "blank SKU code"):
        v["_blank_sku"] = True
    return v


def build_pack(outdir):
    os.makedirs(outdir, exist_ok=True)
    results = []

    # ---- 1. APPAREL — the tuned default; history + promo + censoring + curves
    styles = ["Crew Tee", "Polo", "Oxford Shirt", "Slim Jeans", "Chino",
              "Hoodie", "Bomber", "Kurta", "Blazer", "Track Pant"]
    colours = ["Black", "White", "Navy", "Olive", "Maroon"]
    sizes = ["S", "M", "L", "XL"]
    rng0 = random.Random(11)
    skus = []
    for s in styles:
        for c in colours[:3]:
            for z in sizes[:2 + (sum(map(ord, s + c)) % 3)]:
                skus.append({"sku": f"{s[:3].upper()}-{c[:3].upper()}-{z}",
                             "style": s, "colour": c, "size": z,
                             "ads_range": (0.5, 6), "lt_choices": [5, 7, 9, 12],
                             "price": rng0.choice([499, 799, 1299, 1999, 2499])})
    skus = skus[:120]
    H = ["SKU Code", "Store Name", "Closing Stock", "In Transit",
         "Avg Off-take/Day", "Lead Time (Days)", "MRP", "Style", "Colour",
         "Size", "System Status"] + [f"Sold Wk-{w}" for w in range(8, 0, -1)]

    def apparel_row(rng, sku, st, idx, t):
        v = base_values(rng, sku, st, idx, t)
        promo = 3 if idx % 41 == 20 else None
        cens = v["_soh_n"] == 0 and idx % 3 == 0
        under = idx % 37 == 18            # actual demand ≈ 2.5x stated
        base = v["_ads_n"] * 7 * (2.5 if under else 1.0)
        if under:
            t.ledger["understated ADS (history ≫ stated)"] = \
                t.ledger.get("understated ADS (history ≫ stated)", 0) + 1
        wk = hist_weeks(rng, base, promo, cens, volatile=(idx % 43 == 21))
        wrong = "OK" if idx % 31 == 15 else ""
        if wrong:
            t.ledger['wrong "System Status" column'] = \
                t.ledger.get('wrong "System Status" column', 0) + 1
        sys_status = wrong or rng.choice(["OK", "Reorder", "Excess", ""])
        return ["" if v.get("_blank_sku") else sku["sku"], st["label"],
                v["soh"], v["qoo"], v["ads"], v["lt"], v["price"],
                sku["style"], sku["colour"], sku["size"], sys_status] + wk

    n, ledger = make_file(os.path.join(outdir, "apparel_mis_messy.csv"), 11,
                          H, lambda s: s, 24, skus, apparel_row)
    results.append(("apparel_mis_messy.csv", "Apparel / lifestyle", 24, n, ledger))

    # ---- 2. FOOTWEAR — size runs everywhere; UK sizes; some sizes stripped
    rng0 = random.Random(22)
    models = ["Runner Flex", "Court Classic", "Trail Grip", "Loafer Prime",
              "Sandal Air", "Derby Craft", "Slip-On Ease", "Boot Rugged"]
    skus = []
    for m in models:
        for c in ["BLK", "WHT", "TAN"]:
            for z in ["UK6", "UK7", "UK8", "UK9", "UK10", "UK11"]:
                skus.append({"sku": f"FW-{m.split()[0][:4].upper()}-{c}-{z}",
                             "style": m, "colour": c, "size": z,
                             "ads_range": (0.2, 3), "lt_choices": [10, 14, 21],
                             "price": rng0.choice([1499, 2299, 3499, 4999])})
    skus = skus[:150]
    H = ["Article", "Branch", "Qty On Hand", "Open PO", "run_rate",
         "replenishment_days", "Rate", "Style", "Colour", "Size"]

    def foot_row(rng, sku, st, idx, t):
        v = base_values(rng, sku, st, idx, t)
        soh = v["soh"]
        if sku["size"] in ("UK8", "UK9") and idx % 23 == 11:   # break the curve
            soh = "0"
            t.ledger["broken size run (core size zeroed)"] = \
                t.ledger.get("broken size run (core size zeroed)", 0) + 1
        return ["" if v.get("_blank_sku") else sku["sku"], st["label"], soh,
                v["qoo"], v["ads"], v["lt"], v["price"],
                sku["style"], sku["colour"], sku["size"]]

    n, ledger = make_file(os.path.join(outdir, "footwear_mis_messy.csv"), 22,
                          H, lambda s: f"{s} Store", 30, skus, foot_row)
    results.append(("footwear_mis_messy.csv", "Footwear", 30, n, ledger))

    # ---- 3. ELECTRONICS — ETAs, case packs, overcommit bait, high value
    rng0 = random.Random(33)
    cats = [("PowerBank 10K", 1299), ("TWS Buds Pro", 2999), ("SmartWatch S", 4999),
            ("BT Speaker Mini", 1799), ("Cable USB-C 1m", 299), ("Charger 65W", 1599),
            ("Mouse Wireless", 899), ("Keyboard Mech", 3499)]
    skus = [{"sku": f"EL-{c[:3].upper().replace(' ', '')}-{i:03d}",
             "model": c, "ads_range": (0.3, 5), "lt_choices": [15, 20, 30],
             "price": p} for i, (c, p) in enumerate(
                 [(c, p) for c, p in cats for _ in range(10)], start=1)]
    H = ["Item Code", "Outlet", "stock_qty", "inbound", "daily_sales",
         "supplier_lead_time", "unit_cost", "Model", "Case Pack",
         "Expected Receipt Date"]

    def elec_row(rng, sku, st, idx, t):
        v = base_values(rng, sku, st, idx, t)
        qoo = v["qoo"]
        eta = ""
        if qoo not in ("0", "") and not qoo.startswith("-"):
            day = 3 + (idx % 40)
            eta = f"2026-08-{min(31, 17 + day % 14):02d}" if idx % 3 else \
                  f"2026-09-{(day % 27) + 1:02d}"
        if t.hit(idx, 47, "over-committed inbound (pipeline ≫ buffer)"):
            qoo = str(int(v["_ads_n"] * v["_lt_n"] * 6))
        return ["" if v.get("_blank_sku") else sku["sku"], st["label"],
                v["soh"], qoo, v["ads"], v["lt"], v["price"], sku["model"],
                rng.choice(["", "6", "12", "24"]), eta]

    n, ledger = make_file(os.path.join(outdir, "electronics_mis_messy.csv"), 33,
                          H, lambda s: s, 18, skus, elec_row)
    results.append(("electronics_mis_messy.csv", "Electronics & accessories", 18, n, ledger))

    # ---- 4. BEAUTY — fast movers, promo-heavy history, reserved online stock
    rng0 = random.Random(44)
    lines = ["Face Serum", "Vit-C Cream", "Sunscreen 50", "Shampoo Argan",
             "Kajal Deep", "Lip Tint", "Face Wash Neem", "Body Lotion",
             "Hair Oil Onion", "Perfume Musk"]
    shades = ["30ml", "50ml", "100ml", "200ml"]
    skus = [{"sku": f"BP-{l.split()[0][:4].upper()}-{s}", "model": l,
             "ads_range": (2, 14), "lt_choices": [4, 6, 8],
             "price": rng0.choice([199, 349, 499, 699, 999])}
            for l in lines for s in shades][:150]
    H = ["sku_id", "location", "shelf_stock", "qty_on_order", "avg_sales_day",
         "leadtime_days", "selling_price", "Line", "Online Reserved",
         "Damaged Stock"] + [f"wk{w}_sold" for w in range(8, 0, -1)]

    def beauty_row(rng, sku, st, idx, t):
        v = base_values(rng, sku, st, idx, t)
        promo = rng.choice([2, 3, 4]) if idx % 29 == 14 else None
        wk = hist_weeks(rng, v["_ads_n"] * 7, promo,
                        censored=(v["_soh_n"] == 0 and idx % 2 == 0))
        return ["" if v.get("_blank_sku") else sku["sku"], st["label"],
                v["soh"], v["qoo"], v["ads"], v["lt"], v["price"], sku["model"],
                rng.choice(["0", "0", "4", "12"]), rng.choice(["0", "0", "1", "3"])] + wk

    n, ledger = make_file(os.path.join(outdir, "beauty_mis_messy.csv"), 44,
                          H, lambda s: f"{s} Kiosk" if sum(map(ord, s)) % 4 == 0 else s,
                          36, skus, beauty_row)
    results.append(("beauty_mis_messy.csv", "Beauty & personal care", 36, n, ledger))

    # ---- 5. HOME & DECOR — slow movers, dead stock, zero-demand rows
    rng0 = random.Random(55)
    items = ["Cushion Velvet", "Vase Ceramic", "Wall Clock Oak", "Lamp Brass",
             "Rug Jute 4x6", "Planter Set", "Photo Frame A4", "Candle Soy",
             "Throw Blanket", "Mirror Round"]
    skus = [{"sku": f"HD-{i:03d}-{n_.split()[0][:4].upper()}", "model": n_,
             "ads_range": (0.0, 1.2), "lt_choices": [12, 18, 25],
             "price": rng0.choice([399, 799, 1499, 2999, 5999])}
            for i, n_ in enumerate([x for x in items for _ in range(7)], 1)]
    H = ["product_code", "site", "on_hand", "pending_po", "offtake",
         "lead_time_in_days", "asp", "Item"]

    def home_row(rng, sku, st, idx, t):
        v = base_values(rng, sku, st, idx, t)
        ads = v["ads"]
        if idx % 13 == 6:                                   # genuine zero demand
            ads = "0"
            t.ledger["zero-demand row (dead stock w/ shelf qty)"] = \
                t.ledger.get("zero-demand row (dead stock w/ shelf qty)", 0) + 1
        return ["" if v.get("_blank_sku") else sku["sku"], st["label"],
                v["soh"], v["qoo"], ads, v["lt"], v["price"], sku["model"]]

    n, ledger = make_file(os.path.join(outdir, "home_decor_mis_messy.csv"), 55,
                          H, lambda s: s, 12, skus, home_row)
    results.append(("home_decor_mis_messy.csv", "Home & decor", 12, n, ledger))

    # ---- 6. SPORTS — weekend-heavy volatility, per-row buffer factor column
    rng0 = random.Random(66)
    gear = ["Yoga Mat Pro", "Dumbbell 5kg", "Resistance Band", "Cricket Bat",
            "Football Sz5", "Skipping Rope", "Gym Gloves", "Shaker 700ml",
            "Badminton Racq"]
    skus = [{"sku": f"SP-{g.split()[0][:4].upper()}-{i:02d}", "model": g,
             "ads_range": (0.4, 6), "lt_choices": [7, 10, 14],
             "price": rng0.choice([299, 599, 999, 1899, 3499])}
            for i, g in enumerate([x for x in gear for _ in range(10)], 1)]
    H = ["item", "shop", "current_stock", "intransit", "avg_off_take_day",
         "lt", "price", "Gear", "bf"] + [f"Units Sold Week {w}" for w in range(8, 0, -1)]

    def sports_row(rng, sku, st, idx, t):
        v = base_values(rng, sku, st, idx, t)
        vol = idx % 17 == 8
        wk = hist_weeks(rng, v["_ads_n"] * 7, None, False, volatile=vol)
        if vol:
            t.ledger["volatile demand pattern"] = t.ledger.get("volatile demand pattern", 0) + 1
        return ["" if v.get("_blank_sku") else sku["sku"], st["label"],
                v["soh"], v["qoo"], v["ads"], v["lt"], v["price"], sku["model"],
                rng.choice(["", "", "", "2.0", "2.2"])] + wk

    n, ledger = make_file(os.path.join(outdir, "sports_mis_messy.csv"), 66,
                          H, lambda s: s, 20, skus, sports_row)
    results.append(("sports_mis_messy.csv", "Sports & fitness", 20, n, ledger))

    # ---- 7. BOOKS & STATIONERY — longest tail, tiny margins, many zero-movers
    rng0 = random.Random(77)
    skus = [{"sku": f"BK-{i:04d}", "model": f"Title #{i}",
             "ads_range": (0.0, 0.9), "lt_choices": [6, 9, 15],
             "price": rng0.choice([99, 149, 249, 399, 599])}
            for i in range(1, 201)]
    H = ["ISBN/SKU", "store", "closing_qty", "on_order", "sales_per_day",
         "leadtime", "mrp"]

    def book_row(rng, sku, st, idx, t):
        v = base_values(rng, sku, st, idx, t)
        return ["" if v.get("_blank_sku") else sku["sku"], st["label"],
                v["soh"], v["qoo"], v["ads"], v["lt"], v["price"]]

    n, ledger = make_file(os.path.join(outdir, "books_stationery_mis_messy.csv"), 77,
                          H, lambda s: s, 10, skus, book_row)
    results.append(("books_stationery_mis_messy.csv", "Books & stationery", 10, n, ledger))

    # ---- 8. JEWELLERY — high value, low velocity, verify-first bait
    rng0 = random.Random(88)
    pieces = ["Gold Chain 22K", "Silver Anklet", "Diamond Stud", "Pearl Set",
              "Kada Brass", "Nose Pin", "Tennis Bracelet", "Temple Necklace"]
    skus = [{"sku": f"JW-{p.split()[0][:4].upper()}-{i:02d}", "model": p,
             "ads_range": (0.05, 0.6), "lt_choices": [20, 30, 45],
             "price": rng0.choice([4999, 9999, 24999, 49999, 89999])}
            for i, p in enumerate([x for x in pieces for _ in range(6)], 1)]
    H = ["Design Code", "Showroom", "Stock", "Incoming", "Daily Sales",
         "Lead Time", "Tag Price"] + [f"Sold-W{w}" for w in range(8, 0, -1)]

    def jewel_row(rng, sku, st, idx, t):
        v = base_values(rng, sku, st, idx, t)
        soh, wk = v["soh"], hist_weeks(rng, max(0.3, v["_ads_n"]) * 7)
        if idx % 19 == 9:      # claims brisk sales, shelf never moved: verify!
            soh = str(int(max(1, v["_ads_n"]) * 7 * 16))
            wk = [int(max(1, v["_ads_n"] * 7 * 2.2))] * 8
            t.ledger["verify-first bait (stock ≫ claimed sales)"] = \
                t.ledger.get("verify-first bait (stock ≫ claimed sales)", 0) + 1
        return ["" if v.get("_blank_sku") else sku["sku"], st["label"],
                soh, v["qoo"], v["ads"], v["lt"], v["price"]] + wk

    n, ledger = make_file(os.path.join(outdir, "jewellery_mis_messy.csv"), 88,
                          H, lambda s: f"{s} Showroom", 8, skus, jewel_row)
    results.append(("jewellery_mis_messy.csv", "Jewellery & watches", 8, n, ledger))

    # ---- 9. MEGA MIX — scale stress: 500 SKUs × 50 stores ≈ 25k rows
    rng0 = random.Random(99)
    skus = [{"sku": f"MX-{i:04d}", "model": f"Item {i}",
             "ads_range": (0.2, 8), "lt_choices": [5, 7, 10, 14, 21],
             "price": rng0.choice([199, 499, 999, 1999, 3999])}
            for i in range(1, 501)]
    H = ["sku", "store", "soh", "qoo", "ads", "lead_time", "unit_price"]

    def mega_row(rng, sku, st, idx, t):
        v = base_values(rng, sku, st, idx, t, money_col=False)
        return ["" if v.get("_blank_sku") else sku["sku"], st["label"],
                v["soh"], v["qoo"], v["ads"], v["lt"], v["price"]]

    n, ledger = make_file(os.path.join(outdir, "mega_mix_mis.csv"), 99,
                          H, lambda s: s, 50, skus, mega_row)
    results.append(("mega_mix_mis.csv", "Mega mix (scale test)", 50, n, ledger))

    # ---- 10. CORRUPTED — banner row + junk: the run SHOULD be blocked
    path = os.path.join(outdir, "corrupted_mis.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ACME RETAIL PVT LTD — WEEKLY STOCK REPORT (CONFIDENTIAL)"])
        w.writerow(["Report Date:", AS_OF, "", "Prepared by:", "MIS Team"])
        w.writerow(["Product", "Qty", "Notes"])
        rng = random.Random(111)
        for i in range(1, 81):
            w.writerow([f"Item {i}", rng.choice(["some", "N/A", "-", str(rng.randint(0, 50))]),
                        rng.choice(["ok", "check", ""])])
    results.append(("corrupted_mis.csv", "Corrupted (blocked-verdict demo)", 0, 83,
                    {"banner rows above headers": 2, "no usable columns": 1}))

    return results


if __name__ == "__main__":
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    res = build_pack(outdir)
    print(f"{'file':38s} {'rows':>6s}  traps")
    for name, dom, nst, n, ledger in res:
        print(f"{name:38s} {n:>6d}  {sum(ledger.values())} planted "
              f"({len(ledger)} kinds) · {nst} stores · {dom}")
