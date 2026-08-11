#!/usr/bin/env python3
"""Red Pill engine v2 test suite (stdlib only).

Golden assertions pin the SPEC.md §1 reference numbers exactly; property tests
enforce the invariants from SPEC §5 / G30. Run:

    python3 -m unittest discover -s tests -v
"""
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ENGINE = os.path.join(REPO, "skills", "redpill-inventory", "scripts", "redpill_engine.py")
GEN = os.path.join(HERE, "fixtures", "gen_stress_mis.py")
AS_OF = "2026-08-10"

sys.path.insert(0, os.path.dirname(ENGINE))
import redpill_engine as eng  # noqa: E402


def jload(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run_engine(input_csv, workdir, extra=None):
    cmd = [sys.executable, ENGINE, input_csv, "--as-of", AS_OF,
           "--run-dir", workdir]
    cmd += extra or []
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc, os.path.join(workdir, "report.json")


class Base(unittest.TestCase):
    tmp = None
    report = None

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="redpill_test_")
        subprocess.run([sys.executable, GEN, cls.tmp], check=True,
                       capture_output=True)
        cls.v1 = os.path.join(cls.tmp, "stress_mis_v1.csv")
        cls.v2 = os.path.join(cls.tmp, "stress_mis_v2.csv")
        cls.rundir = os.path.join(cls.tmp, "run_v1")
        proc, rep = run_engine(cls.v1, cls.rundir)
        assert proc.returncode == 0, proc.stderr + proc.stdout
        cls.report = jload(rep)


class TestGoldenReference(Base):
    """SPEC.md §1 — the corrected reference numbers, asserted exactly."""

    def test_rows_and_quarantine(self):
        k = self.report["kpis"]
        self.assertEqual(k["rows"], 351)
        self.assertEqual(k["quarantined"], 10)

    def test_status_counts(self):
        self.assertEqual(self.report["kpis"]["status_counts"], {
            "OUT_OF_STOCK": 24, "INCOMING": 17, "CRITICAL": 47,
            "REORDER": 62, "OVERSTOCK": 43, "OPTIMAL": 158})

    def test_rates(self):
        k = self.report["kpis"]
        self.assertEqual(k["health_pct"], 45.0)
        self.assertEqual(k["action_rate_pct"], 42.7)
        self.assertEqual(k["excess_rate_pct"], 12.3)

    def test_order_values_actionable_only(self):
        k = self.report["kpis"]
        self.assertEqual(k["gross_order_value"], 16332241.0)
        self.assertEqual(k["net_order_value"], 11640751.0)

    def test_transfers(self):
        t = self.report["kpis"]["transfers"]
        self.assertEqual(t["count"], 83)
        self.assertEqual(t["value"], 4691490.0)
        self.assertEqual(t["est_saving"], 703723.5)
        self.assertEqual(t["missing_value_count"], 0)  # G1: ₹2,499 parses

    def test_urgency_top3_and_dead_stock_excluded(self):
        top3 = [(u["sku"], u["store"]) for u in self.report["urgency"][:3]]
        self.assertEqual(top3, [("TSH-CRW-BLK-M", "Delhi (CP)"),
                                ("TSH-CRW-BLK-M", "Chennai"),
                                ("POL-TSH-RED-M", "Kochi")])
        urgent_keys = {(u["sku"], u["store"]) for u in self.report["urgency"]}
        for r in self.report["rows"]:
            if r["ads"] == 0:
                self.assertIsNone(r["days_of_stock"])          # G8
                self.assertNotIn((r["sku"], r["store"]), urgent_keys)  # R4

    def test_run_verdict_healthy(self):
        self.assertEqual(self.report["run"]["verdict"], "healthy")
        self.assertEqual(self.report["run"]["as_of"], AS_OF)

    def test_duplicate_rule_documented(self):
        dups = [g for g in self.report["quarantine"] if "duplicate" in g["reason"]]
        self.assertEqual(len(dups), 1)
        self.assertIn("first occurrence wins", dups[0]["reason"])


class TestProperties(Base):
    """Invariants (G30): these must hold on any input, asserted on the fixture."""

    def test_orders_only_for_actionable(self):
        for r in self.report["rows"]:
            if r["status"] in ("OPTIMAL", "OVERSTOCK"):
                self.assertEqual(r["reorder_qty"], 0, r["sku"])
            self.assertGreaterEqual(r["reorder_qty"], 0)
            self.assertGreaterEqual(r["reorder_qty_net"], 0)
            self.assertLessEqual(r["reorder_qty_net"], r["reorder_qty"])

    def test_donors_never_dip_below_buffer(self):
        sent = {}
        for t in self.report["transfers"]:
            sent[(t["sku"], t["from_store"])] = sent.get((t["sku"], t["from_store"]), 0) + t["qty"]
        rows = {(r["sku"], r["store"]): r for r in self.report["rows"]}
        for key, q in sent.items():
            r = rows[key]
            self.assertGreaterEqual(r["soh"] - q, r["buffer"] - 1e-9, key)

    def test_no_action_from_quarantined_rows(self):
        qkeys = {(g["sku"].lower(), g["store"].lower())
                 for g in self.report["quarantine"] if g["sku"] and g["store"]}
        processed = {(r["sku"].lower(), r["store"].lower()) for r in self.report["rows"]}
        # a key may exist in both only via the duplicate rule (first copy processed)
        for t in self.report["transfers"]:
            self.assertIn((t["sku"].lower(), t["from_store"].lower()), processed)
            self.assertIn((t["sku"].lower(), t["to_store"].lower()), processed)
        for key in qkeys - processed:
            self.assertNotIn(key, {(u["sku"].lower(), u["store"].lower())
                                   for u in self.report["urgency"]})

    def test_totals_reconcile(self):
        # every donor/receiver shares the SKU price in this fixture, so
        # gross - net must equal the transfer value exactly.
        k = self.report["kpis"]
        self.assertAlmostEqual(k["gross_order_value"] - k["net_order_value"],
                               k["transfers"]["value"], places=2)

    def test_passthrough_columns_present(self):
        row = self.report["rows"][0]
        for col in ("Style Name", "Colour", "System Status", "Sold W-1", "Supplier"):
            self.assertIn(col, row["passthrough"])
        with open(os.path.join(self.rundir, "computed.csv"), encoding="utf-8") as fh:
            header = fh.readline()
        self.assertIn("System Status", header)
        self.assertIn("Sold W-1", header)


class TestParsing(unittest.TestCase):
    def test_fnum_real_world_formats(self):
        cases = {"1,240": 1240.0, "₹2,499": 2499.0, "  8 ": 8.0, "Rs. 450": 450.0,
                 "INR 99": 99.0, "(500)": -500.0, "12.5": 12.5, "0": 0.0}
        for raw, want in cases.items():
            got, _ = eng.fnum(raw)
            self.assertEqual(got, want, raw)
        for bad in ("", None, "N/A", "abc", "7 days"):
            got, _ = eng.fnum(bad)
            self.assertIsNone(got, bad)

    def test_header_normalization(self):
        self.assertEqual(eng.norm_header("Avg Off-take/Day"), "avg_off_take_day")
        self.assertEqual(eng.norm_header("Lead Time (Days)"), "lead_time_days")
        self.assertEqual(eng.norm_header("  Closing Stock "), "closing_stock")

    def test_unparseable_price_warns_not_silent(self):
        with tempfile.TemporaryDirectory() as td:
            f = os.path.join(td, "x.csv")
            with open(f, "w") as fh:
                fh.write("sku,store,soh,qoo,ads,lead_time,unit_price\n"
                         "A,S1,10,0,2,5,notaprice\n")
            proc, rep = run_engine(f, os.path.join(td, "run"))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = jload(rep)
            self.assertEqual(report["kpis"]["rows"], 1)
            self.assertTrue(any("price unreadable" in w for w in report["warnings"]))


class TestRunDirAndReproducibility(Base):
    def test_run_dir_contents(self):
        for name in ("report.json", "computed.csv", "quarantine.csv", "summary.json",
                     "config_snapshot.json", "run-manifest.json"):
            self.assertTrue(os.path.exists(os.path.join(self.rundir, name)), name)
        self.assertTrue(os.path.exists(
            os.path.join(self.rundir, "input", "stress_mis_v1.csv")))
        manifest = jload(os.path.join(self.rundir, "run-manifest.json"))
        self.assertEqual(manifest["engine_version"], eng.ENGINE_VERSION)
        self.assertIn("report.json", manifest["outputs"])

    def test_rerun_reproduces_identically(self):
        proc = subprocess.run([sys.executable, ENGINE, "--rerun", self.rundir],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("MATCH", proc.stdout)


class TestV2Fixture(Base):
    """The 6 new storyline rows process cleanly in Phase 0 (detection is Phase 4)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        proc, rep = run_engine(cls.v2, os.path.join(cls.tmp, "run_v2"))
        assert proc.returncode == 0, proc.stderr
        cls.r2 = jload(rep)

    def test_v2_rows(self):
        self.assertEqual(self.r2["kpis"]["rows"], 357)          # 351 + 6 new
        self.assertEqual(self.r2["kpis"]["quarantined"], 10)    # same 10 bad rows

    def test_optional_fields_carried(self):
        row = next(r for r in self.r2["rows"]
                   if r["sku"] == "SHR-RUN-BLK-M" and r["store"] == "Thane")
        self.assertEqual(row["reserved"], 10.0)
        self.assertEqual(row["damaged"], 2.0)
        self.assertEqual(row["case_pack"], 12.0)

    def test_overcommit_row_processed_as_optimal_today(self):
        # Phase 0: the ladder alone; the overcommit FLAG lands in Phase 4 (G24).
        row = next(r for r in self.r2["rows"]
                   if r["sku"] == "TSH-CRW-BLK-M" and r["store"] == "Surat")
        self.assertEqual(row["status"], "OPTIMAL")
        self.assertGreater(row["pipeline"], 2 * row["buffer"])


class TestBlockedRun(unittest.TestCase):
    def test_missing_required_columns_blocks_with_report(self):
        with tempfile.TemporaryDirectory() as td:
            f = os.path.join(td, "bad.csv")
            with open(f, "w") as fh:
                fh.write("sku,store,soh\nA,S1,5\n")
            rep = os.path.join(td, "report.json")
            proc = subprocess.run(
                [sys.executable, ENGINE, f, "--as-of", AS_OF, "--report", rep],
                capture_output=True, text=True, cwd=td)
            self.assertNotEqual(proc.returncode, 0)
            report = jload(rep)
            self.assertEqual(report["run"]["verdict"], "blocked")


class TestExample(unittest.TestCase):
    def test_bundled_example_runs(self):
        with tempfile.TemporaryDirectory() as td:
            proc, rep = run_engine(os.path.join(REPO, "examples", "sample_mis.csv"),
                                   os.path.join(td, "run"))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = jload(rep)
            self.assertEqual(report["kpis"]["rows"], 11)
            self.assertEqual(report["run"]["verdict"], "healthy")


if __name__ == "__main__":
    unittest.main()
