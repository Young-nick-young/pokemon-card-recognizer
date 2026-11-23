#!/usr/bin/env python3
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import onboard_set

class OnboardSetSmokeTest(unittest.TestCase):
    def make_definition(self, root: Path, set_id: str = "example-set") -> Path:
        path = root / "definition.json"
        path.write_text(json.dumps({
            "name": "Example Set",
            "set_id": set_id,
            "series": "Example Series",
            "display_code": "EXM",
            "official_code": "EX01",
            "dataset_id": "ex1",
            "expected_cards": 1,
            "denominator": 1,
            "spreadsheet_id": "sheet-id",
            "script_url": "https://example.com/script",
            "cards": [{"number": 1}]
        }), encoding="utf-8")
        return path

    def test_candidate_without_full_links_is_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            definition = self.make_definition(root)
            out = root / "candidate"
            with patch.object(onboard_set, "generate", return_value={"set_id": "example-set"}) as generate, \
                 patch.object(onboard_set, "validate", return_value=True) as validate:
                ok = onboard_set.onboard(
                    definition,
                    recognizer_root=root,
                    candidate_output_root=out,
                )

            self.assertFalse(ok)
            generate.assert_called_once()
            validate.assert_called_once()
            self.assertEqual(validate.call_args.args[0], "example-set")

            report = json.loads(
                (out / "onboarding_linking_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["candidateValidation"], "PASS")
            self.assertFalse(report["productionTouched"])
            self.assertEqual(report["links"]["recognizerRouter"], "prepared")
            self.assertEqual(report["links"]["frontend"], "candidate-file-prepared-only")
            self.assertEqual(report["links"]["googleSheet"], "not-created-or-modified")

            request = json.loads(
                (out / "test_sheet_request.json").read_text(encoding="utf-8")
            )
            self.assertEqual(request["testSheetName"], "TEST_example_set")
            self.assertFalse(request["productionWritesAllowed"])
            self.assertEqual(
                request["inventorySheetPlan"],
                "sets/example_set/inventory_sheet_plan.json"
            )

            readiness = json.loads(
                (out / "onboarding_readiness_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(readiness["status"], "NOT READY")
            self.assertIn("frontend link not verified", readiness["blockingReasons"])
            self.assertIn("test Sheet has not passed", readiness["blockingReasons"])

    def test_validation_failure_blocks_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            definition = self.make_definition(root)
            with patch.object(onboard_set, "generate", return_value={"set_id": "example-set"}), \
                 patch.object(onboard_set, "validate", return_value=False):
                ok = onboard_set.onboard(definition, recognizer_root=root)

            self.assertFalse(ok)

    def test_full_verified_candidate_is_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frontend = root / "frontend"
            apps = root / "apps"
            frontend.mkdir()
            apps.mkdir()
            definition = self.make_definition(root)
            out = root / "candidate"
            result_path = root / "test-sheet-result.json"
            result_path.write_text(
                json.dumps({"status": "PASS", "productionTouched": False}),
                encoding="utf-8",
            )

            with patch.object(onboard_set, "generate", return_value={"set_id": "example-set"}), \
                 patch.object(onboard_set, "validate", return_value=True):
                ok = onboard_set.onboard(
                    definition,
                    recognizer_root=root,
                    frontend_root=frontend,
                    apps_script_root=apps,
                    candidate_output_root=out,
                    test_sheet_result_path=result_path,
                )

            self.assertTrue(ok)
            readiness = json.loads(
                (out / "onboarding_readiness_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(readiness["status"], "READY")
            self.assertEqual(readiness["blockingReasons"], [])

    def test_failed_test_sheet_blocks_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frontend = root / "frontend"
            apps = root / "apps"
            frontend.mkdir()
            apps.mkdir()
            definition = self.make_definition(root)
            out = root / "candidate"
            result_path = root / "test-sheet-result.json"
            result_path.write_text(
                json.dumps({"status": "FAIL", "productionTouched": False}),
                encoding="utf-8",
            )

            with patch.object(onboard_set, "generate", return_value={"set_id": "example-set"}), \
                 patch.object(onboard_set, "validate", return_value=True):
                ok = onboard_set.onboard(
                    definition,
                    recognizer_root=root,
                    frontend_root=frontend,
                    apps_script_root=apps,
                    candidate_output_root=out,
                    test_sheet_result_path=result_path,
                )

            self.assertFalse(ok)
            readiness = json.loads(
                (out / "onboarding_readiness_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(readiness["status"], "NOT READY")
            self.assertIn("test Sheet has not passed", readiness["blockingReasons"])

    def test_generated_set_id_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            definition = self.make_definition(root)
            with patch.object(onboard_set, "generate", return_value={"set_id": "wrong-set"}):
                with self.assertRaises(onboard_set.ScaffoldError):
                    onboard_set.onboard(definition, recognizer_root=root)

    def test_missing_setup_information_is_rejected_before_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            definition = root / "definition.json"
            definition.write_text(json.dumps({"set_id": "example-set"}), encoding="utf-8")
            with patch.object(onboard_set, "generate") as generate:
                with self.assertRaises(onboard_set.ScaffoldError) as caught:
                    onboard_set.onboard(definition, recognizer_root=root)

            self.assertIn("Missing:", str(caught.exception))
            self.assertIn("name", str(caught.exception))
            generate.assert_not_called()

if __name__ == "__main__":
    unittest.main(verbosity=2)
