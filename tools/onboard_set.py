#!/usr/bin/env python3
"""Orchestrate Pokémon Scanner new-set onboarding without deploying production.

This is the glue layer over the existing scaffold, Schema v1 validator,
recognition-library builder, Inventory Sheet Plan v2 validator, and optional
integration roots. It deliberately stops at the promotion gate.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(__file__).resolve().parent


class OnboardingError(RuntimeError):
    pass


def python_name(set_id: str) -> str:
    return set_id.replace("-", "_").replace(".", "_")


def read_json(path: Path):
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_manifest(recognizer_root: Path, set_id: str):
    path = recognizer_root / "sets" / python_name(set_id) / "manifest.json"
    if not path.exists():
        raise OnboardingError("Set manifest not found: " + str(path))
    manifest = read_json(path)
    if not isinstance(manifest, dict):
        raise OnboardingError("Set manifest root must be an object: " + str(path))
    actual = manifest.get("setId")
    if actual != set_id:
        raise OnboardingError(
            "Manifest setId mismatch: expected " + repr(set_id) + ", found " + repr(actual)
        )
    return manifest


def set_id_from_definition(definition: Path) -> str:
    data = read_json(definition)
    if not isinstance(data, dict):
        raise OnboardingError("Definition root must be an object.")
    value = data.get("set_id")
    if not isinstance(value, str) or not value.strip():
        raise OnboardingError("Definition set_id is required.")
    return value.strip().lower()


def build_one_library(recognizer_root: Path, set_id: str):
    registry_path = recognizer_root / "schema_v1_builds.json"
    data = read_json(registry_path)
    entries = data.get("sets") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise OnboardingError("schema_v1_builds.json must contain a sets array.")

    matches = [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("setId") == set_id
    ]
    if len(matches) != 1:
        raise OnboardingError(
            "Build registry must contain "
            + repr(set_id)
            + " exactly once; found "
            + str(len(matches))
            + "."
        )

    entry = matches[0]
    package = entry.get("package")
    output = entry.get("output")
    expected = entry.get("expectedRecords")
    if not isinstance(package, str) or not package.strip():
        raise OnboardingError(set_id + " build entry is missing package.")
    if not isinstance(output, str) or not output.strip():
        raise OnboardingError(set_id + " build entry is missing output.")

    sys.path.insert(0, str(recognizer_root))
    try:
        from schema_v1_library_builder import build_library

        build_library(
            set_id=set_id,
            package_directory=recognizer_root / package,
            expected_records=expected,
            output_path=recognizer_root / output,
        )
    finally:
        if sys.path and sys.path[0] == str(recognizer_root):
            sys.path.pop(0)


def validate_candidate(
    recognizer_root: Path,
    set_id: str,
    frontend_root: Path | None,
    apps_script_root: Path | None,
    require_library: bool,
):
    sys.path.insert(0, str(TOOLS))
    try:
        from validate_set import validate

        return validate(
            set_id=set_id,
            recognizer_root=recognizer_root,
            frontend_root=frontend_root,
            apps_script_root=apps_script_root,
            require_library=require_library,
            integration=frontend_root is not None or apps_script_root is not None,
        )
    finally:
        if sys.path and sys.path[0] == str(TOOLS):
            sys.path.pop(0)


def validate_sheet_snapshot(recognizer_root: Path, set_id: str, snapshot: Path):
    plan_path = (
        recognizer_root
        / "sets"
        / python_name(set_id)
        / "inventory_sheet_plan.json"
    )
    if not plan_path.exists():
        raise OnboardingError("Inventory Sheet Plan v2 not found: " + str(plan_path))
    if not snapshot.exists():
        raise OnboardingError(
            "Google Sheet read-back snapshot not found: " + str(snapshot)
        )

    sys.path.insert(0, str(TOOLS))
    try:
        from validate_inventory_sheet_v2 import validate_plan, validate_snapshot

        plan = read_json(plan_path)
        actual = read_json(snapshot)
        errors = validate_plan(plan)
        errors.extend(validate_snapshot(plan, actual))
    finally:
        if sys.path and sys.path[0] == str(TOOLS):
            sys.path.pop(0)

    if errors:
        print("Google Sheet read-back: FAIL")
        for error in errors:
            print("FAIL ", error)
        return False

    print("Google Sheet read-back: PASS")
    return True


def scaffold(
    definition: Path,
    recognizer_root: Path,
    frontend_root: Path | None,
    apps_script_root: Path | None,
    candidate_output_root: Path | None,
):
    sys.path.insert(0, str(TOOLS))
    try:
        from create_set import generate

        return generate(
            definition_path=definition,
            recognizer_root=recognizer_root,
            frontend_root=frontend_root,
            apps_script_root=apps_script_root,
            candidate_output_root=candidate_output_root,
        )
    finally:
        if sys.path and sys.path[0] == str(TOOLS):
            sys.path.pop(0)


def print_gate(
    set_id: str,
    manifest: dict,
    library_required: bool,
    sheet_checked: bool,
):
    expected = (manifest.get("catalogue") or {}).get("expectedRecords")
    display = manifest.get("displayName") or set_id

    print()
    print("=" * 64)
    print("POKÉMON SCANNER — NEW SET ONBOARDING v1")
    print("=" * 64)
    print("Set:", display, "[" + set_id + "]")
    print("Cards:", expected)
    print("Schema/package validation: PASS")
    print(
        "Recognition library:",
        "PASS / required" if library_required else "NOT BUILT / not requested",
    )
    print(
        "Google Sheet read-back:",
        "PASS" if sheet_checked else "NOT CHECKED / snapshot not supplied",
    )
    print()
    print("PROMOTION GATE: PASS")
    print("PRODUCTION STATUS: NOT DEPLOYED")
    print(
        "No Render, Apps Script, production Sheet, or frontend production "
        "deployment was performed."
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Run the Pokémon Scanner new-set onboarding pipeline and stop at "
            "the production promotion gate."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--definition",
        type=Path,
        help="Normalized JSON definition for a new set candidate.",
    )
    source.add_argument(
        "--set",
        dest="set_id",
        help="Existing Schema v1 set ID for regression validation.",
    )
    parser.add_argument("--recognizer-root", type=Path, default=ROOT)
    parser.add_argument("--frontend-root", type=Path)
    parser.add_argument("--apps-script-root", type=Path)
    parser.add_argument("--candidate-output-root", type=Path)
    parser.add_argument(
        "--build-library",
        action="store_true",
        help="Build only this set's recognition library before validation.",
    )
    parser.add_argument(
        "--sheet-snapshot",
        type=Path,
        help=(
            "Optional Google Sheet read-back snapshot JSON to compare with "
            "Inventory Sheet Plan v2."
        ),
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    recognizer_root = args.recognizer_root.resolve()
    frontend_root = args.frontend_root.resolve() if args.frontend_root else None
    apps_script_root = (
        args.apps_script_root.resolve() if args.apps_script_root else None
    )
    candidate_output_root = (
        args.candidate_output_root.resolve()
        if args.candidate_output_root
        else None
    )

    if (frontend_root is None) != (apps_script_root is None):
        print(
            "FAIL: --frontend-root and --apps-script-root must be supplied "
            "together for integration validation.",
            file=sys.stderr,
        )
        return 2

    try:
        if args.definition:
            definition = args.definition.resolve()
            set_id = set_id_from_definition(definition)
            print("Stage 1/4 — Scaffold candidate")
            scaffold(
                definition,
                recognizer_root,
                frontend_root,
                apps_script_root,
                candidate_output_root,
            )
        else:
            set_id = str(args.set_id).strip().lower()
            print(
                "Stage 1/4 — Existing set regression mode "
                "(no scaffold changes)"
            )

        manifest = load_manifest(recognizer_root, set_id)

        if args.build_library:
            print("Stage 2/4 — Build recognition library for", set_id)
            build_one_library(recognizer_root, set_id)
        else:
            print("Stage 2/4 — Recognition-library build skipped")

        print("Stage 3/4 — Schema / inventory / integration validation")
        if not validate_candidate(
            recognizer_root,
            set_id,
            frontend_root,
            apps_script_root,
            require_library=args.build_library,
        ):
            print("\nPROMOTION GATE: FAIL")
            print("PRODUCTION STATUS: NOT DEPLOYED")
            return 1

        sheet_checked = False
        print("Stage 4/4 — Inventory Sheet read-back")
        if args.sheet_snapshot:
            if not validate_sheet_snapshot(
                recognizer_root,
                set_id,
                args.sheet_snapshot.resolve(),
            ):
                print("\nPROMOTION GATE: FAIL")
                print("PRODUCTION STATUS: NOT DEPLOYED")
                return 1
            sheet_checked = True
        else:
            print(
                "Google Sheet read-back skipped; provide --sheet-snapshot "
                "when staging has been rendered."
            )

        print_gate(
            set_id,
            manifest,
            args.build_library,
            sheet_checked,
        )
        return 0

    except Exception as error:
        print("FAIL:", error, file=sys.stderr)
        print("PROMOTION GATE: FAIL")
        print("PRODUCTION STATUS: NOT DEPLOYED")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
