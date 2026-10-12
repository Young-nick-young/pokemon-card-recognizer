#!/usr/bin/env python3
"""Stage 2A mocked Google Sheets adapter torture tests.

No Google API, OAuth flow, network request, or live Sheet access occurs here.
Every test uses local temporary copies and in-memory mock responses only.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "tools" / "google_sheets_readonly.py"
BASELINE_PATH = ROOT / "tools" / "production_baseline_v1.json"

spec = importlib.util.spec_from_file_location("google_sheets_readonly_stage2a", ADAPTER_PATH)
gs = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = gs
spec.loader.exec_module(gs)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


BASELINE = load(BASELINE_PATH)
RESULTS = []


def record(name, expected, actual, passed):
    RESULTS.append({"name": name, "expected": expected, "actual": actual, "passed": bool(passed)})


def copy_repo():
    holder = tempfile.TemporaryDirectory(prefix="stage2a-")
    dst = Path(holder.name) / "recognizer"
    shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
    return holder, dst


def make_mock_authority(root: Path, set_id: str, per_card=None):
    set_data = BASELINE["sets"][set_id]
    count = set_data["expectedCardCount"]
    variants = list(set_data["variantRulesExpectedOffline"]["variants"])
    if per_card is None:
        per_card = [variants[:] for _ in range(count)]
    data = {
        "inventoryMetadataVersion": 2,
        "setId": set_id,
        "source": {
            "kind": "stage2a-fixture",
            "note": "Explicit mocked physical inventory authority for Stage 2A only."
        },
        "cards": [
            {
                "cardId": f"fixture-{i:03d}",
                "rarity": "Fixture",
                "cardType": None,
                "inventoryVariants": per_card[i - 1],
            }
            for i in range(1, count + 1)
        ],
    }
    package = root / set_data["schema"]["packagePath"]
    dump(package / "inventory_metadata.json", data)
    return package / "inventory_metadata.json"


class MockReader:
    def __init__(self, metadata, values, *, metadata_error=None, values_error=None):
        self.metadata = metadata
        self.values = values
        self.metadata_error = metadata_error
        self.values_error = values_error
        self.metadata_calls = []
        self.value_calls = []

    def get_spreadsheet_metadata(self, spreadsheet_id, sheet_name):
        self.metadata_calls.append((spreadsheet_id, sheet_name))
        if self.metadata_error:
            raise self.metadata_error
        return copy.deepcopy(self.metadata)

    def batch_get_values(self, spreadsheet_id, ranges):
        self.value_calls.append((spreadsheet_id, tuple(ranges)))
        if self.values_error:
            raise self.values_error
        return copy.deepcopy(self.values)


def good_fixture(root: Path, set_id: str, *, authority=None):
    plan = gs.build_read_plan(BASELINE, set_id)
    if authority is None:
        try:
            authority = gs.load_inventory_authority(root, BASELINE, set_id)
        except gs.AuthorityUnavailable:
            make_mock_authority(root, set_id)
            authority = gs.load_inventory_authority(root, BASELINE, set_id)
    identities = gs.load_expected_identities(root, BASELINE, set_id)

    meta = {
        "spreadsheetId": plan.spreadsheet_id,
        "title": plan.expected_title,
        "sheet": {"title": plan.sheet_name, "sheetId": plan.sheet_id},
    }
    identity_rows = [[x.collector_number, x.name] for x in identities]
    card_rows = [[x.legacy_id] for x in identities]
    variant_min = min(plan.variant_columns.values())
    width = max(plan.variant_columns.values()) - variant_min + 1
    variant_rows = []
    for index, enabled in enumerate(authority.variants_by_index):
        row = [None] * width
        for variant, col in plan.variant_columns.items():
            row[col - variant_min] = 0 if variant in enabled else None
        variant_rows.append(row)
    values = {
        plan.identity_range: identity_rows,
        plan.card_id_range: card_rows,
        plan.variant_range: variant_rows,
    }
    return plan, authority, identities, meta, values


def run_compare(root, set_id, meta, values, authority=None):
    plan = gs.build_read_plan(BASELINE, set_id)
    if authority is None:
        authority = gs.load_inventory_authority(root, BASELINE, set_id)
    identities = gs.load_expected_identities(root, BASELINE, set_id)
    return gs.compare_snapshot(plan, authority, identities, meta, values)


def has(findings, status, text):
    return any(f.status == status and text in f.check for f in findings)


# 1. Exact bounded ranges for all five sets + intentional layouts/workbooks.
holder, root = copy_repo()
try:
    expected = {
        "ascended-heroes": (
            "1EsYzX-JqWqzksqaOBrvn6xu6RnIzWhqNJhcW2UQAKsE",
            "'Ascended Heroes'!B13:C307", "'Ascended Heroes'!T13:T307", "'Ascended Heroes'!G13:K307",
        ),
        "destined-rivals": (
            "1Fkgs9gtgrpeeyPkaIWOKHgPnv3Zyxryq288o7cWsVvY",
            "'Destined Rivals'!B13:C256", "'Destined Rivals'!Q13:Q256", "'Destined Rivals'!F13:I256",
        ),
        "perfect-order": (
            "1EsYzX-JqWqzksqaOBrvn6xu6RnIzWhqNJhcW2UQAKsE",
            "'Perfect Order'!B13:C136", "'Perfect Order'!Q13:Q136", "'Perfect Order'!F13:I136",
        ),
        "chaos-rising": (
            "1EsYzX-JqWqzksqaOBrvn6xu6RnIzWhqNJhcW2UQAKsE",
            "'Chaos Rising'!B13:C134", "'Chaos Rising'!Q13:Q134", "'Chaos Rising'!F13:I134",
        ),
        "pitch-black": (
            "1EsYzX-JqWqzksqaOBrvn6xu6RnIzWhqNJhcW2UQAKsE",
            "'Pitch Black'!B13:C132", "'Pitch Black'!Q13:Q132", "'Pitch Black'!F13:I132",
        ),
    }
    actual = {}
    for sid in BASELINE["productionSetOrder"]:
        p = gs.build_read_plan(BASELINE, sid)
        actual[sid] = (p.spreadsheet_id, *p.ranges)
    record("bounded ranges + ASC/DRI/standard layouts", expected, actual, actual == expected)
finally:
    holder.cleanup()


# 2. Actual ASC committed authority loads from Sheet Plan and has 295 rows.
holder, root = copy_repo()
try:
    auth = gs.load_inventory_authority(root, BASELINE, "ascended-heroes")
    ok = auth.source_kind == "inventory_sheet_plan" and len(auth.variants_by_index) == 295
    record("ASC accepted authority loads from Sheet Plan", "inventory_sheet_plan / 295", f"{auth.source_kind} / {len(auth.variants_by_index)}", ok)
finally:
    holder.cleanup()


# 3. Poison Schema cards[].variants; authority must not change.
holder, root = copy_repo()
try:
    before = gs.load_inventory_authority(root, BASELINE, "ascended-heroes")
    cards_path = root / BASELINE["sets"]["ascended-heroes"]["schema"]["cardsPath"]
    cards = load(cards_path)
    for card in cards["cards"]:
        card["variants"] = ["THIS-MUST-NOT-BE-AUTHORITY"]
    dump(cards_path, cards)
    after = gs.load_inventory_authority(root, BASELINE, "ascended-heroes")
    record("Schema cards[].variants ignored for inventory availability", before.variants_by_index, after.variants_by_index, before.variants_by_index == after.variants_by_index)
finally:
    holder.cleanup()


# 4. Missing authority on a standard set -> NOT VERIFIED, no inference.
holder, root = copy_repo()
try:
    plan = gs.build_read_plan(BASELINE, "perfect-order")
    dummy = MockReader({}, {})
    findings = gs.validate_with_reader(dummy, root, BASELINE, "perfect-order")
    record("missing inventory authority", "NOT VERIFIED", gs.overall_status(findings), gs.overall_status(findings) == gs.NOT_VERIFIED)
finally:
    holder.cleanup()


# 5. Good mocked reads for standard POR/CRI/PBL and DRI.
holder, root = copy_repo()
try:
    statuses = {}
    calls = {}
    for sid in ("destined-rivals", "perfect-order", "chaos-rising", "pitch-black"):
        make_mock_authority(root, sid)
        plan, auth, ids, meta, values = good_fixture(root, sid)
        reader = MockReader(meta, values)
        findings = gs.validate_with_reader(reader, root, BASELINE, sid)
        statuses[sid] = gs.overall_status(findings)
        calls[sid] = reader.value_calls
    ok = all(v == gs.PASS for v in statuses.values())
    record("good mocked DRI/POR/CRI/PBL reads", "all PASS", statuses, ok)
    bounded = all(calls[sid] == [(gs.build_read_plan(BASELINE, sid).spreadsheet_id, gs.build_read_plan(BASELINE, sid).ranges)] for sid in calls)
    record("reader receives only exact bounded ranges", "exact 3 ranges per set", calls, bounded)
finally:
    holder.cleanup()


# 6. Good ASC mock using real accepted availability matrix.
holder, root = copy_repo()
try:
    plan, auth, ids, meta, values = good_fixture(root, "ascended-heroes")
    reader = MockReader(meta, values)
    findings = gs.validate_with_reader(reader, root, BASELINE, "ascended-heroes")
    record("good ASC A:T / five-variant mock", "PASS", gs.overall_status(findings), gs.overall_status(findings) == gs.PASS)
finally:
    holder.cleanup()


# 7-9. Blank / zero / positive semantics.
holder, root = copy_repo()
try:
    sid = "perfect-order"
    variants = BASELINE["sets"][sid]["variantRulesExpectedOffline"]["variants"]
    count = BASELINE["sets"][sid]["expectedCardCount"]
    per_card = [["normal"] for _ in range(count)]
    make_mock_authority(root, sid, per_card)
    plan, auth, ids, meta, good = good_fixture(root, sid)

    # Available zero is valid.
    findings = run_compare(root, sid, meta, copy.deepcopy(good), auth)
    record("available variant quantity zero", "PASS", gs.overall_status(findings), gs.overall_status(findings) == gs.PASS)

    # Available positive is valid.
    pos = copy.deepcopy(good)
    pos[plan.variant_range][0][0] = 3
    findings = run_compare(root, sid, meta, pos, auth)
    record("available variant positive quantity", "PASS", gs.overall_status(findings), gs.overall_status(findings) == gs.PASS)

    # Available blank fails.
    bad = copy.deepcopy(good)
    bad[plan.variant_range][0][0] = None
    findings = run_compare(root, sid, meta, bad, auth)
    record("available variant blank", "FAIL", gs.overall_status(findings), gs.overall_status(findings) == gs.FAIL)

    # Unavailable zero fails.
    bad = copy.deepcopy(good)
    bad[plan.variant_range][0][1] = 0
    findings = run_compare(root, sid, meta, bad, auth)
    record("unavailable variant zero", "FAIL", gs.overall_status(findings), gs.overall_status(findings) == gs.FAIL)

    # Unavailable positive fails.
    bad = copy.deepcopy(good)
    bad[plan.variant_range][0][1] = 2
    findings = run_compare(root, sid, meta, bad, auth)
    record("unavailable variant positive", "FAIL", gs.overall_status(findings), gs.overall_status(findings) == gs.FAIL)
finally:
    holder.cleanup()


# 10. Malformed and negative quantities fail.
holder, root = copy_repo()
try:
    sid = "perfect-order"
    count = BASELINE["sets"][sid]["expectedCardCount"]
    make_mock_authority(root, sid, [["normal"] for _ in range(count)])
    plan, auth, ids, meta, values = good_fixture(root, sid)
    for label, raw in (("negative", -1), ("text", "many"), ("fractional", 1.5)):
        bad = copy.deepcopy(values)
        bad[plan.variant_range][0][0] = raw
        findings = run_compare(root, sid, meta, bad, auth)
        record(f"malformed quantity: {label}", "FAIL", gs.overall_status(findings), gs.overall_status(findings) == gs.FAIL)
finally:
    holder.cleanup()


# 11-15. Identity failures.
holder, root = copy_repo()
try:
    sid = "pitch-black"
    make_mock_authority(root, sid)
    plan, auth, ids, meta, values = good_fixture(root, sid)

    bad = copy.deepcopy(values); bad[plan.card_id_range][5][0] = bad[plan.card_id_range][4][0]
    findings = run_compare(root, sid, meta, bad, auth)
    record("duplicate legacy Card ID", "FAIL", gs.overall_status(findings), gs.overall_status(findings) == gs.FAIL and has(findings, gs.FAIL, "duplicate legacy Card IDs"))

    bad = copy.deepcopy(values); bad[plan.card_id_range][5][0] = ""
    findings = run_compare(root, sid, meta, bad, auth)
    record("missing legacy Card ID", "FAIL", gs.overall_status(findings), gs.overall_status(findings) == gs.FAIL and has(findings, gs.FAIL, "missing legacy Card IDs"))

    bad = copy.deepcopy(values); bad[plan.card_id_range][5][0] = "WRONG-006"
    findings = run_compare(root, sid, meta, bad, auth)
    record("wrong legacy Card ID", "FAIL", gs.overall_status(findings), gs.overall_status(findings) == gs.FAIL)

    bad = copy.deepcopy(values); bad[plan.identity_range][4], bad[plan.identity_range][5] = bad[plan.identity_range][5], bad[plan.identity_range][4]
    findings = run_compare(root, sid, meta, bad, auth)
    record("collector order / wrong row", "FAIL", gs.overall_status(findings), gs.overall_status(findings) == gs.FAIL)

    bad = copy.deepcopy(values); bad[plan.identity_range].pop(10); bad[plan.card_id_range].pop(10); bad[plan.variant_range].pop(10)
    findings = run_compare(root, sid, meta, bad, auth)
    record("missing live row", "FAIL", gs.overall_status(findings), gs.overall_status(findings) == gs.FAIL and has(findings, gs.FAIL, "row count"))
finally:
    holder.cleanup()


# 16. Numeric collector values normalize without false positive.
holder, root = copy_repo()
try:
    sid = "chaos-rising"
    make_mock_authority(root, sid)
    plan, auth, ids, meta, values = good_fixture(root, sid)
    numeric = copy.deepcopy(values)
    for i, row in enumerate(numeric[plan.identity_range], 1):
        row[0] = i
    findings = run_compare(root, sid, meta, numeric, auth)
    record("numeric collector display normalization", "PASS", gs.overall_status(findings), gs.overall_status(findings) == gs.PASS)
finally:
    holder.cleanup()


# 17. Workbook/sheet metadata mismatches fail.
holder, root = copy_repo()
try:
    sid = "destined-rivals"
    make_mock_authority(root, sid)
    plan, auth, ids, meta, values = good_fixture(root, sid)
    bad_meta = copy.deepcopy(meta); bad_meta["spreadsheetId"] = BASELINE["workbooks"]["mega-evolution"]["expectedSpreadsheetId"]
    findings = run_compare(root, sid, bad_meta, values, auth)
    record("DRI wrong workbook evidence", "FAIL", gs.overall_status(findings), gs.overall_status(findings) == gs.FAIL)
    bad_meta = copy.deepcopy(meta); bad_meta["sheet"]["sheetId"] = 999
    findings = run_compare(root, sid, bad_meta, values, auth)
    record("wrong sheet/tab ID", "FAIL", gs.overall_status(findings), gs.overall_status(findings) == gs.FAIL)
finally:
    holder.cleanup()


# 18. Missing returned bounded range -> NOT VERIFIED.
holder, root = copy_repo()
try:
    sid = "perfect-order"
    make_mock_authority(root, sid)
    plan, auth, ids, meta, values = good_fixture(root, sid)
    missing = copy.deepcopy(values); missing.pop(plan.variant_range)
    findings = run_compare(root, sid, meta, missing, auth)
    record("missing bounded API range evidence", "NOT VERIFIED", gs.overall_status(findings), gs.overall_status(findings) == gs.NOT_VERIFIED)
finally:
    holder.cleanup()


# 19. Auth/API evidence -> NOT VERIFIED and secret never enters report.
holder, root = copy_repo()
try:
    sid = "perfect-order"
    make_mock_authority(root, sid)
    secret = "SUPER_SECRET_TOKEN_123"
    reader = MockReader({}, {}, metadata_error=gs.AuthenticationUnavailable("Bearer " + secret))
    findings = gs.validate_with_reader(reader, root, BASELINE, sid)
    rendered = json.dumps([f.report_dict() for f in findings])
    record("auth unavailable", "NOT VERIFIED", gs.overall_status(findings), gs.overall_status(findings) == gs.NOT_VERIFIED)
    record("credentials/tokens redacted from reports", "secret absent", rendered, secret not in rendered and "Bearer" not in rendered)

    reader = MockReader({}, {}, values_error=gs.ReadEvidenceUnavailable("access_token=" + secret))
    # Metadata must succeed before values error.
    plan, auth, ids, meta, values = good_fixture(root, sid)
    reader.metadata = meta
    findings = gs.validate_with_reader(reader, root, BASELINE, sid)
    rendered = json.dumps([f.report_dict() for f in findings])
    record("API/read evidence unavailable", "NOT VERIFIED", gs.overall_status(findings), gs.overall_status(findings) == gs.NOT_VERIFIED)
    record("API error secret redaction", "secret absent", rendered, secret not in rendered)
finally:
    holder.cleanup()


# 20. Wrong layout in baseline is rejected before any read.
for sid, field, bad_value in (
    ("ascended-heroes", "cardIdColumn", 17),
    ("perfect-order", "cardIdColumn", 20),
):
    broken = copy.deepcopy(BASELINE)
    broken["sets"][sid]["inventoryExpectedOffline"][field] = bad_value
    try:
        gs.build_read_plan(broken, sid)
        actual = "accepted"
        ok = False
    except gs.ConfigurationError as error:
        actual = str(error)
        ok = True
    record(f"wrong accepted layout rejected: {sid}", "ConfigurationError", actual, ok)


# 21. ASC five-variant structure mutation rejected.
broken = copy.deepcopy(BASELINE)
broken["sets"]["ascended-heroes"]["inventoryExpectedOffline"]["variantColumns"].pop("special-reverse")
try:
    gs.build_read_plan(broken, "ascended-heroes")
    actual = "accepted"
    ok = False
except gs.ConfigurationError as error:
    actual = str(error)
    ok = True
record("ASC five-variant layout mutation", "ConfigurationError", actual, ok)


# 22. Standard POR/CRI/PBL F:I/Q structures independently proven.
structures = {}
for sid in ("perfect-order", "chaos-rising", "pitch-black"):
    p = gs.build_read_plan(BASELINE, sid)
    structures[sid] = (p.card_id_column, tuple(p.variant_columns.values()))
record("POR/CRI/PBL standard F:I/Q structure", {sid:(17,(6,7,8,9)) for sid in structures}, structures, all(v == (17,(6,7,8,9)) for v in structures.values()))


# 23. Static adapter AST: no file write, subprocess, network, or Google write method calls.
source = ADAPTER_PATH.read_text(encoding="utf-8")
tree = ast.parse(source)
forbidden_attrs = {"update", "batchUpdate", "append", "clear", "write_text", "write_bytes", "unlink", "rename", "replace"}
forbidden_names = {"open", "urlopen", "request", "post", "put", "patch", "delete", "subprocess"}
hits = []
for node in ast.walk(tree):
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in forbidden_attrs:
            hits.append("attribute-call:" + func.attr)
        elif isinstance(func, ast.Name) and func.id in forbidden_names:
            hits.append("name-call:" + func.id)
imports = []
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        imports.extend(alias.name for alias in node.names)
    elif isinstance(node, ast.ImportFrom) and node.module:
        imports.append(node.module)
unsafe_imports = [name for name in imports if name.startswith(("requests", "httpx", "googleapiclient", "google.auth", "urllib", "socket", "subprocess"))]
record("no write/network-capable adapter code path", "no forbidden calls/imports", {"calls":hits,"imports":unsafe_imports}, not hits and not unsafe_imports)


# 24. Adapter source has no credential material or scopes in Stage 2A.
credential_markers = ["client_secret", "private_key", "refresh_token", "AIza", "ya29."]
found = [m for m in credential_markers if m in source]
record("no credentials/tokens embedded", "none", found, not found)


# 25. Executing validator through mock does not mutate fixture files.
holder, root = copy_repo()
try:
    sid = "perfect-order"
    make_mock_authority(root, sid)
    before = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*") if p.is_file()
    }
    plan, auth, ids, meta, values = good_fixture(root, sid)
    reader = MockReader(meta, values)
    gs.validate_with_reader(reader, root, BASELINE, sid)
    after = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*") if p.is_file()
    }
    record("adapter comparison is filesystem read-only", "no file changes", {"added":sorted(set(after)-set(before)), "changed":sorted(k for k in before.keys() & after.keys() if before[k]!=after[k])}, before == after)
finally:
    holder.cleanup()


print("\nSTAGE 2A RESULTS")
print("=" * 100)
failed = 0
for i, result in enumerate(RESULTS, 1):
    state = "PASS" if result["passed"] else "FAIL"
    if not result["passed"]:
        failed += 1
    print(f"{i:02d}. {state} — {result['name']}")
    print(f"    Expected: {result['expected']}")
    print(f"    Actual:   {result['actual']}")
print("=" * 100)
print(f"TOTAL: {len(RESULTS)}  PASSED: {len(RESULTS)-failed}  FAILED: {failed}")
raise SystemExit(1 if failed else 0)
