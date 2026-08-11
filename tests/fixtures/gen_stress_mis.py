#!/usr/bin/env python3
"""Deterministic stress-MIS generator (fixtures for the Red Pill test suite).

Writes two files into the directory given as argv[1] (default: cwd):

  stress_mis_v1.csv  — the original 361-row messy MIS (seed=7). BYTE-IDENTICAL
                       to the first dry run's stress_mis_raw.csv; the SPEC §1
                       reference numbers are asserted against this file.
  stress_mis_v2.csv  — v1 rows + 3 extra columns (Reserved Qty / Damaged Qty /
                       Case Pack) + 6 deterministic storyline rows (G9):
                       pipeline-overcommit, stockout-censored sales, implausible
                       sales-vs-stock, promo spike, lane-gate receiver (LT <=
                       truck time), case-pack/reserved/damaged row. The extra
                       rows use NO randomness, so v1 bytes never change.

Storyline intent markers live in comments here, not in the data — the engine
must find them, not be told.
"""
import csv
import random
import sys

random.seed(7)
BF = 1.5

STORES = [
    ("Mumbai - Andheri", 1.35, 4), ("Delhi (CP)", 1.28, 6), ("Bengaluru", 1.22, 7),
    ("Hyderabad", 1.05, 7), ("Pune", 0.98, 5), ("Chennai", 0.92, 9),
    ("Kolkata", 0.82, 11), ("Ahmedabad", 0.78, 6), ("Jaipur", 0.72, 8),
    ("Lucknow", 0.68, 10), ("Kochi", 0.75, 12), ("Chandigarh", 0.85, 7),
]

SKUS = [
    ("TSH-CRW-BLK-M", "Crew Neck T-Shirt", "Tops", "Black", "M", 799, 10, 0),
    ("TSH-CRW-WHT-L", "Crew Neck T-Shirt", "Tops", "White", "L", 799, 8, 0),
    ("TSH-CRW-NVY-S", "Crew Neck T-Shirt", "Tops", "Navy", "S", 799, 6, 0),
    ("TSH-CRW-GRN-XL", "Crew Neck T-Shirt", "Tops", "Green", "XL", 799, 5, 0),
    ("POL-TSH-RED-M", "Polo T-Shirt", "Tops", "Red", "M", 1199, 7, 0),
    ("POL-TSH-GRN-L", "Polo T-Shirt", "Tops", "Green", "L", 1199, 5, 0),
    ("POL-TSH-NVY-S", "Polo T-Shirt", "Tops", "Navy", "S", 1199, 5, 0),
    ("JNS-SLM-IND-32", "Slim Fit Jeans", "Bottoms", "Indigo", "32", 2499, 6, 1),
    ("JNS-SLM-BLK-34", "Slim Fit Jeans", "Bottoms", "Black", "34", 2499, 4, 1),
    ("JNS-SLM-IND-30", "Slim Fit Jeans", "Bottoms", "Indigo", "30", 2499, 4, 1),
    ("CHN-TRS-KHK-32", "Chino Trousers", "Bottoms", "Khaki", "32", 1799, 4, 1),
    ("CHN-TRS-NVY-34", "Chino Trousers", "Bottoms", "Navy", "34", 1799, 3, 1),
    ("CHN-TRS-OLV-30", "Chino Trousers", "Bottoms", "Olive", "30", 1799, 3, 1),
    ("SHT-OXF-BLU-M", "Oxford Shirt", "Shirts", "Blue", "M", 1899, 4, 0),
    ("SHT-OXF-WHT-L", "Oxford Shirt", "Shirts", "White", "L", 1899, 4, 0),
    ("SHT-OXF-PNK-M", "Oxford Shirt", "Shirts", "Pink", "M", 1899, 3, 0),
    ("SWT-HOD-GRY-M", "Hooded Sweatshirt", "Outerwear", "Grey", "M", 2199, 5, 1),
    ("SWT-HOD-BLK-XL", "Hooded Sweatshirt", "Outerwear", "Black", "XL", 2199, 4, 1),
    ("SWT-HOD-NVY-L", "Hooded Sweatshirt", "Outerwear", "Navy", "L", 2199, 4, 1),
    ("JKT-DNM-BLU-M", "Denim Jacket", "Outerwear", "Blue", "M", 3499, 3, 2),
    ("JKT-DNM-BLU-L", "Denim Jacket", "Outerwear", "Blue", "L", 3499, 3, 2),
    ("JKT-BMR-OLV-L", "Bomber Jacket", "Outerwear", "Olive", "L", 3999, 2, 2),
    ("SHR-RUN-BLK-M", "Running Shorts", "Activewear", "Black", "M", 999, 7, 0),
    ("SHR-RUN-BLU-L", "Running Shorts", "Activewear", "Blue", "L", 999, 5, 0),
    ("LEG-YOG-BLK-S", "Yoga Leggings", "Activewear", "Black", "S", 1299, 5, 0),
    ("KUR-ETH-MRN-M", "Kurta", "Ethnic", "Maroon", "M", 1599, 4, 1),
    ("KUR-ETH-CRM-L", "Kurta", "Ethnic", "Cream", "L", 1599, 3, 1),
    ("BLZ-FRM-CHR-40", "Formal Blazer", "Formal", "Charcoal", "40", 5999, 2, 2),
    ("BLZ-FRM-NVY-42", "Formal Blazer", "Formal", "Navy", "42", 5999, 1, 2),
    ("SCF-WIN-GRY-OS", "Winter Scarf", "Accessories", "Grey", "OS", 699, 2, 3),
]

CHRONIC = {"SWT-HOD-GRY-M", "SWT-HOD-BLK-XL", "SWT-HOD-NVY-L"}
VOLATILE = {"JKT-DNM-BLU-M", "JKT-DNM-BLU-L"}
HERO = {"TSH-CRW-BLK-M", "JNS-SLM-IND-32", "SHR-RUN-BLK-M", "POL-TSH-RED-M", "KUR-ETH-MRN-M"}
DEADSTOCK = {"SCF-WIN-GRY-OS"}


def engine_status(soh, qoo, ads, lt):
    pipeline = soh + qoo
    rop = ads * lt
    buf = ads * lt * BF
    if soh == 0 and qoo == 0: return "OUT_OF_STOCK"
    if soh == 0 and qoo > 0:  return "INCOMING"
    if pipeline < 0.5 * rop:  return "CRITICAL"
    if pipeline < rop:        return "REORDER"
    if soh > 2 * buf:         return "OVERSTOCK"
    return "OPTIMAL"


def set_stock(status, ads, lt):
    if ads <= 0:
        return (random.randint(6, 40), 0) if status == "OVERSTOCK" else (0, 0)
    rop = ads * lt
    soh = qoo = 0
    for _ in range(80):
        if status == "OUT_OF_STOCK":  soh, qoo = 0, 0
        elif status == "INCOMING":    soh, qoo = 0, max(1, round(rop * random.uniform(0.7, 1.3)))
        elif status == "CRITICAL":    soh, qoo = max(1, round(rop * random.uniform(0.15, 0.42))), 0
        elif status == "REORDER":     soh, qoo = max(1, round(rop * random.uniform(0.55, 0.9))), 0
        elif status == "OVERSTOCK":
            tot = round(3 * ads * lt * random.uniform(1.2, 1.9)) + 3
            qoo = round(tot * random.choice([0, 0, 0, 0.2])); soh = tot - qoo
        else:
            tot = round(ads * lt * random.uniform(1.2, 2.6))
            qoo = round(tot * random.choice([0, 0, 0, 0.3])); soh = max(1, tot - qoo)
        if engine_status(soh, qoo, ads, lt) == status:
            return soh, qoo
    return soh, qoo


def weekly_sales(ads_actual, mode):
    mu = ads_actual * 7.0
    if mode == "volatile":
        return [max(0, round(random.gauss(mu, mu * 0.75))) for _ in range(8)]
    if mode == "uptrend":
        return [max(0, round(mu * f * random.uniform(0.9, 1.1)))
                for f in (0.55, 0.68, 0.8, 0.95, 1.12, 1.3, 1.45, 1.6)]
    return [max(0, round(random.gauss(mu, mu * 0.18))) for _ in range(8)]


POOL = (["OPTIMAL"] * 40 + ["REORDER"] * 16 + ["CRITICAL"] * 9 +
        ["OVERSTOCK"] * 12 + ["OUT_OF_STOCK"] * 6 + ["INCOMING"] * 5 + ["OPTIMAL"] * 12)

LEGACY = {"OUT_OF_STOCK": "OUT OF STOCK", "INCOMING": "IN TRANSIT", "CRITICAL": "URGENT",
          "REORDER": "REORDER", "OVERSTOCK": "EXCESS", "OPTIMAL": "OK"}

rows = []
for si, (code, style, cat, colour, size, mrp, base, lt_add) in enumerate(SKUS):
    for ti, (store, sfac, lt_base) in enumerate(STORES):
        ads_actual = max(1, round(base * sfac))
        lt = max(2, lt_base + lt_add + random.choice([-1, 0, 0, 1]))
        mode = "normal"; stated = ads_actual
        if code in CHRONIC:
            mode = "uptrend"; stated = max(1, round(ads_actual * 0.55))
        elif code in VOLATILE:
            mode = "volatile"
        else:
            rr = random.random()
            if rr < 0.10:   stated = max(1, round(ads_actual * 0.65))
            elif rr < 0.18: stated = max(1, round(ads_actual * 1.5))
        force_zero_ads = code in DEADSTOCK and ti in (3, 4, 6, 8, 9, 10)
        if force_zero_ads:
            stated = 0; mode = "normal"
        sales = weekly_sales(ads_actual, mode) if stated else [0] * 8

        if code in HERO and ti == 0:      status = "OVERSTOCK"
        elif code in HERO and ti == 1:    status = random.choice(["OUT_OF_STOCK", "CRITICAL"])
        elif code in HERO and ti == 2:    status = "CRITICAL"
        elif code in CHRONIC:             status = random.choice(["REORDER", "REORDER", "CRITICAL", "OPTIMAL"])
        elif force_zero_ads:              status = random.choice(["OVERSTOCK", "OUT_OF_STOCK"])
        else:                             status = random.choice(POOL)
        soh, qoo = set_stock(status, stated if stated else 0, lt)

        real = engine_status(soh, qoo, stated if stated else 0, lt)
        legacy = LEGACY[real]
        if random.random() < 0.08:
            legacy = random.choice([v for k, v in LEGACY.items() if v != legacy])

        rows.append({
            "SKU Code": code, "Style Name": style, "Category": cat, "Colour": colour,
            "Size": size, "Outlet": store, "Supplier": f"VND-{(si % 6)+1:02d}",
            "Closing Stock": soh, "In Transit": qoo, "Avg Off-take/Day": stated,
            "Lead Time (Days)": lt, "MRP": mrp, "System Status": legacy,
            "Sold W-8": sales[0], "Sold W-7": sales[1], "Sold W-6": sales[2], "Sold W-5": sales[3],
            "Sold W-4": sales[4], "Sold W-3": sales[5], "Sold W-2": sales[6], "Sold W-1": sales[7],
        })


def find(code, store):
    return next(r for r in rows if r["SKU Code"] == code and r["Outlet"] == store)

# the 10 broken rows + number-format noise (identical to dry-run v1)
find("CHN-TRS-NVY-34", "Chennai")["Avg Off-take/Day"] = ""
find("SHT-OXF-BLU-M", "Kolkata")["Lead Time (Days)"] = ""
find("KUR-ETH-CRM-L", "Ahmedabad")["Closing Stock"] = "N/A"
find("POL-TSH-GRN-L", "Jaipur")["Closing Stock"] = "-6"
find("JNS-SLM-BLK-34", "Lucknow")["Lead Time (Days)"] = "0"
find("SHT-OXF-WHT-L", "Pune")["Lead Time (Days)"] = "7 days"
find("LEG-YOG-BLK-S", "Kochi")["In Transit"] = "-10"
find("CHN-TRS-OLV-30", "Hyderabad")["Outlet"] = ""
find("BLZ-FRM-CHR-40", "Delhi (CP)")["Avg Off-take/Day"] = "abc"
find("SHR-RUN-BLU-L", "Chandigarh")["Closing Stock"] = "12.5"
find("TSH-CRW-BLK-M", "Mumbai - Andheri")["Closing Stock"] = "1,240"
find("JNS-SLM-IND-32", "Mumbai - Andheri")["MRP"] = "₹2,499"
find("POL-TSH-RED-M", "Mumbai - Andheri")["Avg Off-take/Day"] = "  8 "
find("KUR-ETH-MRN-M", "Mumbai - Andheri")["In Transit"] = ""
dup = dict(find("TSH-CRW-WHT-L", "Pune")); dup["Closing Stock"] = 99
rows.append(dup)

COLS = ["SKU Code", "Style Name", "Category", "Colour", "Size", "Outlet", "Supplier",
        "Closing Stock", "In Transit", "Avg Off-take/Day", "Lead Time (Days)", "MRP",
        "System Status", "Sold W-8", "Sold W-7", "Sold W-6", "Sold W-5", "Sold W-4",
        "Sold W-3", "Sold W-2", "Sold W-1"]

# ---------------------------------------------------------------- v2 additions
# Fixed constants only — no RNG — so the v1 byte stream above never changes.
V2_COLS = COLS + ["Reserved Qty", "Damaged Qty", "Case Pack"]

def v2row(code, store, soh, qoo, ads, lt, sales, legacy, reserved="", damaged="", pack=""):
    sku = next(s for s in SKUS if s[0] == code)
    return {
        "SKU Code": code, "Style Name": sku[1], "Category": sku[2], "Colour": sku[3],
        "Size": sku[4], "Outlet": store, "Supplier": "VND-07",
        "Closing Stock": soh, "In Transit": qoo, "Avg Off-take/Day": ads,
        "Lead Time (Days)": lt, "MRP": sku[5], "System Status": legacy,
        "Sold W-8": sales[0], "Sold W-7": sales[1], "Sold W-6": sales[2], "Sold W-5": sales[3],
        "Sold W-4": sales[4], "Sold W-3": sales[5], "Sold W-2": sales[6], "Sold W-1": sales[7],
        "Reserved Qty": reserved, "Damaged Qty": damaged, "Case Pack": pack,
    }

V2_EXTRA = [
    # 1. pipeline-overcommit: shelf normal, inbound absurd (pipeline 440 vs buffer 45) -> G24
    v2row("TSH-CRW-BLK-M", "Surat", 40, 400, 5, 6, [34, 36, 33, 35, 37, 34, 36, 35], "OK"),
    # 2. stockout-censored sales: OOS now; two zero-sale weeks while shelf was empty -> G19
    v2row("SWT-HOD-GRY-M", "Surat", 0, 0, 3, 7, [28, 31, 34, 0, 0, 38, 41, 0], "OUT OF STOCK"),
    # 3. implausible: sells ~40/wk per history yet SOH 500 with ADS 2 -> G23 verify-first
    v2row("POL-TSH-RED-M", "Surat", 500, 0, 2, 6, [40, 38, 42, 39, 41, 40, 43, 39], "OK"),
    # 4. promo spike: one 3x week (W-4) in otherwise flat history -> G18
    v2row("TSH-CRW-WHT-L", "Surat", 70, 0, 6, 6, [41, 43, 40, 42, 126, 41, 44, 42], "OK"),
    # 5. lane-gate: CRITICAL receiver whose supplier LT (2d) beats the 3-day truck -> G22
    v2row("JNS-SLM-IND-32", "Thane", 3, 0, 4, 2, [27, 29, 26, 28, 30, 27, 29, 28], "URGENT"),
    # 6. reserved/damaged/case-pack fields on a healthy row -> G26/G22 (ATP + packs)
    v2row("SHR-RUN-BLK-M", "Thane", 60, 0, 5, 5, [34, 36, 35, 33, 37, 35, 36, 34], "OK",
          reserved=10, damaged=2, pack=12),
]


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else "."
    with open(f"{outdir}/stress_mis_v1.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    with open(f"{outdir}/stress_mis_v2.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=V2_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({**r, "Reserved Qty": "", "Damaged Qty": "", "Case Pack": ""})
        for r in V2_EXTRA:
            w.writerow(r)
    print(f"wrote stress_mis_v1.csv ({len(rows)} rows) and "
          f"stress_mis_v2.csv ({len(rows) + len(V2_EXTRA)} rows) to {outdir}")


if __name__ == "__main__":
    main()
