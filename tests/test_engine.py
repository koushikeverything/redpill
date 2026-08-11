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


class TestCockpitRenderer(Base):
    """G10: the cockpit is a fixed template + report.json injection, no more."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        render = os.path.join(REPO, "skills", "redpill-inventory", "scripts",
                              "render_cockpit.py")
        proc = subprocess.run([sys.executable, render, "--run-dir", cls.rundir],
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        with open(os.path.join(cls.rundir, "cockpit.html"), encoding="utf-8") as f:
            cls.html = f.read()

    def test_placeholder_replaced_with_report(self):
        self.assertNotIn("__REPORT_JSON__", self.html)
        # the embedded blob IS the report (escaped-slash tolerant)
        start = self.html.index('<script type="application/json" id="data">') + \
            len('<script type="application/json" id="data">')
        end = self.html.index("</script>", start)
        blob = json.loads(self.html[start:end].replace("<\\/", "</"))
        self.assertEqual(blob["kpis"], self.report["kpis"])
        self.assertEqual(len(blob["rows"]), len(self.report["rows"]))

    def test_money_labels_and_banner_hooks_present(self):
        for needle in ("potential", "estimated", "Today's Actions",
                       "advisory only", "report.json"):
            self.assertIn(needle, self.html, needle)

    def test_template_has_no_business_constants(self):
        # the page must not hard-code plan numbers; spot-check the golden totals
        tpl_path = os.path.join(REPO, "skills", "redpill-inventory", "assets",
                                "cockpit_template.html")
        with open(tpl_path, encoding="utf-8") as f:
            tpl = f.read()
        for forbidden in ("11640751", "4691490", "703723", "16332241"):
            self.assertNotIn(forbidden, tpl)


class TestAskBack(Base):
    """Phase 2 (G13/G14/G33): candidates, overrides merge->full rerun, mapping memory."""

    def test_candidates_inferred(self):
        q = {(g["sku"], g["store"]): g for g in self.report["quarantine"]}
        # text extraction: '7 days' -> 7
        pune = q[("SHT-OXF-WHT-L", "Pune")]
        self.assertTrue(any(c["value"] == 7 and "number found" in c["basis"]
                            for c in pune["candidates"]))
        # peer lead time for the Kolkata oxford (other stores of same SKU)
        kol = q[("SHT-OXF-BLU-M", "Kolkata")]
        peer = [c for c in kol["candidates"] if "other store" in c["basis"]]
        self.assertTrue(peer and peer[0]["value"] > 0)
        # history-derived ads for the blank-ads row
        che = q[("CHN-TRS-NVY-34", "Chennai")]
        self.assertTrue(any("sales history" in c["basis"] for c in che["candidates"]))
        # negative qoo -> candidate 0
        koc = q[("LEG-YOG-BLK-S", "Kochi")]
        self.assertTrue(any(c["value"] == 0 for c in koc["candidates"]))
        # duplicate -> resolution options
        dup = q[("TSH-CRW-WHT-L", "Pune")]
        self.assertTrue(any(c["value"] == "keep_first" for c in dup["candidates"]))
        # every gap carries a plain-language ask
        for g in self.report["quarantine"]:
            self.assertTrue(g.get("ask"))

    def test_overrides_close_every_gap(self):
        # build overrides from the engine's own candidates (the card-tap simulation)
        ov_rows = []
        for g in self.report["quarantine"]:
            if "duplicate" in g["reason"]:
                ov_rows.append({"line": g["line"], "skip": True,
                                "reason": "user kept first occurrence"})
                continue
            sets = {}
            for c in g["candidates"]:
                if c["field"] in ("lead_time", "ads", "qoo") and isinstance(c["value"], (int, float)):
                    sets.setdefault(c["field"], c["value"])
            # answers no candidate could infer (user typed them)
            if "soh" in g["reason"]:
                sets["soh"] = 6            # physical count
            if "store is blank" in g["reason"]:
                sets["store"] = "Hyderabad"
            ov_rows.append({"line": g["line"], "set": sets})
        ovp = os.path.join(self.tmp, "overrides.json")
        with open(ovp, "w") as f:
            json.dump({"rows": ov_rows}, f)
        rd = os.path.join(self.tmp, "run_ov")
        proc, rep = run_engine(self.v1, rd, extra=["--overrides", ovp])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        r2 = jload(rep)
        self.assertEqual(r2["kpis"]["quarantined"], 0)
        self.assertEqual(r2["kpis"]["rows"], 360)     # 351 + 9 fixed, dup skipped
        self.assertEqual(r2["run"]["overrides_applied"], 10)
        self.assertEqual(r2["run"]["verdict"], "healthy")
        fixed = next(r for r in r2["rows"]
                     if r["sku"] == "SHT-OXF-WHT-L" and r["store"] == "Pune")
        self.assertTrue(any("user override" in p for p in fixed["provenance"]))
        # reproducibility holds WITH overrides in the run dir
        proc2 = subprocess.run([sys.executable, ENGINE, "--rerun", rd],
                               capture_output=True, text=True)
        self.assertIn("MATCH", proc2.stdout)

    def test_ads_override_swing_cap_warns(self):
        ovp = os.path.join(self.tmp, "ov_swing.json")
        with open(ovp, "w") as f:
            json.dump({"rows": [{"line": 3, "set": {"ads": 20}}]}, f)  # 8 -> 20
        proc, rep = run_engine(self.v1, os.path.join(self.tmp, "run_swing"),
                               extra=["--overrides", ovp])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        r2 = jload(rep)
        self.assertTrue(any("swings" in w and "cap" in w for w in r2["warnings"]))

    def test_user_confirmed_mapping_memory(self):
        with tempfile.TemporaryDirectory() as td:
            f = os.path.join(td, "weird.csv")
            with open(f, "w") as fh:
                fh.write("Article No,Shop,Stok,Rate of Sale,Delivery Days\n"
                         "A1,S1,10,2,5\n")
            mp = os.path.join(td, "mappings.json")
            with open(mp, "w") as fh:
                json.dump({"Stok": "soh", "Rate of Sale": "ads",
                           "Delivery Days": "lead_time", "Article No": "sku",
                           "Shop": "store"}, fh)
            proc, rep = run_engine(f, os.path.join(td, "run"),
                                   extra=["--mappings", mp])
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            r2 = jload(rep)
            self.assertEqual(r2["kpis"]["rows"], 1)
            for tgt in ("soh", "ads", "lead_time"):
                self.assertEqual(r2["mapping"]["fields"][tgt]["confidence"],
                                 "user_confirmed")


class TestBundleColdStart(unittest.TestCase):
    """Phase 3: the shipped .skill bundle must be self-contained — engine and
    renderer run from a fresh extraction with nothing but stdlib."""

    def test_bundle_runs_standalone(self):
        import zipfile
        bundle = os.path.join(REPO, "dist", "redpill-inventory.skill")
        with tempfile.TemporaryDirectory() as td:
            with zipfile.ZipFile(bundle) as z:
                z.extractall(td)
            root = os.path.join(td, "redpill-inventory")
            eng_path = os.path.join(root, "scripts", "redpill_engine.py")
            self.assertTrue(os.path.exists(eng_path), os.listdir(td))
            rd = os.path.join(td, "run")
            proc = subprocess.run(
                [sys.executable, eng_path,
                 os.path.join(REPO, "examples", "sample_mis.csv"),
                 "--as-of", AS_OF, "--run-dir", rd],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            proc2 = subprocess.run(
                [sys.executable, os.path.join(root, "scripts", "render_cockpit.py"),
                 "--run-dir", rd], capture_output=True, text=True)
            self.assertEqual(proc2.returncode, 0, proc2.stderr)
            with open(os.path.join(rd, "cockpit.html"), encoding="utf-8") as f:
                html = f.read()
            self.assertNotIn("__REPORT_JSON__", html)

    def test_command_files_valid(self):
        cmds = os.path.join(REPO, "commands")
        expected = {"run.md", "setup.md", "template.md", "policies.md", "explain.md"}
        self.assertEqual(set(os.listdir(cmds)) & expected, expected)
        for name in expected:
            with open(os.path.join(cmds, name), encoding="utf-8") as f:
                body = f.read()
            self.assertTrue(body.startswith("---"), name)
            self.assertIn("description:", body.split("---")[1], name)


class TestModelRealism(Base):
    """Phase 4 (G18-G29): the demand module + realism gates, storyline by storyline."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        proc, rep = run_engine(cls.v2, os.path.join(cls.tmp, "run_v2r"))
        assert proc.returncode == 0, proc.stderr
        cls.r2 = jload(rep)

    def corr(self, sku, store):
        return next((c for c in self.r2["ads_corrections"]
                     if c["sku"] == sku and c["store"] == store), None)

    def test_chronic_underforecast_detected(self):          # G19/G29 core
        c = self.corr("SWT-HOD-GRY-M", "Chandigarh")
        self.assertEqual(c["deviation_pct"], 186)
        self.assertEqual(c["confidence"], "high")
        self.assertIn("raise master ADS 2 -> 6", c["recommendation"])

    def test_stockout_censoring(self):                      # G19
        c = self.corr("SWT-HOD-GRY-M", "Surat")
        self.assertEqual(c["excluded"]["censored_weeks"], 3)
        self.assertEqual(c["confidence"], "low")

    def test_suspected_promo_flagged_not_assumed(self):     # G18
        c = self.corr("TSH-CRW-WHT-L", "Surat")
        self.assertEqual(c["excluded"]["suspected_promo_weeks_ago"], [4])

    def test_promo_config_excludes_week(self):              # G18 confirmed path
        cfg = os.path.join(self.tmp, "cfg_promo.json")
        with open(cfg, "w") as f:
            json.dump({"promo_weeks_ago": [4]}, f)
        proc, rep = run_engine(self.v2, os.path.join(self.tmp, "run_promo"),
                               extra=["--config", cfg])
        r = jload(rep)
        c = next((c for c in r["ads_corrections"]
                  if c["sku"] == "TSH-CRW-WHT-L" and c["store"] == "Surat"), None)
        self.assertIsNone(c)   # spike excluded -> deviation collapses -> no correction

    def test_volatile_uses_median_and_recommends_buffer(self):   # G29
        vol = [c for c in self.r2["ads_corrections"] if "volatile" in c["recommendation"]]
        self.assertGreaterEqual(len(vol), 10)
        self.assertTrue(all(c["cv"] >= 0.6 for c in vol))  # report cv is rounded 2dp

    def test_verify_first_gate(self):                        # G23/G50
        self.assertEqual(len(self.r2["plausibility_flags"]), 1)
        f = self.r2["plausibility_flags"][0]
        self.assertEqual((f["sku"], f["store"]), ("POL-TSH-RED-M", "Surat"))
        row = next(r for r in self.r2["rows"]
                   if r["sku"] == "POL-TSH-RED-M" and r["store"] == "Surat")
        self.assertEqual(row["mitigation"], "verify count first")
        self.assertIsNone(self.corr("POL-TSH-RED-M", "Surat"))  # no ADS change on distrusted data

    def test_overcommit_flag(self):                          # G24
        self.assertEqual(self.r2["kpis"]["overcommit_count"], 1)
        row = next(r for r in self.r2["rows"]
                   if r["sku"] == "TSH-CRW-BLK-M" and r["store"] == "Surat")
        self.assertTrue(row["overcommit"])
        self.assertEqual(row["status"], "OPTIMAL")

    def test_lane_gate_with_disclosure(self):                # G22
        proc, rep = run_engine(self.v2, os.path.join(self.tmp, "run_gate"),
                               extra=["--transfer-days", "3"])
        r = jload(rep)
        self.assertFalse([t for t in r["transfers"] if t["to_store"] == "Thane"])
        self.assertTrue(any("beats the truck" in n for n in r["transfer_notes"]))

    def test_atp_disclosed(self):                            # G26/G52
        row = next(r for r in self.r2["rows"]
                   if r["sku"] == "SHR-RUN-BLK-M" and r["store"] == "Thane")
        self.assertTrue(any("sellable stock 48" in p for p in row["provenance"]))

    def test_segmentation_and_curves(self):                  # G20/G21/#5
        k = self.r2["kpis"]
        self.assertEqual(k["size_curve_breaks_count"], 10)
        self.assertTrue(0 < k["weighted_health_pct"] < 100)
        abcs = {r["abc"] for r in self.r2["rows"]}
        self.assertTrue({"A", "B", "C"} <= abcs)
        b = self.r2["size_curve_breaks"][0]
        self.assertIn("size run broken", b["note"])

    def test_budget_split(self):                             # G23
        proc, rep = run_engine(self.v1, os.path.join(self.tmp, "run_budget"),
                               extra=["--budget", "500000"])
        r = jload(rep)
        b = r["kpis"]["budget"]
        self.assertLessEqual(b["within_value"], 500000)
        self.assertGreater(b["deferred_lines"], 0)
        self.assertAlmostEqual(b["within_value"] + b["deferred_value"],
                               r["kpis"]["net_order_value"], places=2)

    def test_policies_enforced_and_disclosed(self):          # G25
        pol = os.path.join(self.tmp, "policies.json")
        with open(pol, "w") as f:
            json.dump({"protected_stores": ["Mumbai - Andheri"],
                       "no_reorder_skus": ["SCF-WIN-GRY-OS"],
                       "no_transfer_lanes": [["Kolkata", "Kochi"]]}, f)
        proc, rep = run_engine(self.v1, os.path.join(self.tmp, "run_pol"),
                               extra=["--policies", pol])
        r = jload(rep)
        self.assertFalse([t for t in r["transfers"]
                          if t["from_store"] == "Mumbai - Andheri"])
        self.assertFalse([t for t in r["transfers"]
                          if t["from_store"] == "Kolkata" and t["to_store"] == "Kochi"])
        self.assertTrue(r["policy_applications"])

    def test_apply_corrections_changes_math_with_provenance(self):   # G14 governed apply
        proc, rep = run_engine(self.v1, os.path.join(self.tmp, "run_apply"),
                               extra=["--apply-ads-corrections"])
        r = jload(rep)
        self.assertNotEqual(r["kpis"]["net_order_value"], 11640751.0)
        row = next(x for x in r["rows"]
                   if x["sku"] == "SWT-HOD-GRY-M" and x["store"] == "Chandigarh")
        self.assertTrue(any("engine correction" in p for p in row["provenance"]))

    def test_case_pack_rounding(self):                       # G22 packs
        with tempfile.TemporaryDirectory() as td:
            f = os.path.join(td, "p.csv")
            with open(f, "w") as fh:
                fh.write("sku,store,soh,qoo,ads,lead_time,unit_price,case_pack\n"
                         "A,Donor,100,0,2,5,100,12\n"
                         "A,Recv,3,0,4,5,100,12\n")
            proc, rep = run_engine(f, os.path.join(td, "run"))
            r = jload(rep)
            t = r["transfers"]
            self.assertEqual(len(t), 1)
            self.assertEqual(t[0]["qty"] % 12, 0)
            self.assertEqual(t[0]["qty"], 24)   # deficit 27 floored to whole packs
