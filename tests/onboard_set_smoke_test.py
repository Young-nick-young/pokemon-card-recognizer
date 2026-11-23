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
        path.write_text(json.dumps({"set_id": set_id}), encoding="utf-8")
        return path

    def test_success_runs_generate_then_validate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            definition = self.make_definition(root)
            with patch.object(onboard_set, "generate", return_value={"set_id": "example-set"}) as generate, \
                 patch.object(onboard_set, "validate", return_value=True) as validate:
                ok = onboard_set.onboard(definition, recognizer_root=root)

            self.assertTrue(ok)
            generate.assert_called_once()
            validate.assert_called_once()
            self.assertEqual(validate.call_args.args[0], "example-set")

    def test_validation_failure_blocks_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            definition = self.make_definition(root)
            with patch.object(onboard_set, "generate", return_value={"set_id": "example-set"}), \
                 patch.object(onboard_set, "validate", return_value=False):
                ok = onboard_set.onboard(definition, recognizer_root=root)

            self.assertFalse(ok)

    def test_generated_set_id_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            definition = self.make_definition(root)
            with patch.object(onboard_set, "generate", return_value={"set_id": "wrong-set"}):
                with self.assertRaises(onboard_set.ScaffoldError):
                    onboard_set.onboard(definition, recognizer_root=root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
