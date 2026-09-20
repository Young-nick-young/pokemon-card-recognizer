#!/usr/bin/env python3
"""Validate Inventory Sheet Plan v1 and optional Google read-back snapshot."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

LETTERS=[chr(65+i) for i in range(17)]

class ValidationError(RuntimeError):
    pass

def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def expected_row_values(row):
    v=row["values"]
    return [
        None,
        v["collectorNumber"],
        v["name"],
        v["rarity"],
        v["cardType"],
        v["normalQty"],
        v["reverseHoloQty"],
        v["holoQty"],
        v["otherQty"],
        None,
        v["normalPriceBhd"],
        v["reversePriceBhd"],
        v["holoPriceBhd"],
        v["otherPriceBhd"],
        None,
        v["storageLocation"],
        v["compatibilityCardId"],
    ]

def validate_plan(plan):
    errors=[]
    if plan.get("inventorySheetPlanVersion")!=1: errors.append("plan version must be 1")
    if plan.get("headerRow")!=12: errors.append("headerRow must be 12")
    if plan.get("startRow")!=13: errors.append("startRow must be 13")
    if plan.get("freezeRows")!=12: errors.append("freezeRows must be 12")
    cols=plan.get("columns")
    rows=plan.get("rows")
    if not isinstance(cols,list) or len(cols)!=17: errors.append("plan must define exactly 17 columns A:Q")
    if not isinstance(rows,list) or not rows: errors.append("plan rows must be a non-empty array")
    if isinstance(rows,list) and rows:
        if plan.get("endRow")!=12+len(rows): errors.append("endRow does not match row count")
        ids=[r.get("canonicalCardId") for r in rows]
        compat=[r.get("compatibilityCardId") for r in rows]
        if len(ids)!=len(set(ids)): errors.append("duplicate canonicalCardId in plan")
        if len(compat)!=len(set(compat)): errors.append("duplicate compatibilityCardId in plan")
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
            for key in ("normalPriceBhd","reversePriceBhd","holoPriceBhd","otherPriceBhd","storageLocation"):
                if v.get(key) is not None: errors.append(f"row {i}: {key} must initialize blank")
    return errors

def validate_snapshot(plan,snapshot):
    errors=[]
    if snapshot.get("freezeRows")!=plan.get("freezeRows"): errors.append("frozen row count mismatch")
    headers=snapshot.get("headers")
    expected_headers=[c["header"] for c in plan["columns"]]
    if headers!=expected_headers: errors.append("header values mismatch")
    widths=snapshot.get("columnWidths")
    expected_widths=[c["widthPx"] for c in plan["columns"]]
    if widths!=expected_widths: errors.append("column widths mismatch")
    formats=snapshot.get("columnNumberFormats") or {}
    for col in plan["columns"]:
        expected=col.get("numberFormat")
        actual=formats.get(col["letter"])
        if expected and actual!=expected: errors.append(f'{col["letter"]}: number format mismatch ({actual!r} != {expected!r})')
    if snapshot.get("headerStyle")!=plan.get("headerStyle"): errors.append("header formatting invariant mismatch")
    body=snapshot.get("bodyStyle") or {}
    for key in ("fontFamily","fontSize","verticalAlignment","foregroundColor"):
        if body.get(key)!=plan["bodyStyle"].get(key): errors.append("body formatting invariant mismatch: "+key)
    actual_rows=snapshot.get("rows")
    if not isinstance(actual_rows,list) or len(actual_rows)!=len(plan["rows"]):
        errors.append("read-back row count mismatch")
        return errors
    for expected,actual in zip(plan["rows"],actual_rows):
        row=expected["row"]
        if actual.get("row")!=row: errors.append(f"row {row}: row coordinate mismatch"); continue
        values=actual.get("values")
        if values!=expected_row_values(expected): errors.append(f"row {row}: literal/blank values mismatch")
        formulas=actual.get("formulas") or {}
        if formulas.get("A")!=expected["values"]["imageFormula"]: errors.append(f"row {row}: image formula mismatch")
        if formulas.get("J")!=expected["values"]["totalFormula"]: errors.append(f"row {row}: total formula mismatch")
        if formulas.get("O")!=expected["values"]["collectionValueFormula"]: errors.append(f"row {row}: collection value formula mismatch")
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
