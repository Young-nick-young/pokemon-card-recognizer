#!/usr/bin/env python3
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tools" / "google_sheets_test_harness_v2.gs"

class GoogleSheetsTestHarnessSafetyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = HARNESS.read_text(encoding="utf-8")

    def test_requires_test_prefix(self):
        self.assertIn("testSheetName.indexOf('TEST_') !== 0", self.text)
        self.assertIn("Snapshot is restricted to TEST_-prefixed sheets.", self.text)

    def test_refuses_production_name(self):
        self.assertIn("testSheetName === plan.sheetName", self.text)
        self.assertIn("allowProductionName: false", self.text)

    def test_reports_production_untouched(self):
        self.assertIn("productionTouched: false", self.text)

    def test_uses_existing_safe_renderer(self):
        self.assertIn("renderInventorySheetPlanV2(", self.text)

    def test_reads_back_and_compares(self):
        self.assertIn("snapshotInventorySheetPlanV2_", self.text)
        self.assertIn("compareInventorySheetPlanV2Snapshot_", self.text)
        self.assertRegex(self.text, r"status:\s*errors\.length === 0 \? 'PASS' : 'FAIL'")

    def test_no_delete_sheet_call(self):
        self.assertNotIn(".deleteSheet(", self.text)

if __name__ == "__main__":
    unittest.main(verbosity=2)
