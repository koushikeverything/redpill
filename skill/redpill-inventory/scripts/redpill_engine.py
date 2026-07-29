#!/usr/bin/env python3
"""Red Pill deterministic formula engine.

Usage:
    python redpill_engine.py input.csv [--out computed.csv] [--summary summary.json]
                             [--buffer-factor 1.5] [--target-factor 2.5] [--savings-rate 0.15]

Input CSV columns (case-insensitive; extra columns pass through untouched):
    sku, store, soh, qoo, ads, lead_time  [, price]

Outputs:
  - computed.csv : input rows + pipeline, buffer, rop, days_of_stock, status,
                   reorder_qty, reorder_qty_net (after transfers), order_value
  - summary.json : status counts, health score, urgency ranking, transfer plan

All logic mirrors references/formulas.md. Derived values are never read from
the input — everything is recomputed here.
"""
import argparse
import csv
import json
import math
import sys
from datetime import date, timedelta

STATUSES = ["OUT_OF_STOCK", "INCOMING", "CRITICAL", "REORDER", "OVERSTOCK", "OPTIMAL"]


def compute_row(soh, qoo, ads, lt, bf, tf, price=None):
    pipeline = soh + qoo
    buffer = ads * lt * bf
    rop = ads * lt
    days = (pipeline / ads) if ads > 0 else 0.0
    reorder = max(0, math.ceil(round(ads * lt * tf - soh - qoo, 9)))
    # Status: strict evaluation order, first match wins.
    if soh == 0 and qoo == 0:
        status = "OUT_OF_STOCK"
    elif soh == 0 and qoo > 0:
        status = "INCOMING"
    elif pipeline < 0.5 * rop:
        status = "CRITICAL"
    elif pipeline < rop:
        status = "REORDER"
    elif soh > 2 * buffer:
        status = "OVERSTOCK"
    else:
        status = "OPTIMAL"
    return {
        "pipeline": pipeline,
        "buffer": round(buffer, 2),
        "rop": round(rop, 2),
        "days_of_stock": round(days, 2),
        "status": status,
        "reorder_qty": reorder,
        "order_value": round(reorder * price, 2) if price is not None else "",
    }


def build_transfers(rows, savings_rate):
    """Per-SKU greedy pairing: largest deficit ← largest surplus."""
    transfers = []
    by_sku = {}
    for r in rows:
        by_sku.setdefault(r["sku"], []).append(r)
    for sku, group in by_sku.items():
        donors = sorted(
            [r for r in group if r["status"] == "OVERSTOCK"],
            key=lambda r: r["soh"] - r["buffer"], reverse=True)
        receivers = sorted(
            [r for r in group if r["status"] in ("OUT_OF_STOCK", "CRITICAL", "REORDER")],
            key=lambda r: r["buffer"] - r["pipeline"], reverse=True)
        surplus = {id(d): d["soh"] - d["buffer"] for d in donors}
        deficit = {id(x): x["buffer"] - x["pipeline"] for x in receivers}
        for recv in receivers:
            for don in donors:
                qty = math.floor(round(max(0, min(surplus[id(don)], deficit[id(recv)])), 9))
                if qty <= 0:
                    continue
                price = don.get("price")
                value = round(qty * price, 2) if price is not None else None
                transfers.append({
                    "sku": sku, "from_store": don["store"], "to_store": recv["store"],
                    "qty": qty, "value": value,
                    "est_saving": round(value * savings_rate, 2) if value is not None else None,
                })
                surplus[id(don)] -= qty
                deficit[id(recv)] -= qty
                # Net the receiver's reorder quantity down by the incoming units.
                recv["reorder_qty_net"] = max(0, recv.get("reorder_qty_net", recv["reorder_qty"]) - qty)
                if deficit[id(recv)] <= 0:
                    break
    return transfers


def fnum(v, default=None):
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, AttributeError):
        return default


TEMPLATE_HEADER = ["sku", "store", "soh", "qoo", "ads", "lead_time", "unit_price"]
TEMPLATE_EXAMPLE = ["Face Serum", "Mumbai", "3", "0", "12", "7", "450"]
TEMPLATE_LEGEND = [
    ["# sku        = product name or code (required)"],
    ["# store      = store/location name (required)"],
    ["# soh        = stock on hand, units on shelf right now (required, >= 0)"],
    ["# qoo        = quantity on order / in transit (blank allowed -> treated as 0)"],
    ["# ads        = average daily sales in units/day for THIS sku at THIS store (required; use 0 only if truly no demand)"],
    ["# lead_time  = supplier lead time in DAYS for THIS sku at THIS store (required, > 0)"],
    ["# unit_price = per-unit price/cost (optional; enables order values & transfer savings)"],
    ["# One row per SKU x Store combination. Delete these # lines before running."],
]


def write_template(path, known_rows=None):
    """Write a fill-in template. If known_rows given, pre-populate what we know
    and leave blanks where data is needed."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(TEMPLATE_HEADER)
        if known_rows:
            for r in known_rows:
                w.writerow([r.get(c, "") for c in TEMPLATE_HEADER])
        else:
            w.writerow(TEMPLATE_EXAMPLE)
        for line in TEMPLATE_LEGEND:
            w.writerow(line)
    return path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("input", nargs="?")
    p.add_argument("--out", default="computed.csv")
    p.add_argument("--summary", default="summary.json")
    p.add_argument("--gaps", default="data_gaps.csv")
    p.add_argument("--template", action="store_true",
                   help="Write a blank fill-in template (redpill_input_template.csv) and exit")
    p.add_argument("--buffer-factor", type=float, default=1.5)
    p.add_argument("--target-factor", type=float, default=2.5)
    p.add_argument("--savings-rate", type=float, default=0.15)
    args = p.parse_args()

    if args.template or not args.input:
        path = write_template("redpill_input_template.csv")
        print(f"Template written to {path}. Fill it in (one row per SKU x Store) and rerun:")
        print(f"  python redpill_engine.py {path}")
        return

    with open(args.input, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        raw = list(reader)
    if not raw:
        sys.exit("Empty input file. Run with --template to get the required format.")

    cols = {c.lower().strip().replace(" ", "_").replace("-", "_"): c for c in raw[0].keys()}

    def col(*names):
        for n in names:
            if n in cols:
                return cols[n]
        return None

    c_sku = col("sku", "product", "item", "sku_code")
    c_store = col("store", "location", "branch", "outlet")
    c_soh = col("soh", "stock_on_hand", "closing_stock", "stock")
    c_qoo = col("qoo", "quantity_on_order", "in_transit", "pending_po", "on_order")
    c_ads = col("ads", "avg_daily_sales", "average_daily_sales", "daily_sales", "offtake")
    c_lt = col("lead_time", "lt", "lead_time_days", "leadtime")
    c_price = col("price", "unit_price", "cost", "unit_cost", "mrp")
    c_bf = col("buffer_factor", "bf")  # optional per-row override of --buffer-factor
    missing = [n for n, c in [("sku", c_sku), ("store", c_store), ("soh", c_soh),
                              ("ads", c_ads), ("lead_time", c_lt)] if c is None]
    if missing:
        path = write_template("redpill_input_template.csv")
        sys.exit(f"Missing required columns: {missing}. Found: {list(cols)}.\n"
                 f"A fill-in template with the required format was written to {path}.")

    # ---- Row-level validation: quarantine, never guess ----
    rows, gaps, warnings, assumptions = [], [], [], []
    if c_qoo is None:
        assumptions.append("No QOO/in-transit column found: assumed QOO = 0 for ALL rows. "
                           "Add a qoo column if orders are in transit.")
    seen = set()
    for i, r in enumerate(raw, start=2):  # 2 = first data line in the file
        sku, store = str(r[c_sku]).strip(), str(r[c_store]).strip()
        problems = []
        if not sku or not store:
            problems.append("blank sku/store")
        key = (sku.lower(), store.lower())
        if key in seen:
            problems.append("duplicate SKU+Store row (first occurrence kept)")
        soh = fnum(r[c_soh])
        qoo_raw = r[c_qoo] if c_qoo else ""
        qoo = fnum(qoo_raw)
        ads = fnum(r[c_ads])
        lt = fnum(r[c_lt])
        price = fnum(r[c_price]) if c_price else None
        if soh is None:
            problems.append(f"soh not a number ('{r[c_soh]}')")
        elif soh < 0:
            problems.append(f"soh negative ({soh}) — physical stock cannot be < 0")
        if qoo is None:
            if str(qoo_raw).strip() == "":
                qoo = 0.0
                assumptions.append(f"{sku}/{store}: blank QOO assumed 0")
            else:
                problems.append(f"qoo not a number ('{qoo_raw}')")
        elif qoo < 0:
            problems.append(f"qoo negative ({qoo})")
        if ads is None:
            problems.append("ads blank/non-numeric — blank is NOT zero demand; fill actual units/day")
        elif ads == 0:
            warnings.append(f"{sku}/{store}: ADS = 0 stated — treated as zero demand "
                            f"(any stock -> OVERSTOCK). Verify this is not missing master data.")
        elif ads < 0:
            problems.append(f"ads negative ({ads})")
        if lt is None or (lt is not None and lt <= 0):
            problems.append(f"lead_time missing or <= 0 ('{r[c_lt]}') — need supplier days for this SKU at this store")
        bf = args.buffer_factor
        if c_bf and str(r.get(c_bf, "")).strip():
            bf_row = fnum(r[c_bf])
            if bf_row is None or bf_row <= 0:
                problems.append(f"buffer_factor invalid ('{r[c_bf]}') — must be a positive number (default 1.5)")
            else:
                bf = bf_row
                if bf_row != args.buffer_factor:
                    assumptions.append(f"{sku}/{store}: per-row buffer factor {bf_row} used (global default {args.buffer_factor})")
        if problems:
            gap = {c: str(r.get(orig, "")) for c, orig in
                   [("sku", c_sku), ("store", c_store), ("soh", c_soh),
                    ("qoo", c_qoo), ("ads", c_ads), ("lead_time", c_lt), ("unit_price", c_price)]
                   if orig}
            gap.update({"line": i, "reason": "; ".join(problems)})
            gaps.append(gap)
            continue
        seen.add(key)
        d = compute_row(soh, qoo, ads, lt, bf, args.target_factor, price)
        d.update({"sku": sku, "store": store, "soh": soh, "qoo": qoo,
                  "ads": ads, "lead_time": lt, "price": price,
                  "expected_delivery": (date.today() + timedelta(days=int(lt))).isoformat(),
                  "reorder_qty_net": d["reorder_qty"]})
        rows.append(d)

    if gaps:
        # Quarantine file doubles as the fill-in form: known values pre-filled,
        # bad/missing cells left for the user, reason column explains each.
        with open(args.gaps, "w", newline="", encoding="utf-8") as f:
            fields = TEMPLATE_HEADER + ["line", "reason"]
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for g in gaps:
                w.writerow(g)
    if not rows:
        sys.exit(f"No valid rows to process — all {len(gaps)} rows quarantined to {args.gaps}. "
                 f"Fix the 'reason' items and rerun.")

    transfers = build_transfers(rows, args.savings_rate)

    out_fields = ["sku", "store", "soh", "qoo", "ads", "lead_time", "pipeline", "buffer",
                  "rop", "days_of_stock", "status", "reorder_qty", "reorder_qty_net",
                  "order_value", "expected_delivery"]
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
        w.writeheader()
        for r in sorted(rows, key=lambda x: x["days_of_stock"]):
            w.writerow(r)

    counts = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    health = round(100.0 * counts["OPTIMAL"] / len(rows), 1)
    actionable = [r for r in rows if r["status"] in ("OUT_OF_STOCK", "INCOMING", "CRITICAL", "REORDER")]
    summary = {
        "rows": len(rows),
        "status_counts": counts,
        "health_score_pct": health,
        "urgency_top10": [
            {"sku": r["sku"], "store": r["store"], "status": r["status"],
             "days_of_stock": r["days_of_stock"], "reorder_qty_net": r["reorder_qty_net"]}
            for r in sorted(actionable, key=lambda x: x["days_of_stock"])[:10]],
        "transfer_plan": transfers,
        "total_transfer_savings": round(sum(t["est_saving"] or 0 for t in transfers), 2),
        "data_quality": {
            "rows_processed": len(rows),
            "rows_quarantined": len(gaps),
            "quarantine_file": args.gaps if gaps else None,
            "quarantined": [{"line": g["line"], "sku": g.get("sku", ""),
                             "store": g.get("store", ""), "reason": g["reason"]} for g in gaps],
            "assumptions": assumptions,
            "warnings": warnings,
        },
        "parameters": {"buffer_factor": args.buffer_factor,
                       "target_factor": args.target_factor,
                       "savings_rate": args.savings_rate},
    }
    with open(args.summary, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    msg = (f"Computed {len(rows)} rows → {args.out}; summary → {args.summary}; "
           f"health {health}%; transfers: {len(transfers)}")
    if gaps:
        msg += (f"\n⚠ {len(gaps)} row(s) QUARANTINED → {args.gaps} (pre-filled fill-in form; "
                f"complete the missing cells per the 'reason' column and rerun, or merge back into the input).")
    print(msg)


if __name__ == "__main__":
    main()
