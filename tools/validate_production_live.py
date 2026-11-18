#!/usr/bin/env python3
"""Stage 2C integrated read-only production validator."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

import google_sheets_readonly as sheets
import validate_production as offline
from google_sheets_live_reader import LiveGoogleSheetsReader

PASS = "PASS"
WARNING = "WARNING"
FAIL = "FAIL"
NOT_VERIFIED = "NOT VERIFIED"


def set_live_label(findings: list[sheets.SheetFinding]) -> str:
    has_fail = any(f.status == FAIL for f in findings)
    has_warning = any(f.status == WARNING for f in findings)
    has_unverified = any(f.status == NOT_VERIFIED for f in findings)
    if has_fail:
        return FAIL
    if has_warning and has_unverified:
        return "PASS WITH WARNINGS / UNVERIFIED ITEMS"
    if has_unverified:
        return "PASS WITH UNVERIFIED ITEMS"
    if has_warning:
        return "PASS WITH WARNINGS"
    return PASS


def combined_label(
    offline_findings: list[offline.Finding],
    live_by_set: dict[str, list[sheets.SheetFinding]],
) -> str:
    if offline.offline_status(offline_findings) == FAIL:
        return FAIL
    if any(any(f.status == FAIL for f in fs) for fs in live_by_set.values()):
        return FAIL
    has_warning = (
        offline.offline_status(offline_findings) == WARNING
        or any(any(f.status == WARNING for f in fs) for fs in live_by_set.values())
    )
    has_unverified = any(
        any(f.status == NOT_VERIFIED for f in fs) for fs in live_by_set.values()
    )
    if has_warning and has_unverified:
        return "PASS WITH WARNINGS / UNVERIFIED ITEMS"
    if has_unverified:
        return "PASS WITH UNVERIFIED ITEMS"
    if has_warning:
        return "PASS WITH WARNINGS"
    return PASS


def build_json_report(
    baseline: dict[str, Any],
    offline_findings: list[offline.Finding],
    live_by_set: dict[str, list[sheets.SheetFinding]],
) -> dict[str, Any]:
    return {
        "baseline": baseline.get("baselineName"),
        "overallStatus": combined_label(offline_findings, live_by_set),
        "offlineStatus": offline.overall_offline_label(offline_findings),
        "sets": {
            set_id: {
                "code": baseline["sets"][set_id]["setCode"],
                "offlineStatus": offline.offline_status(offline_findings, set_id),
                "liveStatus": set_live_label(live_by_set[set_id]),
                "liveFindings": [f.report_dict() for f in live_by_set[set_id]],
            }
            for set_id in baseline["productionSetOrder"]
        },
    }


def render(
    baseline: dict[str, Any],
    offline_findings: list[offline.Finding],
    live_by_set: dict[str, list[sheets.SheetFinding]],
) -> None:
    print("Pokémon Inventory Scanner — Stage 2C Production Validator")
    print("READ-ONLY / DIAGNOSTIC ONLY")
    print("Baseline:", baseline.get("baselineName"))
    print()
    for set_id in baseline["productionSetOrder"]:
        code = baseline["sets"][set_id]["setCode"]
        label = set_live_label(live_by_set[set_id])
        print(f"{code} — {label}")
        for finding in live_by_set[set_id]:
            if finding.status in (WARNING, FAIL, NOT_VERIFIED):
                print(f"  {finding.status}: {finding.check}")
                print(f"    {finding.reason}")
    print()
    print("OFFLINE RESULT:", offline.overall_offline_label(offline_findings))
    print("OVERALL PRODUCTION RESULT:", combined_label(offline_findings, live_by_set))


def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--recognizer-root", type=Path, default=ROOT)
    p.add_argument("--frontend-root", type=Path)
    p.add_argument("--baseline", type=Path, default=HERE / "production_baseline_v1.json")
    p.add_argument("--json", action="store_true", help="Print machine-readable JSON after the report.")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        baseline, offline_findings = offline.validate(
            args.recognizer_root.resolve(),
            args.frontend_root.resolve() if args.frontend_root else None,
            args.baseline.resolve(),
        )
        reader = LiveGoogleSheetsReader.from_environment()
        live_by_set = {
            set_id: sheets.validate_with_reader(
                reader, args.recognizer_root.resolve(), baseline, set_id
            )
            for set_id in baseline["productionSetOrder"]
        }
    except sheets.AuthenticationUnavailable:
        print("Stage 2C cannot run: read-only Google Sheets authentication unavailable.")
        return 2
    except Exception as error:
        print("Stage 2C validator could not complete:", sheets.sanitize_for_report(str(error)))
        return 2

    render(baseline, offline_findings, live_by_set)
    if args.json:
        print(json.dumps(build_json_report(baseline, offline_findings, live_by_set), indent=2))

    return 1 if combined_label(offline_findings, live_by_set) == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
