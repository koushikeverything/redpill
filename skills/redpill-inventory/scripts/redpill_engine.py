#!/usr/bin/env python3
"""Red Pill deterministic engine (v2).

The single source of truth for parsing, validation, math, statuses, transfers,
ordering, totals, and report generation. Claude orchestrates and explains —
it never computes business numbers (SPEC.md §0).

Usage:
    python redpill_engine.py input.csv [--run-dir runs/2026-08-11]
                             [--as-of 2026-08-11] [--out computed.csv]
                             [--summary summary.json] [--gaps quarantine.csv]
                             [--report report.json]
                             [--buffer-factor 1.5] [--target-factor 2.5]
                             [--savings-rate 0.15]
    python redpill_engine.py --template          # blank fill-in form
    python redpill_engine.py --rerun RUN_DIR     # reproduce a prior run, verify identical

Outputs (all numbers every surface shows come from report.json):
  report.json    versioned full data contract (schema {SCHEMA_VERSION})
  computed.csv   per-row values incl. passthrough columns
  quarantine.csv rows set aside, pre-filled fix-me form
  summary.json   compact compatibility view (subset of report.json)
With --run-dir, everything (plus an immutable input copy, config snapshot and
run-manifest.json) is written inside the run directory.

Behavioral rules (SPEC.md gap register, Phase 0):
  G1 currency/format parsing, warn on unparseable optional price — never silent
  G2 reorder_qty = 0 unless status is actionable (OOS/INCOMING/CRITICAL/REORDER)
  G3 engine owns gross AND net order values and all totals
  G4 broad header aliases; punctuation-insensitive normalization
  G5 unmapped input columns pass through untouched
  G7 run-level verdict: healthy / degraded / blocked (+ as-of freshness stamp)
  G8 ADS=0 -> days_of_stock null; deterministic duplicate rule (first occurrence
     wins, later copies quarantined, quarantined-first documented per row);
     fractional stock warned; one empty sentinel ("" everywhere)
  G32 run directories, immutable input copy, provenance, reproducibility
  G33 mapping confidence classes: exact / high / ambiguous / user_confirmed
"""
import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import sys
from datetime import date, timedelta

ENGINE_VERSION = "2.4.2"
SCHEMA_VERSION = "2.4.0"

STATUSES = ["OUT_OF_STOCK", "INCOMING", "CRITICAL", "REORDER", "OVERSTOCK", "OPTIMAL"]
ACTIONABLE = {"OUT_OF_STOCK", "INCOMING", "CRITICAL", "REORDER"}

# Policy thresholds (G38): business choices, not mathematical facts. Defined once
# so the math and the report's assumptions_and_policies section can never drift.
CRITICAL_FRACTION_OF_ROP = 0.5   # CRITICAL when pipeline < this fraction of ROP
OVERSTOCK_X_BUFFER = 2.0         # OVERSTOCK when SOH > this multiple of buffer
ADS_CORRECTION_TRIGGER = 0.20    # propose a correction when |deviation| exceeds this
CV_VOLATILE = 0.6                # median + buffer-raise advice when CV exceeds this

# ---------------------------------------------------------------- header mapping
def norm_header(h):
    """lower-case, collapse every non-alphanumeric run to '_' (G4)."""
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(h).lower())).strip("_")

# target -> (exact aliases, high-confidence aliases). Confidence classes per G33.
ALIASES = {
    "sku":       (["sku", "sku_code", "product", "item", "product_code"],
                  ["item_code", "article", "article_code", "style_code", "variant_code",
                   "sku_id", "design_code", "isbn", "isbn_sku"]),
    "store":     (["store", "location", "branch", "outlet"],
                  ["shop", "site", "store_name", "outlet_name", "store_code", "showroom"]),
    "soh":       (["soh", "stock_on_hand", "closing_stock", "stock"],
                  ["current_stock", "on_hand", "qty_on_hand", "closing_qty", "stock_qty",
                   "shelf_stock"]),
    "qoo":       (["qoo", "quantity_on_order", "in_transit", "pending_po", "on_order"],
                  ["open_po", "inbound", "po_qty", "intransit", "qty_on_order", "in_transit_qty",
                   "incoming"]),
    "ads":       (["ads", "avg_daily_sales", "average_daily_sales", "daily_sales", "offtake"],
                  ["off_take", "avg_off_take", "avg_off_take_day", "avg_offtake_day",
                   "daily_offtake", "sales_per_day", "run_rate", "avg_sales_day"]),
    "lead_time": (["lead_time", "lt", "lead_time_days", "leadtime"],
                  ["leadtime_days", "supplier_lead_time", "replenishment_days",
                   "lead_time_in_days"]),
    "price":     (["price", "unit_price", "cost", "unit_cost", "mrp"],
                  ["rate", "selling_price", "asp", "unit_mrp", "tag_price"]),
    # optional, carried for later phases (schema hedges — G6/G26/G34)
    "reserved":  (["reserved", "reserved_qty"], ["online_reserved", "reserved_stock"]),
    "damaged":   (["damaged", "damaged_qty"], ["defective", "damaged_stock"]),
    "case_pack": (["case_pack", "case_pack_size"], ["pack_size", "carton_size", "case_size"]),
    "expected_receipt_date": (["expected_receipt_date", "eta"], ["po_eta", "receipt_date"]),
    "buffer_factor": (["buffer_factor", "bf"], []),
}
REQUIRED = ["sku", "store", "soh", "ads", "lead_time"]


def map_headers(headers, forced=None):
    """Return (mapping {target: {source, confidence}}, passthrough_columns, issues).
    `forced` maps source-header -> target with confidence "user_confirmed" (G33)."""
    normed = {h: norm_header(h) for h in headers}
    mapping, ambiguous = {}, []
    claimed = set()
    for src_header, target in (forced or {}).items():
        if src_header in headers and target in ALIASES:
            mapping[target] = {"source": src_header, "confidence": "user_confirmed"}
            claimed.add(src_header)
    for target, (exact, high) in ALIASES.items():
        if target in mapping:
            continue
        hits = []
        for h, n in normed.items():
            if h in claimed:
                continue
            if n in exact:
                hits.append((h, "exact"))
            elif n in high:
                hits.append((h, "high"))
        if not hits:
            continue
        hits.sort(key=lambda x: (x[1] != "exact", headers.index(x[0])))
        src, conf = hits[0]
        if len(hits) > 1:
            ambiguous.append({"target": target, "chosen": src,
                              "also_matched": [h for h, _ in hits[1:]]})
            conf = "ambiguous"
        mapping[target] = {"source": src, "confidence": conf}
        claimed.add(src)
    passthrough = [h for h in headers if h not in claimed]
    return mapping, passthrough, ambiguous


# ---------------------------------------------------------------- value parsing
CURRENCY_RE = re.compile(r"^(rs\.?|inr|₹|\$|€|£)\s*", re.IGNORECASE)

def fnum(v):
    """Parse a real-world number: '₹2,499' '1,240' '  8 ' '(500)'.
    Returns (value_or_None, provenance_note_or_None)."""
    if v is None:
        return None, None
    raw = str(v).strip()
    if raw == "":
        return None, None
    s = CURRENCY_RE.sub("", raw)
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    s = s.replace(",", "").replace(" ", "")
    try:
        val = -float(s) if neg else float(s)
    except ValueError:
        return None, None
    note = None
    if raw not in (str(val), f"{val:g}", s):
        cleaned = raw != s and raw != f"({s})"
        if cleaned or neg:
            note = f"parsed '{raw}' -> {val:g}"
    return val, note


# ---------------------------------------------------------------- row math
def compute_row(soh, qoo, ads, lt, bf, tf, price=None):
    pipeline = soh + qoo
    buffer = ads * lt * bf
    rop = ads * lt
    days = round(pipeline / ads, 2) if ads > 0 else None  # G8: never 0-for-unknown
    # G36: pipeline cover (days_of_stock) counts inbound that hasn't landed;
    # current cover counts only what is on the shelf right now.
    current_cover = round(soh / ads, 2) if ads > 0 else None
    # Status ladder — strict order, first match wins (formulas.md).
    if soh == 0 and qoo == 0:
        status, reason = "OUT_OF_STOCK", "SOH 0 and nothing on order — losing sales now"
    elif soh == 0:
        status, reason = "INCOMING", f"SOH 0 but {qoo:g} in transit"
    elif pipeline < CRITICAL_FRACTION_OF_ROP * rop:
        status, reason = "CRITICAL", (f"pipeline {pipeline:g} < half of reorder point "
                                      f"{rop:g} — will stock out before replenishment lands")
    elif pipeline < rop:
        status, reason = "REORDER", f"pipeline {pipeline:g} < reorder point {rop:g} — order today"
    elif soh > OVERSTOCK_X_BUFFER * buffer:
        status, reason = "OVERSTOCK", (f"SOH {soh:g} > 2x buffer {OVERSTOCK_X_BUFFER*buffer:g} — "
                                       f"capital tied up; transfer donor")
    else:
        status, reason = "OPTIMAL", f"pipeline {pipeline:g} within buffer — healthy"
    actionable = status in ACTIONABLE
    # G2: refill-to-target orders exist only for actionable rows.
    reorder = max(0, math.ceil(round(ads * lt * tf - soh - qoo, 9))) if actionable else 0
    return {
        "pipeline": pipeline, "buffer": round(buffer, 2), "rop": round(rop, 2),
        "days_of_stock": days, "current_cover": current_cover,
        "status": status, "status_reason": reason,
        "actionable": actionable, "reorder_qty": reorder,
        "order_value": round(reorder * price, 2) if price is not None else None,
    }


# ---------------------------------------------------------------- transfers
def sellable(r):
    """ATP when reserved/damaged columns exist (G26/G52): what a donor may give."""
    s_ = r["soh"] - (r["reserved"] or 0) - (r["damaged"] or 0)
    return max(0.0, s_)


def build_transfers(rows, savings_rate, warnings, transfer_days=0, policies=None,
                    cost_per_unit=0.0):
    """Per-SKU greedy pairing: largest deficit <- largest surplus.
    Donors keep their full buffer by construction (surplus = sellable - buffer).
    Gates (G22/G25): lane time vs supplier LT, case packs, lane blacklist,
    protected donor stores. Every gate application is disclosed."""
    pol = policies or {}
    protected = {str(x).lower() for x in pol.get("protected_stores", [])}
    lane_cost = {(str(a).lower(), str(b).lower()): float(c)
                 for a, b, c in pol.get("lane_costs", [])}
    blacklist = {(str(a).lower(), str(b).lower())
                 for a, b in pol.get("no_transfer_lanes", [])}
    notes = []
    transfers = []
    by_sku = {}
    for r in rows:
        by_sku.setdefault(r["sku"], []).append(r)
    for sku in sorted(by_sku):
        group = by_sku[sku]
        donors = sorted([r for r in group if r["status"] == "OVERSTOCK"
                         and r["store"].lower() not in protected],
                        key=lambda r: (-(sellable(r) - r["buffer"]), r["line"]))
        skipped_prot = [r["store"] for r in group if r["status"] == "OVERSTOCK"
                        and r["store"].lower() in protected]
        for st in skipped_prot:
            notes.append(f"{sku}: {st} is a protected store — not used as donor")
        receivers = sorted([r for r in group
                            if r["status"] in ("OUT_OF_STOCK", "CRITICAL", "REORDER")],
                           key=lambda r: (-(r["buffer"] - r["pipeline"]), r["line"]))
        surplus = {r["line"]: max(0.0, sellable(r) - r["buffer"]) for r in donors}
        deficit = {r["line"]: r["buffer"] - r["pipeline"] for r in receivers}
        for recv in receivers:
            if transfer_days > 0 and recv["lead_time"] <= transfer_days:
                notes.append(f"{sku} -> {recv['store']}: supplier "
                             f"({recv['lead_time']:g}d) beats the truck "
                             f"({transfer_days:g}d) — order fresh instead")
                continue
            # G36: transfer still worth sending, but flag when the receiver runs
            # dry before the truck lands — a valid transfer can arrive too late.
            dry_gap = None
            if transfer_days > 0 and recv["ads"] > 0:
                dry = recv["soh"] / recv["ads"]
                if dry < transfer_days:
                    dry_gap = round(transfer_days - dry, 1)
                    notes.append(f"{sku} -> {recv['store']}: shelf runs dry ~day "
                                 f"{dry:.0f}, {dry_gap:g}d before the truck "
                                 f"({transfer_days:g}d) lands — expedite the move "
                                 f"or bridge with the fresh order")
            for don in donors:
                if (don["store"].lower(), recv["store"].lower()) in blacklist:
                    notes.append(f"{sku}: lane {don['store']} -> {recv['store']} "
                                 f"blocked by policy")
                    continue
                qty = math.floor(round(max(0, min(surplus[don["line"]],
                                                  deficit[recv["line"]])), 9))
                pack = don.get("case_pack") or recv.get("case_pack")
                if pack and pack > 1 and qty > 0:
                    whole = int(qty // pack) * int(pack)
                    if whole == 0:
                        notes.append(f"{sku} {don['store']} -> {recv['store']}: "
                                     f"below one case pack of {pack:g} — skipped")
                        qty = 0
                    else:
                        qty = whole
                if qty <= 0:
                    continue
                price = don.get("price")
                value = round(qty * price, 2) if price is not None else None
                if value is None:
                    warnings.append(f"transfer {sku} {don['store']}->{recv['store']}: "
                                    f"donor price missing — value/saving omitted")
                cpu = lane_cost.get((don["store"].lower(), recv["store"].lower()),
                                    cost_per_unit)
                est_saving = round(value * savings_rate, 2) if value is not None else None
                est_cost = round(qty * cpu, 2) if cpu else None          # G35: cost if known
                net_benefit = (round(est_saving - est_cost, 2)
                               if est_saving is not None and est_cost is not None else None)
                transfers.append({
                    "sku": sku, "from_store": don["store"], "to_store": recv["store"],
                    "qty": qty, "value": value,
                    "est_saving": est_saving,
                    "est_transfer_cost": est_cost,          # null = cost unknown, not zero
                    "net_benefit": net_benefit,
                    "receiver_dry_before_arrival_days": dry_gap,   # G36: null = arrives in time
                })
                surplus[don["line"]] -= qty
                deficit[recv["line"]] -= qty
                recv["reorder_qty_net"] = max(0, recv["reorder_qty_net"] - qty)
                if deficit[recv["line"]] <= 0:
                    break
    return transfers, notes


# ---------------------------------------------------------------- template
TEMPLATE_HEADER = ["sku", "store", "soh", "qoo", "ads", "lead_time", "unit_price"]
TEMPLATE_EXAMPLE = ["Face Serum", "Mumbai", "3", "0", "12", "7", "450"]
TEMPLATE_LEGEND = [
    ["# sku        = product name or code (required)"],
    ["# store      = store/location name (required)"],
    ["# soh        = stock on hand, units on shelf right now (required, >= 0)"],
    ["# qoo        = quantity on order / in transit (blank allowed -> treated as 0)"],
    ["# ads        = average daily sales in units/day for THIS sku at THIS store (required)"],
    ["# lead_time  = supplier lead time in DAYS for THIS sku at THIS store (required, > 0)"],
    ["# unit_price = per-unit price/cost (optional; enables order values & transfer savings)"],
    ["# One row per SKU x Store combination. Delete these # lines before running."],
]

def write_template(path, known_rows=None):
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


def aux_out_path(args, name):
    """Destination for side outputs (gap file, fill-in template): next to
    --out / --report when either carries a directory, so a run pointed at
    another directory never drops files into the caller's CWD. Bare-name
    defaults keep the old CWD behavior; --run-dir rewrites --out/--report
    first, so side outputs land inside the run dir."""
    for anchor in (getattr(args, "out", None), getattr(args, "report", None)):
        if anchor and anchor != os.devnull:
            d = os.path.dirname(anchor)
            if d:
                return os.path.join(d, name)
    return name


# ---------------------------------------------------------------- helpers
def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def jdump(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")


# ---------------------------------------------------------------- ask-back (G13)
NUM_IN_TEXT = re.compile(r"(\d+(?:\.\d+)?)")

def build_candidates(gaps, rows, src):
    """Deterministic pre-guessed answers for quarantined rows, so the skill can
    ask one-tap questions ('7 days in 10 other stores — use 7?')."""
    lt_by_sku, ads_by_sku = {}, {}
    for r in rows:
        lt_by_sku.setdefault(r["sku"], []).append(r["lead_time"])
        ads_by_sku.setdefault(r["sku"], []).append(r["ads"])

    def mode(vals):
        best, n = None, 0
        for v in sorted(set(vals)):
            c = vals.count(v)
            if c > n:
                best, n = v, c
        return best, n

    for g in gaps:
        reason, cands = g["reason"], []
        rawrow = g.pop("_rawrow", {})
        if "lead_time" in reason:
            m = NUM_IN_TEXT.search(str(g.get("lead_time", "")))
            if m and float(m.group(1)) > 0:
                cands.append({"field": "lead_time", "value": float(m.group(1)),
                              "basis": f"number found in '{g['lead_time']}'",
                              "confidence": "high"})
            peers = lt_by_sku.get(g["sku"], [])
            if peers:
                v, n = mode(peers)
                cands.append({"field": "lead_time", "value": v,
                              "basis": f"used in {n} other store(s) for this SKU",
                              "confidence": "high" if n >= 3 else "low"})
            g["ask"] = "supplier lead time in days for this SKU at this store"
        if "ads" in reason and "lead_time" not in reason:
            sold = []
            for k in sorted(rawrow.keys(), key=lambda h: norm_header(h)):
                if "sold" in norm_header(k):
                    v, _ = fnum(rawrow[k])
                    sold.append((norm_header(k), v))
            recent = [v for _, v in sorted(sold)[-4:] if v is not None]
            if len(recent) == 4:
                cands.append({"field": "ads", "value": round(sum(recent) / 28.0, 1),
                              "basis": "≈ recent 4-week sales history in this file",
                              "confidence": "medium"})
            g["ask"] = "average daily sales (units/day) — blank is NOT zero demand"
        if "soh" in reason:
            g["ask"] = "shelf stock right now — needs a physical count if unknown"
        if "qoo" in reason:
            cands.append({"field": "qoo", "value": 0,
                          "basis": "set 0 if nothing is actually in transit",
                          "confidence": "medium"})
            g["ask"] = "units genuinely on order / in transit"
        if "store is blank" in reason or "sku is blank" in reason:
            g["ask"] = "which SKU/store this row belongs to"
        if "duplicate" in reason:
            cands.append({"field": "resolution", "value": "keep_first",
                          "basis": "keep the first occurrence (current behavior)",
                          "confidence": "high"})
            cands.append({"field": "resolution", "value": "use_this_row",
                          "basis": "replace with this row's values via an override",
                          "confidence": "low"})
            g["ask"] = "which copy of this duplicated row is correct"
        g.setdefault("ask", "correct value for the field named in the reason")
        g["candidates"] = cands
    return gaps




# ---------------------------------------------------------------- demand module (G18/G19/G29)
SOLD_COL = re.compile(r"sold|sale")

def _history(row):
    """[(weeks_ago, units)] oldest-first from passthrough sales columns."""
    out = []
    for k, v in row["passthrough"].items():
        n = norm_header(k)
        if SOLD_COL.search(n):
            m = NUM_IN_TEXT.search(n)
            units, _ = fnum(v)
            if m and units is not None:
                out.append((int(float(m.group(1))), units))
    return sorted(out, key=lambda x: -x[0])


def _stats(vals):
    m = sum(vals) / len(vals)
    if m <= 0:
        return m, 0.0
    var = sum((v - m) ** 2 for v in vals) / len(vals)
    return m, (var ** 0.5) / m


def analyze_demand(rows, promo_weeks_ago):
    """Engine-owned ADS analysis: censoring, promo exclusion, CV, confidence,
    corrections, plausibility (verify-first). Returns (corrections, plausibility)."""
    corrections, plausibility = [], []
    promo_set = set(promo_weeks_ago or [])
    for r in rows:
        hist = _history(r)
        if len(hist) < 4:
            continue
        excluded_promo = [w for w, _ in hist if w in promo_set]
        usable = [(w, u) for w, u in hist if w not in promo_set]
        censored = []
        if r["soh"] == 0 and any(u > 0 for _, u in usable):
            censored = [w for w, u in usable if u == 0]
            usable = [(w, u) for w, u in usable if u > 0]   # G19: empty-shelf weeks out
        if len(usable) < 3:
            continue
        weekly = [u for _, u in usable]
        mean_w, cv = _stats(weekly)
        nonzero = [u for u in weekly if u > 0]
        med = sorted(weekly)[len(weekly) // 2]
        # suspected promo: one week towers over the median of the others (G18)
        suspected = [w for w, u in usable
                     if len(nonzero) >= 4 and med > 0 and u > 2.5 * med]
        recent = weekly[-4:]
        actual = (med / 7.0) if cv > CV_VOLATILE else (sum(recent) / (7.0 * len(recent)))  # G29
        r["cv"] = round(cv, 2)
        stated = r["ads"]
        conf = ("high" if len(usable) >= 6 and cv < 0.4 and not censored
                else "low" if (censored or cv > 0.8 or len(usable) < 4) else "medium")
        dev = None if stated <= 0 else (actual - stated) / stated
        total_sold = sum(u for _, u in hist)
        if dev is not None and dev > 1.0 and r["soh"] > 1.5 * total_sold > 0:
            plausibility.append({
                "sku": r["sku"], "store": r["store"],
                "reason": (f"file claims ~{actual:.1f}/day sales but shelf holds "
                           f"{r['soh']:g} (> 8 weeks of sales) — stock and sales "
                           f"disagree; physically count before large actions")})
            r["warnings"].append("verify count first — stock and claimed sales disagree")
            r["mitigation"] = "verify count first"
            continue   # don't also propose an ADS change on distrusted data
        needs = (dev is not None and abs(dev) > ADS_CORRECTION_TRIGGER) or                 cv > CV_VOLATILE or (stated == 0 and actual > 0.5)
        if not needs:
            continue
        if stated == 0:
            rec = f"stated ADS 0 but it sells ~{actual:.1f}/day — set master ADS"
        elif cv > CV_VOLATILE:
            rec = ("volatile (CV {:.2f}) — median used; raise buffer factor to ~2.0 "
                   "rather than chasing the mean".format(cv))
        elif dev > 0:
            rec = f"raise master ADS {stated:g} -> {round(actual)} (under-forecast)"
        else:
            rec = f"lower master ADS {stated:g} -> {round(actual)} (over-stated)"
        corrections.append({
            "sku": r["sku"], "store": r["store"], "line": r["line"],
            "stated_ads": stated, "actual_ads": round(actual, 1),
            "deviation_pct": None if dev is None else round(dev * 100),
            "cv": round(cv, 2), "confidence": conf,
            "weeks_used": len(usable),
            "excluded": {"censored_weeks": len(censored),
                         "promo_weeks": len(excluded_promo),
                         "suspected_promo_weeks_ago": suspected},
            "recommendation": rec})
    return corrections, plausibility


def segment_rows(rows):
    """ABC by revenue-rate share (70/90 cumulative), XYZ by demand CV (G20)."""
    priced = sorted([r for r in rows if r["price"] and r["ads"] > 0],
                    key=lambda r: (-(r["ads"] * r["price"]), r["line"]))
    total = sum(r["ads"] * r["price"] for r in priced) or 1.0
    cum = 0.0
    for r in rows:
        r["abc"] = None
        r["xyz"] = (None if "cv" not in r else
                    "X" if r["cv"] < 0.25 else "Y" if r["cv"] < 0.6 else "Z")
    for r in priced:
        cum += r["ads"] * r["price"] / total
        r["abc"] = "A" if cum <= 0.70 else "B" if cum <= 0.90 else "C"
    opt_val = sum(r["ads"] * r["price"] for r in priced if r["status"] == "OPTIMAL")
    all_val = sum(r["ads"] * r["price"] for r in priced) or 1.0
    return round(100.0 * opt_val / all_val, 1)


def size_curve_breaks(rows):
    """Broken size runs within a style+colour family per store (G21)."""
    fams = {}
    for r in rows:
        style = None
        colour = None
        size = None
        for k, v in r["passthrough"].items():
            n = norm_header(k)
            if n in ("style", "style_name"):
                style = str(v).strip()
            elif n in ("colour", "color"):
                colour = str(v).strip()
            elif n == "size":
                size = str(v).strip()
        if style and colour and size:
            fams.setdefault((r["store"], style, colour), []).append((size, r))
    breaks = []
    for (store, style, colour), members in sorted(fams.items()):
        if len(members) < 2:
            continue
        missing = [(sz, r["sku"]) for sz, r in members
                   if r["status"] in ("OUT_OF_STOCK", "CRITICAL")]
        stranded = [(sz, r["sku"]) for sz, r in members if r["status"] == "OVERSTOCK"]
        healthy = len(members) - len(missing)
        if missing and healthy:
            breaks.append({
                "store": store, "style": style, "colour": colour,
                "missing_sizes": [s for s, _ in missing],
                "stranded_sizes": [s for s, _ in stranded],
                "note": (f"{style} ({colour}) at {store}: size run broken — "
                         f"{', '.join(s for s, _ in missing)} unavailable while other "
                         f"sizes sit; customers see a broken rack")})
    return breaks


# ---------------------------------------------------------------- main pipeline
def run(args):
    warnings, assumptions, provenance = [], [], []

    with open(args.input, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        raw = list(reader)
        headers = reader.fieldnames or []
    if not raw:
        sys.exit("Empty input file. Run with --template to get the required format.")

    forced_map, ovmap, config = {}, {}, None
    if getattr(args, "mappings", None) and os.path.exists(args.mappings):
        with open(args.mappings, encoding="utf-8") as f:
            forced_map = json.load(f)
    if getattr(args, "overrides", None) and os.path.exists(args.overrides):
        with open(args.overrides, encoding="utf-8") as f:
            ov = json.load(f)
        forced_map.update(ov.get("mappings", {}))
        ovmap = {int(o["line"]): o for o in ov.get("rows", [])}
    if getattr(args, "config", None) and os.path.exists(args.config):
        with open(args.config, encoding="utf-8") as f:
            config = json.load(f)
    policies = None
    if getattr(args, "policies", None) and os.path.exists(args.policies):
        with open(args.policies, encoding="utf-8") as f:
            policies = json.load(f)

    mapping, passthrough_cols, ambiguous = map_headers(headers, forced_map)
    missing = [t for t in REQUIRED if t not in mapping]
    report_min = {
        "schema_version": SCHEMA_VERSION,
        "engine": {"version": ENGINE_VERSION},
        "run": {"as_of": args.as_of, "input_file": os.path.basename(args.input),
                "input_sha256": sha256(args.input)},
        "mapping": {"fields": mapping, "ambiguous": ambiguous,
                    "passthrough_columns": passthrough_cols},
    }
    if missing:
        report_min["run"]["verdict"] = "blocked"
        report_min["run"]["verdict_reasons"] = [
            f"required columns not found: {missing}",
            f"columns seen: {[norm_header(h) for h in headers]}"]
        jdump(report_min, args.report)
        path = write_template(aux_out_path(args, "redpill_input_template.csv"))
        sys.exit(f"Missing required columns: {missing}. Mapping report -> {args.report}. "
                 f"A fill-in template was written to {path}.")

    src = {t: m["source"] for t, m in mapping.items()}
    as_of = date.fromisoformat(args.as_of)

    if "qoo" not in mapping:
        assumptions.append("No QOO/in-transit column found: assumed QOO = 0 for ALL rows.")

    rows, gaps = [], []
    first_seen = {}   # key -> (line, kept_bool)  — deterministic duplicate rule (G8)
    overrides_applied = 0
    for i, r in enumerate(raw, start=2):
        ov = ovmap.get(i, {})
        if ov.get("skip"):
            assumptions.append(f"line {i}: row skipped by user override "
                               f"({ov.get('reason', 'no reason given')})")
            overrides_applied += 1
            continue
        sets = ov.get("set", {})
        sku = str(sets.get("sku", r[src["sku"]])).strip()
        store = str(sets.get("store", r[src["store"]])).strip()
        problems, row_prov, row_warn = [], [], []
        if sets:
            overrides_applied += 1
        if not sku:
            problems.append("sku is blank")
        if not store:
            problems.append("store is blank")
        key = (sku.lower(), store.lower())
        if sku and store and key in first_seen:
            fl, kept = first_seen[key]
            problems.append(f"duplicate of line {fl} "
                            f"({'kept' if kept else 'itself quarantined'}) — "
                            f"first occurrence wins")

        def parse(field, default_blank=None):
            if field not in src:
                return default_blank, ""
            rawv = r.get(src[field], "")
            v, note = fnum(rawv)
            if note:
                row_prov.append(f"{field}: {note}")
            return v, str(rawv).strip()

        soh, soh_raw = parse("soh")
        qoo, qoo_raw = parse("qoo")
        ads, ads_raw = parse("ads")
        lt, lt_raw = parse("lead_time")
        price, price_raw = parse("price")
        reserved, _ = parse("reserved")
        damaged, _ = parse("damaged")
        case_pack, _ = parse("case_pack")
        eta = str(r.get(src.get("expected_receipt_date", ""), "")).strip() or None

        # user overrides (G13/G14): explicit, provenance-logged, never silent
        _local = {"soh": soh, "qoo": qoo, "ads": ads, "lead_time": lt, "price": price,
                  "reserved": reserved, "damaged": damaged, "case_pack": case_pack}
        for field, new in sets.items():
            if field in ("sku", "store", "resolution"):
                continue
            newv, _ = fnum(new)
            if newv is None:
                problems.append(f"override for {field} is not a number ('{new}')")
                continue
            old = _local.get(field)
            if field == "ads" and old is not None and old > 0:
                swing = abs(newv - old) / old
                if swing > args.max_ads_swing:
                    row_warn.append(
                        f"ads override {old:g} -> {newv:g} swings "
                        f"{swing*100:.0f}% (> {args.max_ads_swing*100:.0f}% cap) — "
                        f"applied, but review before changing master data")
            row_prov.append(f"{field}: user override "
                            f"{'(blank)' if old is None else f'{old:g}'} -> {newv:g}")
            _local[field] = newv
        soh, qoo, ads, lt = _local["soh"], _local["qoo"], _local["ads"], _local["lead_time"]
        price, reserved = _local["price"], _local["reserved"]
        damaged, case_pack = _local["damaged"], _local["case_pack"]
        if sets:
            soh_raw = str(sets.get("soh", soh_raw))
            qoo_raw = str(sets.get("qoo", qoo_raw))
            ads_raw = str(sets.get("ads", ads_raw))
            lt_raw = str(sets.get("lead_time", lt_raw))

        if soh is None:
            problems.append(f"soh not a number ('{soh_raw}')")
        elif soh < 0:
            problems.append(f"soh negative ({soh:g}) — physical stock cannot be < 0")
        elif soh != int(soh):
            row_warn.append(f"soh fractional ({soh:g}) — physical units expected")
        if qoo is None:
            if qoo_raw == "" or "qoo" not in src:
                qoo = 0.0
                if "qoo" in src:
                    assumptions.append(f"{sku}/{store}: blank QOO assumed 0")
            else:
                problems.append(f"qoo not a number ('{qoo_raw}')")
        elif qoo < 0:
            problems.append(f"qoo negative ({qoo:g})")
        elif qoo != int(qoo):
            row_warn.append(f"qoo fractional ({qoo:g})")
        if ads is None:
            problems.append("ads blank/non-numeric — blank is NOT zero demand; "
                            "fill actual units/day")
        elif ads < 0:
            problems.append(f"ads negative ({ads:g})")
        elif ads == 0:
            row_warn.append("ADS = 0 stated — treated as zero demand (stock -> overstock "
                            "donor; no reorder). Verify this is not missing master data")
        if lt is None or lt <= 0:
            problems.append(f"lead_time missing or <= 0 ('{lt_raw}') — need supplier days "
                            f"for this SKU at this store")
        if price is None and price_raw not in ("", None) and "price" in src:
            row_warn.append(f"price unreadable ('{price_raw}') — order/transfer values "
                            f"omitted for this row")  # G1: never silent
        bf = args.buffer_factor
        if "buffer_factor" in src and str(r.get(src["buffer_factor"], "")).strip():
            bf_row, _ = fnum(r[src["buffer_factor"]])
            if bf_row is None or bf_row <= 0:
                problems.append(f"buffer_factor invalid ('{r[src['buffer_factor']]}')")
            else:
                bf = bf_row
                if bf_row != args.buffer_factor:
                    assumptions.append(f"{sku}/{store}: per-row buffer factor {bf_row:g} used")

        if problems:
            gap = {"line": i, "sku": sku, "store": store,
                   "soh": soh_raw, "qoo": qoo_raw, "ads": ads_raw,
                   "lead_time": lt_raw, "unit_price": price_raw,
                   "reason": "; ".join(problems), "_rawrow": dict(r)}
            gaps.append(gap)
            if sku and store and key not in first_seen:
                first_seen[key] = (i, False)
            continue
        first_seen[key] = (i, True)

        d = compute_row(soh, qoo, ads, lt, bf, args.target_factor, price)
        d.update({
            "line": i, "sku": sku, "store": store, "soh": soh, "qoo": qoo,
            "ads": ads, "lead_time": lt, "price": price,
            "reserved": reserved, "damaged": damaged, "case_pack": case_pack,
            "expected_receipt_date": eta,
            "expected_delivery": (as_of + timedelta(days=int(lt))).isoformat(),
            "reorder_qty_net": d["reorder_qty"],
            "passthrough": {c: r.get(c, "") for c in passthrough_cols},   # G5
            "provenance": row_prov, "warnings": row_warn,
        })
        rows.append(d)
        warnings.extend(f"{sku}/{store}: {w}" for w in row_warn)
        provenance.extend(f"{sku}/{store}: {p}" for p in row_prov)

    if not rows:
        _write_quarantine(args.gaps, gaps)
        sys.exit(f"No valid rows — all {len(gaps)} rows quarantined to {args.gaps}. "
                 f"Fix the 'reason' items and rerun.")

    # ---- demand module (G18/G19/G29) + optional application (governed, G14) ----
    promo_weeks = (config or {}).get("promo_weeks_ago", [])
    ads_corrections, plausibility = analyze_demand(rows, promo_weeks)
    if args.apply_ads_corrections:
        by_line = {c["line"]: c for c in ads_corrections}
        for r in rows:
            c = by_line.get(r["line"])
            if not c or c["confidence"] == "low":
                continue
            stated = r["ads"]
            new = c["actual_ads"]
            if stated > 0:
                lo, hi = stated * (1 - args.max_ads_swing), stated * (1 + args.max_ads_swing)
                capped = min(max(new, lo), hi)
                if capped != new:
                    r["warnings"].append(f"ads correction capped {new:g} -> {capped:g} "
                                         f"(±{args.max_ads_swing*100:.0f}% swing cap)")
                new = capped
            r["provenance"].append(f"ads: engine correction {stated:g} -> {new:g} "
                                   f"({c['confidence']} confidence) — applied by flag")
            r["ads"] = new
            d = compute_row(r["soh"], r["qoo"], r["ads"], r["lead_time"],
                            args.buffer_factor, args.target_factor, r["price"])
            r.update(d)
            r["reorder_qty_net"] = r["reorder_qty"]
    # clearance / no-reorder policy (G25)
    if policies:
        stop_skus = {str(x).lower() for x in policies.get("no_reorder_skus", [])}
        for r in rows:
            if r["sku"].lower() in stop_skus and r["reorder_qty"] > 0:
                warnings.append(f"{r['sku']}/{r['store']}: fresh order suppressed by "
                                f"no-reorder policy (clearance)")
                r["reorder_qty"] = 0
                r["reorder_qty_net"] = 0
                r["order_value"] = 0.0

    transfers, transfer_notes = build_transfers(
        rows, args.savings_rate, warnings,
        transfer_days=args.transfer_days, policies=policies,
        cost_per_unit=args.transfer_cost_per_unit)
    gaps = build_candidates(gaps, rows, src)

    # INCOMING sufficiency/lateness risk (G34)
    incoming_risk = 0
    incoming_no_eta = False
    for r in rows:
        r["incoming_risk"] = None
        if r["status"] != "INCOMING":
            continue
        risks = []
        if r["pipeline"] < CRITICAL_FRACTION_OF_ROP * r["rop"]:
            risks.append("inbound covers under half the danger line — order more now")
        elif r["pipeline"] < r["rop"]:
            risks.append("inbound stays below the reorder point — top-up order needed")
        eta = r.get("expected_receipt_date")
        if eta:
            try:
                eta_d = date.fromisoformat(str(eta))
                if (eta_d - as_of).days > r["lead_time"]:
                    risks.append(f"arrives {eta} — later than a fresh order "
                                 f"({r['lead_time']:g}d) would")
            except ValueError:
                risks.append(f"expected receipt date '{eta}' unreadable")
        else:
            incoming_no_eta = True
        if risks:
            r["incoming_risk"] = "; ".join(risks)
            r["warnings"].append("incoming risk: " + r["incoming_risk"])
            incoming_risk += 1
    if incoming_no_eta:
        assumptions.append("INCOMING rows carry no expected receipt date — inbound is "
                           "assumed to arrive within its lead time (lower confidence)")

    # Projected stockout date (G36): when does the shelf actually reach zero?
    # Honest arithmetic from the snapshot — current stock burns at ADS; inbound
    # extends cover only if it lands before the shelf runs dry. Not a simulation:
    # with one aggregate QOO and at most one ETA per row, this IS the projection.
    eta_assumed = False
    stockout_before_inbound = 0
    for r in rows:
        r["projected_stockout_date"] = None
        r["stockout_before_inbound_days"] = None
        if r["ads"] <= 0:
            continue
        dry_days = r["soh"] / r["ads"]
        if r["qoo"] > 0:
            eta_d = None
            if r["expected_receipt_date"]:
                try:
                    eta_d = date.fromisoformat(str(r["expected_receipt_date"]))
                except ValueError:
                    eta_d = None
            if eta_d is None:
                eta_d = as_of + timedelta(days=int(r["lead_time"]))
                eta_assumed = True
            elif eta_d < as_of:      # promised date passed, PO still open — overdue
                r["warnings"].append(f"inbound overdue — receipt date "
                                     f"{eta_d.isoformat()} already passed; "
                                     f"projection assumes it lands now")
                eta_d = as_of
            gap = (eta_d - as_of).days - dry_days
            if gap > 0:      # shelf goes dark before the inbound lands
                r["stockout_before_inbound_days"] = round(gap, 1)
                r["projected_stockout_date"] = (
                    as_of + timedelta(days=math.floor(dry_days))).isoformat()
                stockout_before_inbound += 1
                if r["soh"] > 0:   # empty-shelf rows already say INCOMING
                    r["warnings"].append(
                        f"projected dry {r['projected_stockout_date']} — "
                        f"{r['stockout_before_inbound_days']:g} day(s) before "
                        f"inbound lands ({eta_d.isoformat()})")
            else:            # inbound lands in time; total pipeline sets the date
                r["projected_stockout_date"] = (
                    as_of + timedelta(days=math.floor((r["soh"] + r["qoo"])
                                                      / r["ads"]))).isoformat()
        else:
            r["projected_stockout_date"] = (
                as_of + timedelta(days=math.floor(dry_days))).isoformat()
    if eta_assumed:
        assumptions.append("rows with inbound but no expected receipt date: stockout "
                           "projection assumes arrival at the supplier lead time")

    # overcommit flag (G24) + ATP disclosure (G26) + mitigations (G28)
    overcommit = 0
    for r in rows:
        r["overcommit"] = (r["status"] not in ("OVERSTOCK",)
                           and r["pipeline"] > OVERSTOCK_X_BUFFER * r["buffer"])
        if r["overcommit"]:
            overcommit += 1
            r["warnings"].append("over-committed: inbound orders exceed 2x buffer — "
                                 "consider trimming the open order")
        if (r["reserved"] or r["damaged"]) and sellable(r) != r["soh"]:
            r["provenance"].append(f"sellable stock {sellable(r):g} "
                                   f"(SOH {r['soh']:g} − reserved/damaged) used for donor math")
        if r.get("mitigation") is None:
            r["mitigation"] = None
        if (r["status"] in ("OUT_OF_STOCK", "CRITICAL") and r["mitigation"] is None
                and r["days_of_stock"] is not None
                and r["days_of_stock"] < r["lead_time"]
                and not any(t["to_store"] == r["store"] and t["sku"] == r["sku"]
                            for t in transfers)):
            r["mitigation"] = ("supply lands after the stockout — expedite, "
                              "substitute, or hold remaining stock for full price")

    weighted_health = segment_rows(rows)          # ABC-XYZ + weighted view (G20/#5)
    curve_breaks = size_curve_breaks(rows)        # G21

    # Financial impact (G37) — estimated, never "realised". Price missing => null
    # (counted, never fabricated as zero).
    rev_risk_total = capital_total = 0.0
    rev_risk_missing = capital_missing = 0
    for r in rows:
        r["daily_revenue_at_risk"] = None
        r["capital_tied_up"] = None
        if r["status"] in ("OUT_OF_STOCK", "CRITICAL") and r["ads"] > 0:
            if r["price"] is not None:
                r["daily_revenue_at_risk"] = round(r["ads"] * r["price"], 2)
                rev_risk_total += r["daily_revenue_at_risk"]
            else:
                rev_risk_missing += 1
        if r["status"] == "OVERSTOCK":
            excess = max(0.0, r["soh"] - r["buffer"])   # everything above protection
            if r["price"] is not None:
                r["capital_tied_up"] = round(excess * r["price"], 2)
                capital_total += r["capital_tied_up"]
            else:
                capital_missing += 1

    # G3: engine owns every total. Order totals are ACTIONABLE-ONLY by definition (G2).
    for r in rows:
        r["order_value_net"] = (round(r["reorder_qty_net"] * r["price"], 2)
                                if r["price"] is not None else None)
    gross_order = round(sum(r["order_value"] or 0 for r in rows), 2)
    net_order = round(sum(r["order_value_net"] or 0 for r in rows), 2)
    missing_price_orders = sum(1 for r in rows
                               if r["reorder_qty_net"] > 0 and r["price"] is None)
    if missing_price_orders:
        warnings.append(f"{missing_price_orders} order line(s) have no readable price — "
                        f"order totals understate true spend")

    counts = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    n = len(rows)
    actionable_rows = sum(counts[s] for s in ACTIONABLE)
    kpis = {
        "rows": n, "quarantined": len(gaps),
        "status_counts": counts,
        "health_pct": round(100.0 * counts["OPTIMAL"] / n, 1),
        "action_rate_pct": round(100.0 * actionable_rows / n, 1),
        "excess_rate_pct": round(100.0 * counts["OVERSTOCK"] / n, 1),
        "actionable_rows": actionable_rows,
        "gross_order_value": gross_order,
        "net_order_value": net_order,
        "order_lines_missing_price": missing_price_orders,
        "transfers": {
            "count": len(transfers),
            "units": sum(t["qty"] for t in transfers),
            "value": round(sum(t["value"] or 0 for t in transfers), 2),
            "est_saving": round(sum(t["est_saving"] or 0 for t in transfers), 2),
            "est_cost": (round(sum(t["est_transfer_cost"] for t in transfers
                                   if t["est_transfer_cost"] is not None), 2)
                         if any(t["est_transfer_cost"] is not None for t in transfers)
                         else None),
            "net_benefit": (round(sum(t["net_benefit"] for t in transfers
                                      if t["net_benefit"] is not None), 2)
                            if any(t["net_benefit"] is not None for t in transfers)
                            else None),
            "missing_value_count": sum(1 for t in transfers if t["value"] is None),
        },
        "money_labels": {"order_values": "potential", "transfer_savings": "estimated",
                         "revenue_at_risk": "estimated", "capital_tied_up": "estimated"},
        "financial_impact": {                                   # G37 — all estimated
            "daily_revenue_at_risk": round(rev_risk_total, 2),
            "at_risk_rows_missing_price": rev_risk_missing,
            "capital_tied_up": round(capital_total, 2),
            "overstock_rows_missing_price": capital_missing,
        },
        "stockout_before_inbound_count": stockout_before_inbound,   # G36
        "overcommit_count": overcommit,
        "incoming_risk_count": incoming_risk,
        "weighted_health_pct": weighted_health,
        "ads_corrections_count": len(ads_corrections),
        "size_curve_breaks_count": len(curve_breaks),
    }
    if args.budget and args.budget > 0:            # G23: within-budget / deferred split
        remaining = args.budget
        within_v = deferred_v = 0.0
        deferred_n = 0
        ordered = sorted([r for r in rows if r["reorder_qty_net"] > 0],
                         key=lambda r: (r["days_of_stock"]
                                        if r["days_of_stock"] is not None else 0.0,
                                        r["line"]))
        for r in ordered:
            v = r["order_value_net"] or 0
            if v <= remaining:
                r["budget_status"] = "within"
                remaining -= v
                within_v += v
            else:
                r["budget_status"] = "deferred"
                deferred_v += v
                deferred_n += 1
        kpis["budget"] = {"limit": args.budget, "within_value": round(within_v, 2),
                          "deferred_value": round(deferred_v, 2),
                          "deferred_lines": deferred_n}

    # Urgency: rows that need a human move now; nothing-to-do rows excluded (G8/R4).
    urgency = sorted(
        [r for r in rows if r["actionable"]
         and (r["reorder_qty_net"] > 0 or r["status"] == "INCOMING")],
        key=lambda r: (r["days_of_stock"] if r["days_of_stock"] is not None else 0.0,
                       r["line"]))

    # Run verdict (G7)
    qpct = 100.0 * len(gaps) / (n + len(gaps))
    verdict, reasons = "healthy", []
    if ambiguous:
        verdict = "degraded"
        reasons.append(f"{len(ambiguous)} ambiguous column mapping(s) — confirm before trusting")
    if qpct > 20:
        verdict = "degraded"
        reasons.append(f"{qpct:.0f}% of rows quarantined — fill the gaps and rerun")
    if qpct > 60:
        verdict = "blocked"
        reasons.append("majority of rows unusable — do not act on this run")

    report = dict(report_min)
    report["engine"]["parameters"] = {
        "buffer_factor": args.buffer_factor, "target_factor": args.target_factor,
        "savings_rate": args.savings_rate}
    report["run"].update({"verdict": verdict, "verdict_reasons": reasons,
                          "quarantine_pct": round(qpct, 1),
                          "overrides_applied": overrides_applied})
    if config is not None:
        report["run"]["config"] = config
    report.update({
        "kpis": kpis,
        "rows": sorted(rows, key=lambda r: r["line"]),
        "transfers": transfers,
        "transfer_notes": transfer_notes,
        "transfer_lanes": [
            {"from_store": f, "to_store": t,
             "transfers": sum(1 for x in transfers
                              if x["from_store"] == f and x["to_store"] == t),
             "units": sum(x["qty"] for x in transfers
                          if x["from_store"] == f and x["to_store"] == t)}
            for f, t in sorted({(x["from_store"], x["to_store"]) for x in transfers})],
        "ads_corrections": ads_corrections,
        "plausibility_flags": plausibility,
        "size_curve_breaks": curve_breaks,
        "policy_applications": [w for w in warnings if "policy" in w or "protected" in w],
        "urgency": [{"sku": r["sku"], "store": r["store"], "status": r["status"],
                     "days_of_stock": r["days_of_stock"],
                     "reorder_qty_net": r["reorder_qty_net"]} for r in urgency],
        "quarantine": gaps,
        "assumptions": assumptions, "warnings": warnings, "provenance": provenance,
    })
    # G38: one place that separates configurable business POLICY from computed math.
    # Everything here is a choice someone can defend or change — not a formula result.
    report["assumptions_and_policies"] = {
        "note": ("business policies and disclosed assumptions in effect for this run — "
                 "policy values are configurable choices, not mathematical facts"),
        "policy_parameters": {
            "buffer_factor": args.buffer_factor,
            "target_factor": args.target_factor,
            "savings_rate": args.savings_rate,
            "critical_threshold_of_rop": CRITICAL_FRACTION_OF_ROP,
            "overstock_multiple_of_buffer": OVERSTOCK_X_BUFFER,
            "ads_correction_trigger_pct": round(ADS_CORRECTION_TRIGGER * 100),
            "volatility_cv_threshold": CV_VOLATILE,
            "max_ads_swing": args.max_ads_swing,
            "transfer_days": args.transfer_days or None,
            "transfer_cost_per_unit": args.transfer_cost_per_unit or None,
            "budget": args.budget or None,
        },
        "policy_file_loaded": policies is not None,
        "policy_applications": report["policy_applications"],
        "assumptions": assumptions,
    }
    jdump(report, args.report)

    # computed.csv — includes passthrough columns (G5); "" is the one empty sentinel (G8/C2)
    out_fields = (["sku", "store", "soh", "qoo", "ads", "lead_time", "price",
                   "pipeline", "buffer", "rop", "days_of_stock", "current_cover",
                   "projected_stockout_date", "status",
                   "status_reason", "reorder_qty", "reorder_qty_net",
                   "order_value", "order_value_net", "expected_delivery"]
                  + passthrough_cols)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(out_fields)
        for r in sorted(rows, key=lambda x: (x["days_of_stock"]
                                             if x["days_of_stock"] is not None else 0.0,
                                             x["line"])):
            base = [r["sku"], r["store"], r["soh"], r["qoo"], r["ads"], r["lead_time"],
                    "" if r["price"] is None else r["price"],
                    r["pipeline"], r["buffer"], r["rop"],
                    "" if r["days_of_stock"] is None else r["days_of_stock"],
                    "" if r["current_cover"] is None else r["current_cover"],
                    "" if r["projected_stockout_date"] is None
                    else r["projected_stockout_date"],
                    r["status"], r["status_reason"], r["reorder_qty"], r["reorder_qty_net"],
                    "" if r["order_value"] is None else r["order_value"],
                    "" if r["order_value_net"] is None else r["order_value_net"],
                    r["expected_delivery"]]
            w.writerow(base + [r["passthrough"].get(c, "") for c in passthrough_cols])

    if gaps:
        _write_quarantine(args.gaps, gaps)

    # compact compatibility summary (subset of report.json — never diverges)
    jdump({"schema_version": SCHEMA_VERSION, "kpis": kpis,
           "urgency_top10": report["urgency"][:10],
           "transfer_plan": transfers,
           "data_quality": {"quarantined": [{"line": g["line"], "sku": g["sku"],
                                             "store": g["store"], "reason": g["reason"]}
                                            for g in gaps],
                            "assumptions": assumptions, "warnings": warnings},
           "run": report["run"]}, args.summary)

    msg = (f"[{verdict.upper()}] {n} rows -> {args.out}; report -> {args.report}; "
           f"health {kpis['health_pct']}% (action {kpis['action_rate_pct']}% / "
           f"excess {kpis['excess_rate_pct']}%); transfers {len(transfers)} "
           f"(₹{kpis['transfers']['value']:,.0f} moved, est ₹{kpis['transfers']['est_saving']:,.0f}); "
           f"orders net ₹{net_order:,.0f} (gross ₹{gross_order:,.0f})")
    if gaps:
        msg += f"\n⚠ {len(gaps)} row(s) quarantined -> {args.gaps} (fill-in form; fix and rerun)"
    print(msg)
    return report


def _write_quarantine(path, gaps):
    with open(path, "w", newline="", encoding="utf-8") as f:
        fields = TEMPLATE_HEADER + ["line", "reason"]
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for g in gaps:
            w.writerow(g)


# ---------------------------------------------------------------- run dirs (G32)
def setup_run_dir(args):
    rd = args.run_dir
    os.makedirs(os.path.join(rd, "input"), exist_ok=True)
    input_copy = os.path.join(rd, "input", os.path.basename(args.input))
    if not os.path.exists(input_copy):
        shutil.copy2(args.input, input_copy)
    args.input = input_copy          # analyze the immutable copy
    args.out = os.path.join(rd, "computed.csv")
    args.summary = os.path.join(rd, "summary.json")
    args.gaps = os.path.join(rd, "quarantine.csv")
    args.report = os.path.join(rd, "report.json")
    for attr, name in (("overrides", "overrides.json"), ("mappings", "mappings.json"),
                       ("config", "config.json"), ("policies", "policies.json")):
        src_path = getattr(args, attr, None)
        if src_path and os.path.exists(src_path):
            dst = os.path.join(rd, name)
            if os.path.abspath(src_path) != os.path.abspath(dst):
                shutil.copy2(src_path, dst)
            setattr(args, attr, dst)
    jdump({"engine_version": ENGINE_VERSION, "schema_version": SCHEMA_VERSION,
           "as_of": args.as_of, "input_file": os.path.basename(input_copy),
           "parameters": {"buffer_factor": args.buffer_factor,
                          "target_factor": args.target_factor,
                          "savings_rate": args.savings_rate}},
          os.path.join(rd, "config_snapshot.json"))
    return rd


def write_manifest(args):
    rd = args.run_dir
    outputs = {}
    for name in ["report.json", "computed.csv", "summary.json", "quarantine.csv",
                 "overrides.json", "mappings.json", "config.json"]:
        p = os.path.join(rd, name)
        if os.path.exists(p):
            outputs[name] = sha256(p)
    jdump({"engine_version": ENGINE_VERSION, "schema_version": SCHEMA_VERSION,
           "as_of": args.as_of, "input_sha256": sha256(args.input),
           "outputs": outputs},
          os.path.join(rd, "run-manifest.json"))


def rerun(run_dir):
    """Reproduce a prior run from its directory and verify identical report.json."""
    cfg = json.load(open(os.path.join(run_dir, "config_snapshot.json")))
    manifest = json.load(open(os.path.join(run_dir, "run-manifest.json")))
    args = argparse.Namespace(
        input=os.path.join(run_dir, "input", cfg["input_file"]),
        as_of=cfg["as_of"],
        buffer_factor=cfg["parameters"]["buffer_factor"],
        target_factor=cfg["parameters"]["target_factor"],
        savings_rate=cfg["parameters"]["savings_rate"],
        out=os.devnull, summary=os.devnull, gaps=os.devnull,
        report=os.path.join(run_dir, "report.rerun.json"),
        overrides=os.path.join(run_dir, "overrides.json"),
        mappings=os.path.join(run_dir, "mappings.json"),
        config=os.path.join(run_dir, "config.json"),
        max_ads_swing=0.5, transfer_days=0, budget=0, transfer_cost_per_unit=0,
        policies=os.path.join(run_dir, "policies.json"),
        apply_ads_corrections=False,
    )
    run(args)
    old = manifest["outputs"].get("report.json")
    new = sha256(args.report)
    ok = old == new
    print(f"reproducibility: {'MATCH' if ok else 'MISMATCH'} "
          f"(report.json {new[:12]} vs recorded {str(old)[:12]})")
    if ok:
        os.remove(args.report)
    return 0 if ok else 1


# ---------------------------------------------------------------- CLI
def main():
    p = argparse.ArgumentParser()
    p.add_argument("input", nargs="?")
    p.add_argument("--run-dir", help="write all outputs + input copy + manifest here (G32)")
    p.add_argument("--rerun", metavar="RUN_DIR",
                   help="reproduce a prior run directory and verify identical output")
    p.add_argument("--as-of", default=None,
                   help="data snapshot date YYYY-MM-DD (default: today). Drives "
                        "expected-delivery dates and reproducibility.")
    p.add_argument("--out", default="computed.csv")
    p.add_argument("--summary", default="summary.json")
    p.add_argument("--gaps", default=None,
                   help="quarantined-rows file (default: data_gaps.csv next to "
                        "--out/--report, or CWD when neither has a directory)")
    p.add_argument("--report", default="report.json")
    p.add_argument("--template", action="store_true")
    p.add_argument("--buffer-factor", type=float, default=1.5)
    p.add_argument("--target-factor", type=float, default=2.5)
    p.add_argument("--savings-rate", type=float, default=0.15)
    p.add_argument("--overrides", help="overrides.json: user-confirmed answers "
                   "({rows:[{line,set:{field:value}|skip}],mappings:{header:target}}). "
                   "Raw input stays immutable; the whole analysis reruns.")
    p.add_argument("--mappings", help="mappings.json: user-confirmed header->target map "
                   "(project-local mapping memory, G33)")
    p.add_argument("--config", help="profile config json (echoed into report.run.config)")
    p.add_argument("--max-ads-swing", type=float, default=0.5,
                   help="warn when an ads override moves more than this fraction (G14)")
    p.add_argument("--transfer-days", type=float, default=0,
                   help="inter-store truck time in days; receivers whose supplier is "
                        "faster get a fresh order instead (0 = gate off, G22)")
    p.add_argument("--transfer-cost-per-unit", type=float, default=0,
                   help="flat per-unit transfer cost; per-lane overrides via policies "
                        "lane_costs [[from,to,cost]] (0 = unknown, fields stay null; G35)")
    p.add_argument("--budget", type=float, default=0,
                   help="purchase budget; orders split within/deferred by urgency (G23)")
    p.add_argument("--policies", help="policies.json: protected_stores, "
                   "no_transfer_lanes [[from,to]], no_reorder_skus (G25)")
    p.add_argument("--apply-ads-corrections", action="store_true",
                   help="apply engine ADS corrections (non-low confidence, capped) to "
                        "this run's math — normally done after user approval (G14)")
    args = p.parse_args()

    if args.rerun:
        sys.exit(rerun(args.rerun))
    if args.template or not args.input:
        path = write_template(aux_out_path(args, "redpill_input_template.csv"))
        print(f"Template written to {path}. Fill it in (one row per SKU x Store) and rerun:")
        print(f"  python redpill_engine.py {path}")
        return
    if args.as_of is None:
        args.as_of = date.today().isoformat()
    date.fromisoformat(args.as_of)  # validate early
    if args.gaps is None:
        args.gaps = aux_out_path(args, "data_gaps.csv")
    if args.run_dir:
        setup_run_dir(args)
    run(args)
    if args.run_dir:
        write_manifest(args)


if __name__ == "__main__":
    main()
