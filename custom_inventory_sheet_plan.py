#!/usr/bin/env python3
"""Declarative custom/variable-width inventory planner.

This is intentionally separate from schema_v1_inventory_sheet_plan.py.
Normal four-variant sets continue to use Inventory Sheet Automation v2 unchanged.
"""
from __future__ import annotations
import json
from pathlib import Path

class CustomInventoryLayoutError(RuntimeError):
    pass

def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def _bucket_map(layout):
    out={}
    for b in layout["inventoryBuckets"]:
        bid=b["id"]
        if bid in out:
            raise CustomInventoryLayoutError("duplicate bucket: "+bid)
        out[bid]=b
    return out

def _sum_formula(columns, row):
    if not columns:
        raise CustomInventoryLayoutError("at least one inventory quantity column is required")
    return f"=SUM({columns[0]}{row}:{columns[-1]}{row})"

def _value_formula(buckets, row, identity_col):
    terms=[f'({b["quantityColumn"]}{row}*{b["priceColumn"]}{row})' for b in buckets]
    return f'=IF({identity_col}{row}="","",IFERROR('+"+".join(terms)+",0))"

def _summary_formula(summary, buckets, start_row, end_row):
    op=summary["operation"]
    if op=="sumColumn":
        c=summary["column"]
        return f"=SUM({c}{start_row}:{c}{end_row})"
    if op=="sumBuckets":
        parts=[]
        for bid in summary["buckets"]:
            if bid not in buckets:
                raise CustomInventoryLayoutError("unknown summary bucket: "+bid)
            c=buckets[bid]["quantityColumn"]
            parts.append(f"SUM({c}{start_row}:{c}{end_row})")
        return "="+ "+".join(parts)
    raise CustomInventoryLayoutError("unsupported summary operation: "+str(op))

def build_custom_inventory_sheet_plan(catalogue_path, metadata_path, layout_path):
    catalogue=_load(catalogue_path)
    metadata=_load(metadata_path)
    layout=_load(layout_path)
    if layout.get("kind")!="custom-variable-width":
        raise CustomInventoryLayoutError("custom-variable-width layout required")
    if metadata.get("setId")!=layout.get("setId"):
        raise CustomInventoryLayoutError("metadata/layout setId mismatch")
    buckets=_bucket_map(layout)
    declared=set(buckets)
    cards=metadata.get("cards") or []
    if len(catalogue)!=len(cards):
        raise CustomInventoryLayoutError(f"catalogue count {len(catalogue)} != metadata count {len(cards)}")
    meta={c["cardId"]:c for c in cards}
    if len(meta)!=len(cards):
        raise CustomInventoryLayoutError("duplicate metadata cardId")
    start=int(layout["startRow"])
    identity_col=layout["identity"]["column"]
    collection_guard_col=layout["collectionValue"].get("guardColumn", identity_col)
    rows=[]
    for offset,card in enumerate(catalogue):
        row=start+offset
        m=meta.get(card["cardId"])
        if m is None:
            raise CustomInventoryLayoutError("missing metadata: "+card["cardId"])
        enabled=list(m["inventoryVariants"])
        unknown=[v for v in enabled if v not in declared]
        if unknown:
            raise CustomInventoryLayoutError(f'{card["cardId"]}: unknown buckets {unknown}')
        quantityValues={bid:(0 if bid in enabled else None) for bid in buckets}
        rows.append({
            "row":row,
            "cardId":card["cardId"],
            "collectorNumber":str(card["number"]).zfill(3),
            "name":card["name"],
            "rarity":m["rarity"],
            "cardType":m["cardType"],
            "specialPattern":m.get("specialPattern"),
            "inventoryVariants":enabled,
            "quantityValues":quantityValues,
            "totalFormula":_sum_formula([b["quantityColumn"] for b in buckets.values()],row),
            "collectionValueFormula":_value_formula(list(buckets.values()),row,collection_guard_col),
        })
    if set(meta)!={c["cardId"] for c in catalogue}:
        raise CustomInventoryLayoutError("metadata/catalogue identity sets differ")
    end=start+len(rows)-1
    summaries=[]
    for s in layout["summaries"]:
        x=dict(s)
        x["formula"]=_summary_formula(s,buckets,start,end)
        summaries.append(x)
    return {
        "customInventorySheetPlanVersion":1,
        "layoutId":layout["layoutId"],
        "setId":layout["setId"],
        "sheetName":layout["sheetName"],
        "headerRow":layout["headerRow"],
        "startRow":start,
        "endRow":end,
        "freezeRows":layout["freezeRows"],
        "range":layout["range"],
        "columns":layout["columns"],
        "formatting":layout.get("formatting"),
        "inventoryBuckets":layout["inventoryBuckets"],
        "summaries":summaries,
        "rows":rows,
    }

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("catalogue")
    p.add_argument("metadata")
    p.add_argument("layout")
    p.add_argument("--output")
    a=p.parse_args()
    plan=build_custom_inventory_sheet_plan(a.catalogue,a.metadata,a.layout)
    text=json.dumps(plan,indent=2,ensure_ascii=False)+"\\n"
    if a.output:
        Path(a.output).write_text(text,encoding="utf-8")
    else:
        print(text,end="")
