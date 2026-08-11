#!/usr/bin/env python3
"""Render the Red Pill cockpit from an engine report.json.

The cockpit is a fixed template (assets/cockpit_template.html) + one data
injection. It performs NO business calculations — every number on the page
comes from report.json (SPEC.md §0). Row-level what-if sliders are the one
exception by design (G11): they recompute a single hypothetical row client-side
using the same published formulas, clearly labelled, and never touch plan totals.

Usage:
    python render_cockpit.py report.json [-o cockpit.html]
    python render_cockpit.py --run-dir runs/2026-08-11   # reads/writes in the run dir
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "assets", "cockpit_template.html")
PLACEHOLDER = "__REPORT_JSON__"


def render(report_path, out_path):
    with open(report_path, encoding="utf-8") as f:
        data = f.read()
    json.loads(data)  # validate before injecting
    with open(TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()
    if PLACEHOLDER not in tpl:
        sys.exit("template is missing the __REPORT_JSON__ placeholder")
    html = tpl.replace(PLACEHOLDER, data.replace("</", "<\\/"))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"cockpit -> {out_path}")
    return out_path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("report", nargs="?", default="report.json")
    p.add_argument("-o", "--out", default=None)
    p.add_argument("--run-dir", help="use RUN_DIR/report.json -> RUN_DIR/cockpit.html")
    a = p.parse_args()
    if a.run_dir:
        report = os.path.join(a.run_dir, "report.json")
        out = a.out or os.path.join(a.run_dir, "cockpit.html")
    else:
        report, out = a.report, a.out or "cockpit.html"
    render(report, out)


if __name__ == "__main__":
    main()
