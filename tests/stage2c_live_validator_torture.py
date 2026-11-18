#!/usr/bin/env python3
"""Stage 2C torture tests: identity/variant separation and read-only safety."""
from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import google_sheets_readonly as gs

BASELINE = json.loads((TOOLS / "production_baseline_v1.json").read_text(encoding="utf-8"))
RESULTS=[]


def record(name, ok, actual=""):
    RESULTS.append((name, ok, actual))


class MockReader:
    def __init__(self, metadata, values):
        self.metadata=metadata
        self.values=values
        self.metadata_calls=[]
        self.value_calls=[]

    def get_spreadsheet_metadata(self, spreadsheet_id, sheet_name):
        self.metadata_calls.append((spreadsheet_id,sheet_name))
        return copy.deepcopy(self.metadata)

    def batch_get_values(self, spreadsheet_id, ranges):
        self.value_calls.append((spreadsheet_id,tuple(ranges)))
        return copy.deepcopy(self.values)


def fixture(set_id, authority=True):
    plan=gs.build_read_plan(BASELINE,set_id)
    ids=gs.load_expected_identities(ROOT,BASELINE,set_id)
    meta={"spreadsheetId":plan.spreadsheet_id,"title":plan.expected_title,"sheet":{"title":plan.sheet_name,"sheetId":plan.sheet_id}}
    identity=[[x.collector_number,x.name] for x in ids]
    card_ids=[[x.legacy_id] for x in ids]
    variant_width=max(plan.variant_columns.values())-min(plan.variant_columns.values())+1
    rows=[[None]*variant_width for _ in ids]
    auth=None
    if authority:
        auth=gs.load_inventory_authority(ROOT,BASELINE,set_id)
        vmin=min(plan.variant_columns.values())
        for i,enabled in enumerate(auth.variants_by_index):
            for variant,col in plan.variant_columns.items():
                rows[i][col-vmin]=0 if variant in enabled else None
    values={plan.identity_range:identity,plan.card_id_range:card_ids,plan.variant_range:rows}
    return plan,ids,auth,meta,values


# 1. DRI has no authority but still validates identity and Card IDs.
plan,ids,auth,meta,values=fixture("destined-rivals",authority=False)
reader=MockReader(meta,values)
findings=gs.validate_with_reader(reader,ROOT,BASELINE,"destined-rivals")
record("DRI identity survives missing variant authority",
       any(f.check=="inventory availability authority" and f.status==gs.NOT_VERIFIED for f in findings)
       and not any(f.status==gs.FAIL for f in findings), gs.overall_status(findings))

# 2-3. Explicit aliases warn, unknown name fails.
values2=copy.deepcopy(values)
values2[plan.identity_range][113][1]="Team Rocket's Nidoran♀"
values2[plan.identity_range][116][1]="Team Rocket's Nidoran♂"
findings=gs.validate_with_reader(MockReader(meta,values2),ROOT,BASELINE,"destined-rivals")
record("explicit DRI aliases warn", sum(f.status==gs.WARNING for f in findings)==2, [f.report_dict() for f in findings if f.status==gs.WARNING])

bad=copy.deepcopy(values2); bad[plan.identity_range][0][1]="Wrong Card"
findings=gs.validate_with_reader(MockReader(meta,bad),ROOT,BASELINE,"destined-rivals")
record("unknown name change fails", any(f.status==gs.FAIL and "card name" in f.check for f in findings), gs.overall_status(findings))

# 4. POR corrected authority matches a good snapshot.
plan,ids,auth,meta,values=fixture("perfect-order",authority=True)
findings=gs.validate_with_reader(MockReader(meta,values),ROOT,BASELINE,"perfect-order")
record("POR good authority snapshot passes", gs.overall_status(findings)==gs.PASS, gs.overall_status(findings))

# 5. Available blank fails.
bad=copy.deepcopy(values)
first_variant=next(iter(auth.variants_by_index[0]))
offset=plan.variant_columns[first_variant]-min(plan.variant_columns.values())
bad[plan.variant_range][0][offset]=None
findings=gs.validate_with_reader(MockReader(meta,bad),ROOT,BASELINE,"perfect-order")
record("available blank fails", any(f.status==gs.FAIL and "variant" in f.check for f in findings), gs.overall_status(findings))

# 6. Unavailable zero fails on a known Holo-only POR card.
bad=copy.deepcopy(values)
row_index=11
normal_offset=plan.variant_columns["normal"]-min(plan.variant_columns.values())
bad[plan.variant_range][row_index][normal_offset]=0
findings=gs.validate_with_reader(MockReader(meta,bad),ROOT,BASELINE,"perfect-order")
record("unavailable zero fails", any(f.status==gs.FAIL and "variant" in f.check for f in findings), gs.overall_status(findings))

# 7. Duplicate Card ID fails.
bad=copy.deepcopy(values); bad[plan.card_id_range][1][0]=bad[plan.card_id_range][0][0]
findings=gs.validate_with_reader(MockReader(meta,bad),ROOT,BASELINE,"perfect-order")
record("duplicate Card ID fails", any(f.status==gs.FAIL and f.check=="duplicate legacy Card IDs" for f in findings), gs.overall_status(findings))

# 8. Wrong workbook fails.
bad_meta=copy.deepcopy(meta); bad_meta["spreadsheetId"]="WRONG"
findings=gs.validate_with_reader(MockReader(bad_meta,values),ROOT,BASELINE,"perfect-order")
record("wrong workbook fails", any(f.status==gs.FAIL and f.check=="workbook identifier" for f in findings), gs.overall_status(findings))

# 9. Exact bounded ranges only.
reader=MockReader(meta,values)
gs.validate_with_reader(reader,ROOT,BASELINE,"perfect-order")
record("exact bounded ranges only", reader.value_calls==[(plan.spreadsheet_id,plan.ranges)], reader.value_calls)

# 10. Missing evidence remains NOT VERIFIED rather than false PASS.
reader=MockReader({}, {})
findings=gs.validate_with_reader(reader,ROOT,BASELINE,"perfect-order")
record("missing read evidence is NOT VERIFIED", gs.overall_status(findings)==gs.NOT_VERIFIED, gs.overall_status(findings))

# 11. Live transport statically exposes GET only, no write verbs/methods.
source=(TOOLS/"google_sheets_live_reader.py").read_text(encoding="utf-8")
tree=ast.parse(source)
calls=[]
for node in ast.walk(tree):
    if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
        if node.func.attr in {"post","put","patch","delete","update","append","clear","batchUpdate"}:
            calls.append(node.func.attr)
record("live transport has no write-capable calls", not calls, calls)
record("readonly scope is explicit", "spreadsheets.readonly" in source, "spreadsheets.readonly" in source)

# 12. No credentials embedded.
markers=["-----BEGIN PRIVATE KEY-----","ya29.","AIza"]
record("no credential-shaped values embedded", not any(x in source for x in markers), [x for x in markers if x in source])

failed=0
print("STAGE 2C TORTURE RESULTS")
print("="*90)
for i,(name,ok,actual) in enumerate(RESULTS,1):
    state="PASS" if ok else "FAIL"
    if not ok: failed+=1
    print(f"{i:02d}. {state} — {name}")
    if not ok: print("    Actual:",actual)
print("="*90)
print(f"TOTAL: {len(RESULTS)}  PASSED: {len(RESULTS)-failed}  FAILED: {failed}")
raise SystemExit(1 if failed else 0)
