#!/usr/bin/env python3
"""One-command candidate onboarding for a new scanner set.

This wrapper reuses the existing create_set.py generator and validate_set.py
validator. It does not deploy, merge, publish, or write to live Google Sheets.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from create_set import ScaffoldError, generate
from validate_set import validate

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_SETUP_FIELDS = (
    "name",
    "set_id",
    "series",
    "display_code",
    "official_code",
    "dataset_id",
    "expected_cards",
    "denominator",
    "spreadsheet_id",
    "script_url",
)

def load_definition(definition: Path) -> dict:
    try:
        raw = json.loads(definition.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ScaffoldError(f"Definition file not found: {definition}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise ScaffoldError(f"Definition file is unreadable or invalid JSON: {error}") from error
    if not isinstance(raw, dict):
        raise ScaffoldError("Definition root must be a JSON object.")
    return raw

def preflight_definition(definition: Path) -> dict:
    raw = load_definition(definition)
    missing = []
    for key in REQUIRED_SETUP_FIELDS:
        value = raw.get(key)
        if value is None or value == "" or (isinstance(value, str) and not value.strip()):
            missing.append(key)

    has_cards = isinstance(raw.get("cards"), list) and bool(raw.get("cards"))
    cards_file = raw.get("cards_file")
    has_cards_file = isinstance(cards_file, str) and bool(cards_file.strip())
    if not has_cards and not has_cards_file:
        missing.append("cards or cards_file")

    if missing:
        raise ScaffoldError(
            "New-set setup is incomplete. Missing: " + ", ".join(missing)
        )
    return raw

def read_set_id(definition: Path) -> str:
    raw = preflight_definition(definition)
    set_id = raw.get("set_id")
    if not isinstance(set_id, str) or not set_id.strip():
        raise ScaffoldError("Definition must contain a non-empty set_id.")
    return set_id.strip().lower()

def write_linking_report(
    set_id: str,
    ok: bool,
    recognizer_root: Path,
    frontend_root: Path | None,
    apps_script_root: Path | None,
    candidate_output_root: Path | None,
) -> Path:
    output_root = (
        Path(candidate_output_root).resolve()
        if candidate_output_root is not None
        else recognizer_root / "generated" / set_id
    )
    output_root.mkdir(parents=True, exist_ok=True)

    report = {
        "setId": set_id,
        "candidateValidation": "PASS" if ok else "FAIL",
        "productionTouched": False,
        "links": {
            "recognizerRouter": "prepared",
            "recognitionBuildRegistry": "prepared",
            "frontend": (
                "prepared-and-registered-in-provided-frontend"
                if frontend_root is not None
                else "candidate-file-prepared-only"
            ),
            "appsScript": (
                "config-file-prepared-in-provided-apps-script-root"
                if apps_script_root is not None
                else "candidate-config-prepared-only"
            ),
            "googleSheet": "not-created-or-modified",
        },
    }
    path = output_root / "onboarding_linking_report.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return path

def write_test_sheet_request(
    definition: Path,
    set_id: str,
    recognizer_root: Path,
    candidate_output_root: Path | None,
) -> Path:
    raw = load_definition(definition)
    output_root = (
        Path(candidate_output_root).resolve()
        if candidate_output_root is not None
        else recognizer_root / "generated" / set_id
    )
    output_root.mkdir(parents=True, exist_ok=True)
    package_name = set_id.replace("-", "_").replace(".", "_")
    request = {
        "setId": set_id,
        "spreadsheetId": raw["spreadsheet_id"],
        "productionSheetName": raw.get("sheet_name") or raw["name"],
        "testSheetName": "TEST_" + set_id.replace("-", "_"),
        "inventorySheetPlan": "sets/" + package_name + "/inventory_sheet_plan.json",
        "testHarness": "tools/google_sheets_test_harness_v2.gs",
        "productionWritesAllowed": False,
    }
    path = output_root / "test_sheet_request.json"
    path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
    return path

def onboard(
    definition: Path,
    recognizer_root: Path = ROOT,
    frontend_root: Path | None = None,
    apps_script_root: Path | None = None,
    candidate_output_root: Path | None = None,
    require_library: bool = False,
) -> bool:
    definition = Path(definition).resolve()
    recognizer_root = Path(recognizer_root).resolve()

    print("=" * 68)
    print("NEW SET ONBOARDING — CANDIDATE ONLY")
    print("=" * 68)
    print("[0/2] Checking setup information...")
    set_id = read_set_id(definition)
    print("Setup information: COMPLETE")
    print("Set:", set_id)
    print("Production deployment: DISABLED")
    print()

    print("[1/2] Generating candidate files and links...")
    generated = generate(
        definition,
        recognizer_root=recognizer_root,
        frontend_root=frontend_root,
        apps_script_root=apps_script_root,
        candidate_output_root=candidate_output_root,
    )

    generated_set_id = generated["set_id"]
    if generated_set_id != set_id:
        raise ScaffoldError(
            f"Generated set ID {generated_set_id!r} does not match definition {set_id!r}."
        )

    print()
    print("[2/2] Running candidate validation...")
    ok = validate(
        set_id,
        recognizer_root=recognizer_root,
        frontend_root=frontend_root,
        apps_script_root=apps_script_root,
        require_library=require_library,
        integration=(frontend_root is not None and apps_script_root is not None),
    )

    report_path = write_linking_report(
        set_id,
        ok,
        recognizer_root,
        frontend_root,
        apps_script_root,
        candidate_output_root,
    )
    test_request_path = write_test_sheet_request(
        definition,
        set_id,
        recognizer_root,
        candidate_output_root,
    )

    print()
    print("Linking report:", report_path)
    print("Test Sheet request:", test_request_path)
    print("=" * 68)
    if ok:
        print("RESULT: CANDIDATE READY FOR REVIEW")
        print("Nothing has been deployed to production.")
    else:
        print("RESULT: CANDIDATE NOT READY")
        print("Fix the reported failures before any production promotion.")
    print("=" * 68)
    return ok

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Generate, link, and validate a new Pokémon scanner set candidate in one command. "
            "This tool never deploys production."
        )
    )
    parser.add_argument("definition", type=Path, help="New-set setup JSON")
    parser.add_argument("--recognizer-root", type=Path, default=ROOT)
    parser.add_argument("--frontend-root", type=Path)
    parser.add_argument("--apps-script-root", type=Path)
    parser.add_argument("--candidate-output-root", type=Path)
    parser.add_argument(
        "--require-library",
        action="store_true",
        help="Also require the built recognition library during validation.",
    )
    return parser.parse_args(argv)

def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        ok = onboard(
            args.definition,
            recognizer_root=args.recognizer_root,
            frontend_root=args.frontend_root,
            apps_script_root=args.apps_script_root,
            candidate_output_root=args.candidate_output_root,
            require_library=args.require_library,
        )
    except (OSError, ValueError, json.JSONDecodeError, ScaffoldError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
