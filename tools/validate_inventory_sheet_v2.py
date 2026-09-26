#!/usr/bin/env python3
"""Validate Inventory Sheet Plan v2 and optional Google read-back snapshot."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

STANDARD_WIDTHS=[80,108,180,110,120,120,113,118,116,100,101,99,100,100,100,100,96]
STANDARD_SUMMARY=[
    ("Total Bulk Copies","F1:G2","F3:G3"),
    ("Total Bulk Value","F6:G7","F8:G8"),
    ("Normal","I1:J2","I3:J3"),
    ("Holo","L1:M2","L3:M3"),
    ("Reverse Holo","O1:P2","O3:P3"),
]

def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def validate_plan(plan):
    errors=[]
    if plan.get("inventorySheetPlanVersion")!=2: errors.append("plan version must be 2")
    if plan.get("headerRow")!=12: errors.append("headerRow must be 12")
    if plan.get("startRow")!=13: errors.append("startRow must be 13")
    if plan.get("freezeRows")!=12: errors.append("freezeRows must be 12")
    if plan.get("logoRange")!="A1:E10": errors.append("logoRange must be A1:E10")

    cols=plan.get("columns")
    rows=plan.get("rows")
    if not isinstance(cols,list) or len(cols)!=17:
        errors.append("plan must define exactly 17 columns A:Q")
    elif [c.get("widthPx") for c in cols] != STANDARD_WIDTHS:
        errors.append("column widths do not match the standardized modern layout")
    else:
        if cols[1].get("numberFormat")!="000": errors.append("Card # column must use number format 000")

    heights=plan.get("rowHeights") or {}
    if heights.get("topRows")!={"start":1,"end":11,"pixelSize":21}: errors.append("top row heights must be 21px for rows 1:11")
    if heights.get("header")!={"row":12,"pixelSize":42}: errors.append("header row must be 42px")
    body_height=heights.get("body") or {}
    if body_height.get("start")!=13 or body_height.get("pixelSize")!=96: errors.append("body rows must begin at 13 and be 96px")

    boxes=plan.get("summaryBoxes")
    if not isinstance(boxes,list) or len(boxes)!=5:
        errors.append("exactly five summary boxes are required")
    else:
        basic=[(b.get("label"),b.get("labelRange"),b.get("valueRange")) for b in boxes]
        if basic!=STANDARD_SUMMARY: errors.append("summary box layout does not match the standardized modern layout")

    if not isinstance(rows,list) or not rows:
        errors.append("plan rows must be a non-empty array")
        return errors
    if plan.get("endRow")!=12+len(rows): errors.append("endRow does not match row count")
    if body_height.get("end")!=plan.get("endRow"): errors.append("body row-height range does not end at endRow")

    ids=[r.get("canonicalCardId") for r in rows]
    compat=[r.get("compatibilityCardId") for r in rows]
    if len(ids)!=len(set(ids)): errors.append("duplicate canonicalCardId in plan")
    if len(compat)!=len(set(compat)): errors.append("duplicate compatibilityCardId in plan")

    holo_only_rarities={"illustration rare","art rare","special illustration rare","special art rare","ultra rare"}
    for i,row in enumerate(rows,start=13):
        if row.get("row")!=i: errors.append(f"row coordinate mismatch at planned row {i}")
        v=row.get("values") or {}
        if v.get("collectorNumber") is None: errors.append(f"row {i}: collectorNumber missing")
        if v.get("compatibilityCardId")!=row.get("compatibilityCardId"): errors.append(f"row {i}: compatibility ID drift")
        if v.get("totalFormula")!=f"=SUM(F{i}:I{i})": errors.append(f"row {i}: total formula mismatch")
        expected=f'=IF(B{i}="","",IFERROR((F{i}*K{i})+(G{i}*L{i})+(H{i}*M{i})+(I{i}*N{i}),0))'
        if v.get("collectionValueFormula")!=expected: errors.append(f"row {i}: collection value formula mismatch")
        enabled=set(row.get("inventoryVariants") or [])
        qty={"normal":v.get("normalQty"),"reverse-holo":v.get("reverseHoloQty"),"holo":v.get("holoQty"),"other":v.get("otherQty")}
        for variant,value in qty.items():
            if variant in enabled and value!=0: errors.append(f"row {i}: enabled {variant} must initialize to 0")
            if variant not in enabled and value is not None: errors.append(f"row {i}: unavailable {variant} must be blank")
        name=str(row.get("name") or "")
        rarity=str(row.get("rarity") or "")
        if name.lower().endswith(" ex") or rarity.lower() in holo_only_rarities:
            if enabled != {"holo"}: errors.append(f"row {i}: ex/IR/SIR/Ultra Rare must be Holo-only")
        for key in ("normalPriceBhd","reversePriceBhd","holoPriceBhd","otherPriceBhd","storageLocation"):
            if v.get(key) is not None: errors.append(f"row {i}: {key} must initialize blank")

    end=plan["endRow"]
    expected_formulas={
        "Total Bulk Copies":f"=SUM(J13:J{end})",
        "Total Bulk Value":f"=SUM(O13:O{end})",
        "Normal":f"=SUM(F13:F{end})",
        "Holo":f"=SUM(H13:H{end})",
        "Reverse Holo":f"=SUM(G13:G{end})",
    }
    for box in boxes or []:
        if expected_formulas.get(box.get("label"))!=box.get("formula"):
            errors.append("summary formula mismatch for "+str(box.get("label")))
    return errors

def validate_snapshot(plan,snapshot):
    errors=[]
    if snapshot.get("freezeRows")!=plan.get("freezeRows"): errors.append("frozen row count mismatch")
    if snapshot.get("logoRange")!=plan.get("logoRange"): errors.append("logo reserve mismatch")
    if snapshot.get("headers")!=[c["header"] for c in plan["columns"]]: errors.append("header values mismatch")
    if snapshot.get("columnWidths")!=[c["widthPx"] for c in plan["columns"]]: errors.append("column widths mismatch")
    if snapshot.get("rowHeights")!=plan.get("rowHeights"): errors.append("row heights mismatch")
    if snapshot.get("summaryBoxes")!=plan.get("summaryBoxes"): errors.append("summary box values/formulas mismatch")
    actual_rows=snapshot.get("rows")
    if not isinstance(actual_rows,list) or len(actual_rows)!=len(plan["rows"]):
        errors.append("read-back row count mismatch")
        return errors
    for expected,actual in zip(plan["rows"],actual_rows):
        row=expected["row"]
        if actual.get("row")!=row:
            errors.append(f"row {row}: row coordinate mismatch")
            continue
        if actual.get("inventoryVariants")!=expected.get("inventoryVariants"):
            errors.append(f"row {row}: variant availability mismatch")
        values=actual.get("values") or {}
        for key in ("collectorNumber","name","rarity","cardType","normalQty","reverseHoloQty","holoQty","otherQty","compatibilityCardId"):
            if values.get(key)!=expected["values"].get(key): errors.append(f"row {row}: {key} mismatch")
    return errors

def render(errors,label):
    if errors:
        print(label+": FAIL")
        for e in errors: print("FAIL ",e)
        return False
    print(label+": PASS")
    return True

def parse_args(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--plan",required=True,type=Path)
    p.add_argument("--snapshot",type=Path)
    return p.parse_args(argv)

def main(argv=None):
    a=parse_args(argv)
    try:
        plan=load_json(a.plan)
        ok=render(validate_plan(plan),"Local plan validation")
        if a.snapshot:
            snap=load_json(a.snapshot)
            ok=render(validate_snapshot(plan,snap),"Google Sheet read-back validation") and ok
        return 0 if ok else 1
    except Exception as exc:
        print("FAIL:",exc,file=sys.stderr); return 1

if __name__=="__main__":
    raise SystemExit(main())
