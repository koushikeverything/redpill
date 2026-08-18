#!/usr/bin/env python3
"""S-track adapter tests (S0, gaps G39/G40) — stdlib only.

The adapter's job is normalization, never business math: these tests pin the
Shopify Bulk JSONL -> MIS CSV contract byte-for-byte, prove the skip/pass-
through policies, and run the REAL engine on the adapter's output to show the
existing trust layer owns every bad row. The engine's own golden suite is
untouched by the S-track on purpose.
"""
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "skills", "redpill-inventory", "scripts")
ADAPTER = os.path.join(SCRIPTS, "shopify_snapshot.py")
ENGINE = os.path.join(SCRIPTS, "redpill_engine.py")
GEN = os.path.join(HERE, "fixtures", "gen_shopify_fixture.py")
PULLED_AT = "2026-08-14T09:00:00+05:30"
AS_OF = "2026-08-14"

# sha256 of shopify_mis.csv from fixture v1 + leadtimes {"Weave & Co": 9}.
# ANY normalization change breaks this on purpose — update with a reason,
# same discipline as the engine's report golden.
CSV_SHA256 = "b9eab7a38d12cc78c2c69e6e35e4f5487830fa6d07491c531976349be22c04c8"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def jload(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class Base(unittest.TestCase):
    tmp = None

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="redpill_shopify_")
        subprocess.run([sys.executable, GEN, cls.tmp], check=True, capture_output=True)
        cls.jsonl = os.path.join(cls.tmp, "shopify_bulk_v1.jsonl")
        cls.leadtimes = os.path.join(cls.tmp, "leadtimes.json")
        with open(cls.leadtimes, "w") as f:
            json.dump({"Weave & Co": 9}, f)
        cls.pull = os.path.join(cls.tmp, "pull")
        proc = subprocess.run(
            [sys.executable, ADAPTER, "--from-jsonl", cls.jsonl,
             "--out-dir", cls.pull, "--pulled-at", PULLED_AT,
             "--leadtimes", cls.leadtimes],
            capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr + proc.stdout
        cls.csv_path = os.path.join(cls.pull, "shopify_mis.csv")
        cls.manifest = jload(os.path.join(cls.pull, "pull-manifest.json"))
        with open(cls.csv_path, newline="", encoding="utf-8") as f:
            cls.rows = list(csv.DictReader(f))


class TestSnapshotContract(Base):
    """G39 — deterministic normalization + manifest."""

    def test_normalized_csv_golden(self):
        self.assertEqual(sha256_file(self.csv_path), CSV_SHA256)

    def test_rerun_is_byte_identical(self):
        out2 = os.path.join(self.tmp, "pull2")
        subprocess.run([sys.executable, ADAPTER, "--from-jsonl", self.jsonl,
                        "--out-dir", out2, "--pulled-at", PULLED_AT,
                        "--leadtimes", self.leadtimes], check=True, capture_output=True)
        self.assertEqual(sha256_file(os.path.join(out2, "shopify_mis.csv")),
                         sha256_file(self.csv_path))
        m2 = jload(os.path.join(out2, "pull-manifest.json"))
        self.assertEqual(m2, self.manifest)

    def test_manifest_records_the_pull(self):
        m = self.manifest
        self.assertEqual(m["mode"], "jsonl-replay")
        self.assertEqual(m["pulled_at"], PULLED_AT)
        self.assertEqual(len(m["query_sha256"]), 64)      # what was asked, hashed
        self.assertEqual(m["sha256"]["input_jsonl"], sha256_file(self.jsonl))
        self.assertEqual(m["sha256"]["shopify_mis.csv"], sha256_file(self.csv_path))
        self.assertEqual(m["counts"]["rows"], 24)

    def test_pulled_at_required_in_replay(self):
        proc = subprocess.run([sys.executable, ADAPTER, "--from-jsonl", self.jsonl,
                               "--out-dir", os.path.join(self.tmp, "nope")],
                              capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("reproducible", proc.stderr + proc.stdout)


class TestMappingAndPolicy(Base):
    """G40 — provenance, skip-with-counts, pass-through-never-guess."""

    def test_provenance_covers_every_column(self):
        prov = jload(os.path.join(self.pull, "adapter-provenance.json"))
        with open(self.csv_path, encoding="utf-8") as f:
            header = f.readline().strip().split(",")
        for col in header:
            self.assertIn(col, prov, col)

    def test_skips_are_counted_never_silent(self):
        c = self.manifest["counts"]
        self.assertEqual(c["skipped_archived_variants"], 1)    # Old Tee
        self.assertEqual(c["skipped_untracked_variants"], 1)   # Cap Classic
        skus = {r["sku"] for r in self.rows}
        self.assertNotIn("OLD-TEE-M", skus)
        self.assertNotIn("CAP-CLS-OS", skus)

    def test_bad_data_passes_through_for_engine_quarantine(self):
        blanks = [r for r in self.rows if r["sku"] == ""]
        self.assertEqual(len(blanks), 3)                       # blank-SKU oxford
        neg = [r for r in self.rows if r["soh"] == "-6"]
        self.assertEqual(len(neg), 1)                          # chino Pune
        jog = [r for r in self.rows if r["sku"].startswith("JOG-") and r["lead_time"] == ""]
        self.assertEqual(len(jog), 6)                          # no lead time anywhere

    def test_reserved_merges_committed_and_damage_kept(self):
        r = next(x for x in self.rows
                 if x["sku"] == "TEE-CRW-BLK-M" and x["store"] == "Mumbai Flagship")
        self.assertEqual(r["reserved"], "12")                  # committed 8 + reserved 4
        self.assertEqual(r["damaged"], "2")

    def test_vendor_default_lead_time_applied(self):
        r = next(x for x in self.rows
                 if x["sku"] == "OXF-SHT-WHT-M" and x["store"] == "Mumbai Flagship")
        self.assertEqual(r["lead_time"], "9")                  # from leadtimes.json

    def test_receipt_date_only_with_inbound(self):
        delhi = next(x for x in self.rows
                     if x["sku"] == "TEE-CRW-BLK-M" and x["store"] == "Delhi CP")
        self.assertEqual(delhi["expected_receipt_date"], "2026-08-24")
        mum = next(x for x in self.rows
                   if x["sku"] == "TEE-CRW-BLK-M" and x["store"] == "Mumbai Flagship")
        self.assertEqual(mum["expected_receipt_date"], "")     # no inbound, no date


class TestEngineOwnsTheRest(Base):
    """Integration: the UNCHANGED engine runs the adapter's output and its
    trust layer owns every analog the fixture planted."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rundir = os.path.join(cls.tmp, "run")
        proc = subprocess.run(
            [sys.executable, ENGINE, cls.csv_path, "--as-of", AS_OF,
             "--run-dir", cls.rundir],
            capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr + proc.stdout
        cls.report = jload(os.path.join(cls.rundir, "report.json"))

    def test_processed_and_quarantined(self):
        k = self.report["kpis"]
        self.assertEqual(k["rows"], 14)
        self.assertEqual(k["quarantined"], 10)
        self.assertEqual(self.report["run"]["verdict"], "degraded")  # >20% — honest

    def test_all_six_statuses_appear(self):
        for s, n in self.report["kpis"]["status_counts"].items():
            self.assertGreater(n, 0, s)

    def test_transfers_match_storyline(self):
        got = {(t["sku"], t["from_store"], t["to_store"]): t["qty"]
               for t in self.report["transfers"]}
        self.assertEqual(got, {
            ("TEE-CRW-BLK-M", "Mumbai Flagship", "Pune Kurla"): 18,
            ("TEE-CRW-BLK-L", "Mumbai Flagship", "Pune Kurla"): 8,
            ("CHN-KHK-32", "Mumbai Flagship", "Delhi CP"): 9,
        })

    def test_atp_governs_the_donor(self):
        donor = next(r for r in self.report["rows"]
                     if r["sku"] == "TEE-CRW-BLK-M" and r["store"] == "Mumbai Flagship")
        self.assertTrue(any("sellable stock 106" in p for p in donor["provenance"]))

    def test_incoming_lateness_and_timing_gap(self):
        inc = next(r for r in self.report["rows"] if r["status"] == "INCOMING")
        self.assertEqual(inc["store"], "Delhi CP")
        self.assertIn("later than a fresh order", inc["incoming_risk"])
        self.assertEqual(inc["stockout_before_inbound_days"], 10.0)   # G36 on live-ish data

    def test_quarantine_covers_the_three_analogs(self):
        reasons = " | ".join(g["reason"] for g in self.report["quarantine"])
        self.assertIn("sku is blank", reasons)
        self.assertIn("lead_time missing", reasons)
        self.assertIn("soh negative", reasons)

    def test_size_curve_data_flows_through(self):
        row = next(r for r in self.report["rows"] if r["sku"] == "TEE-CRW-BLK-M")
        pt = {k.lower(): v for k, v in row["passthrough"].items()}
        self.assertEqual(pt.get("size"), "M")
        self.assertEqual(pt.get("colour"), "Black")


if __name__ == "__main__":
    unittest.main()
