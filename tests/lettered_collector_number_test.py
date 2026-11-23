#!/usr/bin/env python3
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT))

from create_set import normalize_definition, build_schema_files, python_name, js_constant
from schema_v1_inventory_sheet_plan import build_inventory_sheet_plan

class LetteredCollectorNumberTest(unittest.TestCase):
    def test_numbered_set_names_generate_valid_code_identifiers(self):
        self.assertEqual(python_name("30th-celebration"), "set_30th_celebration")
        self.assertEqual(js_constant("30th Celebration"), "SET_30TH_CELEBRATION")

    def test_lettered_collector_number_keeps_sequential_internal_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            definition = root / "definition.json"
            raw = {
                "name": "30th Celebration",
                "set_id": "30th-celebration",
                "series": "Mega Evolution",
                "display_code": "30C",
                "official_code": "30C",
                "dataset_id": "me55",
                "expected_cards": 2,
                "denominator": 128,
                "spreadsheet_id": "sheet-id",
                "script_url": "https://example.com/script",
                "cards": [
                    {
                        "number": 1,
                        "name": "Exeggcute",
                        "rarity": "Common",
                        "reference_image": "https://example.com/1.jpg",
                        "inventory_variants": ["holo"],
                    },
                    {
                        "number": "R",
                        "collector_number": "R",
                        "external_id": "me55-R",
                        "name": "Mew",
                        "rarity": "Common",
                        "reference_image": "https://example.com/R.jpg",
                        "inventory_variants": ["holo"],
                    },
                ],
            }
            definition.write_text(json.dumps(raw), encoding="utf-8")

            config = normalize_definition(raw, definition)
            manifest, catalogue, inventory = build_schema_files(config)

            self.assertEqual(catalogue["cards"][0]["cardId"], "30c-001")
            self.assertEqual(catalogue["cards"][0]["number"]["display"], "001/128")
            self.assertEqual(catalogue["cards"][0]["number"]["sortKey"], 1)

            self.assertEqual(catalogue["cards"][1]["cardId"], "30c-002")
            self.assertEqual(catalogue["cards"][1]["number"]["display"], "R/128")
            self.assertEqual(catalogue["cards"][1]["number"]["sortKey"], 2)
            self.assertEqual(
                catalogue["cards"][1]["externalIds"]["pokemonTcgData"],
                "me55-R",
            )
            self.assertEqual(
                catalogue["cards"][1]["externalIds"]["legacyInventoryCardId"],
                "30C-002",
            )

            package = root / "sets" / "thirtieth"
            package.mkdir(parents=True)
            (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (package / "cards.json").write_text(json.dumps(catalogue), encoding="utf-8")
            (package / "inventory_metadata.json").write_text(json.dumps(inventory), encoding="utf-8")

            plan = build_inventory_sheet_plan(package)
            self.assertEqual(plan["rows"][0]["values"]["collectorNumber"], 1)
            self.assertEqual(plan["rows"][1]["values"]["collectorNumber"], "R")
            self.assertEqual(plan["rows"][1]["collectorNumber"], "R")

if __name__ == "__main__":
    unittest.main(verbosity=2)
