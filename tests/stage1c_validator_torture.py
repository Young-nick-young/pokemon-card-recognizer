#!/usr/bin/env python3
"""Stage 1C torture tests for tools/validate_production.py.

All mutations occur only inside TemporaryDirectory copies.
No Google/Render/Apps Script/live HTTP access is used.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_SOURCE = ROOT / "frontend-source"
VALIDATOR_PATH = ROOT / "tools" / "validate_production.py"

spec = importlib.util.spec_from_file_location("validate_production_stage1c", VALIDATOR_PATH)
vp = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = vp
spec.loader.exec_module(vp)


def copy_fixture() -> tuple[tempfile.TemporaryDirectory, Path, Path]:
    holder = tempfile.TemporaryDirectory(prefix="stage1c-")
    base = Path(holder.name)
    recognizer = base / "recognizer"
    frontend = base / "frontend"
    shutil.copytree(
        ROOT,
        recognizer,
        ignore=shutil.ignore_patterns(".git", "frontend-source", "__pycache__", "*.pyc"),
    )
    shutil.copytree(
        FRONTEND_SOURCE,
        frontend,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
    )
    return holder, recognizer, frontend


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def tree_digest(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = str(path.relative_to(root))
        result[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def run_cli(recognizer: Path, frontend: Path | None) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(recognizer / "tools" / "validate_production.py"),
        "--recognizer-root",
        str(recognizer),
        "--baseline",
        str(recognizer / "tools" / "production_baseline_v1.json"),
    ]
    if frontend is not None:
        cmd += ["--frontend-root", str(frontend)]
    return subprocess.run(cmd, text=True, capture_output=True, check=False)


def findings_for(recognizer: Path, frontend: Path | None):
    baseline, findings = vp.validate(
        recognizer,
        frontend,
        recognizer / "tools" / "production_baseline_v1.json",
    )
    return baseline, findings


def has_finding(findings, *, status=None, check_contains=None, set_id=None):
    for f in findings:
        if status is not None and f.status != status:
            continue
        if check_contains is not None and check_contains not in f.check:
            continue
        if set_id is not None and f.set_id != set_id:
            continue
        return True
    return False


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise AssertionError(f"mutation anchor not found in {path}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def mutate_builder_missing(recognizer: Path, frontend: Path):
    path = recognizer / "schema_v1_builds.json"
    data = load(path)
    data["sets"] = [x for x in data["sets"] if x["setId"] != "pitch-black"]
    dump(path, data)


def mutate_builder_duplicate(recognizer: Path, frontend: Path):
    path = recognizer / "schema_v1_builds.json"
    data = load(path)
    entry = next(x for x in data["sets"] if x["setId"] == "perfect-order")
    data["sets"].append(dict(entry))
    dump(path, data)


def mutate_builder_extra(recognizer: Path, frontend: Path):
    path = recognizer / "schema_v1_builds.json"
    data = load(path)
    data["sets"].append({
        "setId": "fake-set",
        "package": "sets/fake_set",
        "expectedRecords": 1,
        "output": "sets/fake_set/card_library.pkl",
    })
    dump(path, data)


def mutate_router_missing(recognizer: Path, frontend: Path):
    replace_once(
        recognizer / "main.py",
        '    "chaos-rising": chaos_rising,\n',
        "",
    )


def mutate_router_extra(recognizer: Path, frontend: Path):
    replace_once(
        recognizer / "main.py",
        '    "pitch-black": pitch_black\n}',
        '    "pitch-black": pitch_black,\n    "fake-set": fake_set\n}',
    )


def mutate_frontend_extra(recognizer: Path, frontend: Path):
    extra = frontend / "js" / "sets" / "fake-set.js"
    extra.write_text(
        'const X={id:"fake-set",name:"Fake",setCode:"FAK",series:"Test"};\nSetRegistry.register(X);\n',
        encoding="utf-8",
    )
    with (frontend / "index.html").open("a", encoding="utf-8") as h:
        h.write('\n<script src="./js/sets/fake-set.js"></script>\n')


def mutate_frontend_duplicate_include(recognizer: Path, frontend: Path):
    with (frontend / "index.html").open("a", encoding="utf-8") as h:
        h.write('\n<script src="./js/sets/pitch-black.js"></script>\n')


def mutate_canonical_duplicate(recognizer: Path, frontend: Path):
    path = recognizer / "sets" / "pitch_black" / "cards.json"
    data = load(path)
    data["cards"][49]["cardId"] = data["cards"][48]["cardId"]
    dump(path, data)


def mutate_card_count(recognizer: Path, frontend: Path):
    path = recognizer / "sets" / "pitch_black" / "cards.json"
    data = load(path)
    data["cards"].pop()
    dump(path, data)


def mutate_first_identity(recognizer: Path, frontend: Path):
    path = recognizer / "sets" / "perfect_order" / "cards.json"
    data = load(path)
    data["cards"][0]["name"] = "Wrong Name"
    dump(path, data)


def mutate_frontend_metadata(recognizer: Path, frontend: Path):
    replace_once(frontend / "js" / "sets" / "chaos-rising.js", 'setCode: "CRI"', 'setCode: "BAD"')


def mutate_apps_script_identifier(recognizer: Path, frontend: Path):
    path = frontend / "js" / "sets" / "perfect-order.js"
    text = path.read_text(encoding="utf-8")
    marker = "https://script.google.com/a/macros/ikns.edu.bh/s/"
    idx = text.index(marker)
    end = text.index('/exec"', idx)
    bad = text[:idx] + "https://script.google.com/a/macros/ikns.edu.bh/s/WRONG" + text[end:]
    path.write_text(bad, encoding="utf-8")


def mutate_asc_column(recognizer: Path, frontend: Path):
    path = recognizer / "sets" / "ascended_heroes" / "manifest.json"
    data = load(path)
    data["inventory"]["cardIdColumn"] = 17
    dump(path, data)


def mutate_asc_variants(recognizer: Path, frontend: Path):
    path = recognizer / "sets" / "ascended_heroes" / "manifest.json"
    data = load(path)
    data["variants"] = [v for v in data["variants"] if v["variantId"] != "special-reverse"]
    data["inventory"]["quantityColumns"].pop("special-reverse", None)
    dump(path, data)


def mutate_asc_request_contract(recognizer: Path, frontend: Path):
    replace_once(
        frontend / "js" / "inventory-request.js",
        "parameters.change = String(delta);",
        "parameters.quantityDelta = String(delta);",
    )


def mutate_harmless_formatting(recognizer: Path, frontend: Path):
    # Python AST should ignore whitespace/comments.
    main = recognizer / "main.py"
    main.write_text("# harmless formatting\n\n" + main.read_text(encoding="utf-8"), encoding="utf-8")

    # JS semantics unchanged: single quotes + extra whitespace/newlines.
    path = frontend / "js" / "sets" / "pitch-black.js"
    text = path.read_text(encoding="utf-8")
    text = text.replace('id: "pitch-black"', "id : 'pitch-black'")
    text = text.replace('setCode: "PBL"', "setCode : 'PBL'")
    text = text.replace('series: "Mega Evolution"', "series : 'Mega Evolution'")
    text = text.replace('officialCode: "ME05"', "officialCode : 'ME05'")
    text = text.replace('datasetId: "me5"', "datasetId : 'me5'")
    path.write_text(text, encoding="utf-8")

    index = frontend / "index.html"
    text = index.read_text(encoding="utf-8")
    text = text.replace(
        '<script src="./js/sets/pitch-black.js"></script>',
        "<script   src='./js/sets/pitch-black.js' ></script>",
    )
    index.write_text(text, encoding="utf-8")


TESTS = []


def record(name: str, expected: str, actual: str, passed: bool, exit_code: int | None = None):
    TESTS.append({
        "name": name,
        "expected": expected,
        "actual": actual,
        "passed": passed,
        "exit_code": exit_code,
    })


def main() -> int:
    # 1. Known-good fixture + warnings + accepted exceptions + exit 0.
    holder, rec, front = copy_fixture()
    try:
        baseline, findings = findings_for(rec, front)
        cli = run_cli(rec, front)
        good = (
            vp.offline_status(findings, "ascended-heroes") == vp.WARNING
            and vp.offline_status(findings, "destined-rivals") == vp.WARNING
            and vp.offline_status(findings, "perfect-order") == vp.PASS
            and vp.offline_status(findings, "chaos-rising") == vp.PASS
            and vp.offline_status(findings, "pitch-black") == vp.PASS
            and has_finding(findings, status=vp.WARNING, check_contains="ASC_CANONICAL", set_id="ascended-heroes")
            and has_finding(findings, status=vp.WARNING, check_contains="DRI_GENERIC", set_id="destined-rivals")
            and not has_finding(findings, status=vp.FAIL, check_contains="accepted exception", set_id="ascended-heroes")
            and not has_finding(findings, status=vp.FAIL, check_contains="accepted exception", set_id="destined-rivals")
            and cli.returncode == 0
            and "OVERALL OFFLINE RESULT: PASS WITH WARNINGS" in cli.stdout
            and "FULL PRODUCTION VERIFICATION: NOT VERIFIED" in cli.stdout
        )
        record(
            "known-good fixture / exceptions / warnings",
            "ASC+DRI WARNING, POR+CRI+PBL PASS, no exception FAIL, exit 0",
            f"ASC={vp.offline_status(findings,'ascended-heroes')}, DRI={vp.offline_status(findings,'destined-rivals')}, exit={cli.returncode}",
            good,
            cli.returncode,
        )
    finally:
        holder.cleanup()

    # 2. Missing frontend -> NOT VERIFIED, exit 1.
    holder, rec, front = copy_fixture()
    try:
        _, findings = findings_for(rec, None)
        cli = run_cli(rec, None)
        ok = (
            all(vp.offline_status(findings, sid) == vp.NOT_VERIFIED for sid in load(rec / "tools" / "production_baseline_v1.json")["productionSetOrder"])
            and has_finding(findings, status=vp.NOT_VERIFIED, check_contains="set universe: frontend")
            and cli.returncode == 1
        )
        record("missing frontend evidence", "NOT VERIFIED + exit 1", f"exit={cli.returncode}", ok, cli.returncode)
    finally:
        holder.cleanup()

    fault_cases = [
        ("missing builder registration", mutate_builder_missing, "shared builder registration", "pitch-black"),
        ("duplicate builder registration", mutate_builder_duplicate, "shared builder registration", "perfect-order"),
        ("extra builder registration", mutate_builder_extra, "set universe: shared builder", None),
        ("missing recognizer router registration", mutate_router_missing, "recognizer router registration", "chaos-rising"),
        ("extra recognizer router registration", mutate_router_extra, "set universe: recognizer router", None),
        ("extra frontend set registration", mutate_frontend_extra, "set universe: frontend", None),
        ("duplicate frontend include", mutate_frontend_duplicate_include, "frontend index includes set exactly once", "pitch-black"),
        ("canonical ID duplicate", mutate_canonical_duplicate, "canonical ID sequence", "pitch-black"),
        ("card count missing", mutate_card_count, "catalogue card count", "pitch-black"),
        ("first identity mismatch", mutate_first_identity, "first card identity", "perfect-order"),
        ("frontend metadata mismatch", mutate_frontend_metadata, "frontend setCode", "chaos-rising"),
        ("Apps Script deployment identifier mismatch", mutate_apps_script_identifier, "frontend Apps Script target identifier", "perfect-order"),
        ("ASC Card ID column exception mismatch", mutate_asc_column, "ASC_CARD_ID_COLUMN_T", "ascended-heroes"),
        ("ASC variant exception mismatch", mutate_asc_variants, "ASC_CUSTOM_FIVE_VARIANT_LAYOUT", "ascended-heroes"),
        ("ASC legacy request-contract mismatch", mutate_asc_request_contract, "ASC_LEGACY_INVENTORY_REQUEST_CONTRACT", "ascended-heroes"),
    ]

    for name, mutator, check_fragment, set_id in fault_cases:
        holder, rec, front = copy_fixture()
        try:
            mutator(rec, front)
            _, findings = findings_for(rec, front)
            cli = run_cli(rec, front)
            ok = (
                has_finding(findings, status=vp.FAIL, check_contains=check_fragment, set_id=set_id)
                and cli.returncode == 1
            )
            actual_status = vp.offline_status(findings, set_id) if set_id else vp.offline_status(findings)
            record(name, f"FAIL on {check_fragment} + exit 1", f"status={actual_status}, exit={cli.returncode}", ok, cli.returncode)
        finally:
            holder.cleanup()

    # 16. Harmless formatting tolerance.
    holder, rec, front = copy_fixture()
    try:
        mutate_harmless_formatting(rec, front)
        _, findings = findings_for(rec, front)
        cli = run_cli(rec, front)
        ok = not any(f.status == vp.FAIL for f in findings if f.scope == "offline") and cli.returncode == 0
        failures = [f.check for f in findings if f.status == vp.FAIL and f.scope == "offline"]
        record("harmless parser formatting", "No FAIL + exit 0", f"failures={failures}, exit={cli.returncode}", ok, cli.returncode)
    finally:
        holder.cleanup()

    # 17. Validator must not mutate its fixture.
    holder, rec, front = copy_fixture()
    try:
        before_rec = tree_digest(rec)
        before_front = tree_digest(front)
        cli = run_cli(rec, front)
        after_rec = tree_digest(rec)
        after_front = tree_digest(front)
        rec_added = sorted(set(after_rec) - set(before_rec))
        front_added = sorted(set(after_front) - set(before_front))
        changed = sorted(k for k in before_rec.keys() & after_rec.keys() if before_rec[k] != after_rec[k])
        ok = before_rec == after_rec and before_front == after_front and cli.returncode == 0
        record(
            "no production mutation paths / filesystem immutability",
            "No added/changed fixture files + exit 0",
            f"recognizer_added={rec_added}, frontend_added={front_added}, changed={changed}, exit={cli.returncode}",
            ok,
            cli.returncode,
        )
    finally:
        holder.cleanup()

    # 18. Static safety scan: no network/mutation APIs in validator source.
    source = VALIDATOR_PATH.read_text(encoding="utf-8")
    forbidden = [
        "requests.",
        "urllib.request",
        "httpx.",
        "socket.",
        ".write_text(",
        ".write_bytes(",
        "open(\"w\"",
        "open('w'",
        "subprocess.",
        "googleapiclient",
        "render.com",
    ]
    hits = [token for token in forbidden if token in source]
    record(
        "static mutation/network safety scan",
        "No network/write/deploy primitives",
        f"hits={hits}",
        not hits,
        None,
    )

    print("\nSTAGE 1C RESULTS")
    print("=" * 88)
    failed = 0
    for idx, item in enumerate(TESTS, 1):
        state = "PASS" if item["passed"] else "FAIL"
        if not item["passed"]:
            failed += 1
        print(f"{idx:02d}. {state} — {item['name']}")
        print(f"    Expected: {item['expected']}")
        print(f"    Actual:   {item['actual']}")
        if item["exit_code"] is not None:
            print(f"    Exit:     {item['exit_code']}")
    print("=" * 88)
    print(f"TOTAL: {len(TESTS)}  PASSED: {len(TESTS)-failed}  FAILED: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
