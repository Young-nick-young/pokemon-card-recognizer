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

def _normalize_catalogue(data):
    if isinstance(data, dict):
        cards=data.get("cards")
        if not isinstance(cards, list):
            raise CustomInventoryLayoutError("Schema catalogue must contain a cards array")
        out=[]
        for card in cards:
            external=card.get("externalIds") or {}
            legacy=external.get("legacyInventoryCardId")
            if not legacy:
                raise CustomInventoryLayoutError("Schema card missing legacyInventoryCardId: "+str(card.get("cardId")))
            out.append({
                "schemaCardId":card["cardId"],
                "cardId":legacy,
                "number":card["number"]["sortKey"],
                "name":card["name"],
                "referenceImage":card["referenceImage"],
                "variants":list(card["variants"]),
            })
        return out
    if isinstance(data, list):
        return [{
            "schemaCardId":card.get("schemaCardId"),
            "cardId":card["cardId"],
            "number":card["number"],
            "name":card["name"],
            "referenceImage":card.get("imageUrl"),
            "variants":None,
        } for card in data]
    raise CustomInventoryLayoutError("Unsupported catalogue shape")


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

def build_custom_inventory_sheet_plan(catalogue_path, metadata_path, layout_path, preservation_checkpoint_path=None):
    catalogue=_normalize_catalogue(_load(catalogue_path))
    metadata=_load(metadata_path)
    layout=_load(layout_path)
    checkpoint=_load(preservation_checkpoint_path) if preservation_checkpoint_path else None
    checkpoint_rows={}
    if checkpoint:
        checkpoint_rows={int(r["row"]):r for r in checkpoint.get("rows",[])}
    if layout.get("kind")!="custom-variable-width":
        raise CustomInventoryLayoutError("custom-variable-width layout required")
    if metadata.get("setId")!=layout.get("setId"):
        raise CustomInventoryLayoutError("metadata/layout setId mismatch")
    buckets=_bucket_map(layout)
    declared=set(buckets)
    cards=metadata.get("cards") or []
    if len(catalogue)!=len(cards):
        raise CustomInventoryLayoutError(f"catalogue count {len(catalogue)} != metadata count {len(cards)}")
    meta={}
    for c in cards:
        key=c.get("schemaCardId") or c["cardId"]
        if key in meta:
            raise CustomInventoryLayoutError("duplicate metadata identity: "+key)
        meta[key]=c
    start=int(layout["startRow"])
    identity_col=layout["identity"]["column"]
    collection_guard_col=layout["collectionValue"].get("guardColumn", identity_col)
    rows=[]
    for offset,card in enumerate(catalogue):
        row=start+offset
        source_key=card.get("schemaCardId") or card["cardId"]
        m=meta.get(source_key)
        if m is None:
            raise CustomInventoryLayoutError("missing metadata: "+source_key)
        if card.get("schemaCardId") and m.get("cardId") != card["cardId"]:
            raise CustomInventoryLayoutError("stable inventory identity mismatch: "+source_key)
        enabled=list(m["inventoryVariants"])
        unknown=[v for v in enabled if v not in declared]
        if unknown:
            raise CustomInventoryLayoutError(f'{card["cardId"]}: unknown buckets {unknown}')
        if card.get("variants") is not None:
            expected_schema={buckets[v].get("schemaVariantId",v) for v in enabled}
            actual_schema=set(card["variants"])
            if expected_schema != actual_schema:
                raise CustomInventoryLayoutError(
                    f'{card["cardId"]}: schema/custom variant mismatch '
                    f'{sorted(actual_schema)} != {sorted(expected_schema)}'
                )
        old=checkpoint_rows.get(row)
        if checkpoint and old is None:
            raise CustomInventoryLayoutError(f"checkpoint missing row {row}")
        if old and old.get("cardId")!=card["cardId"]:
            raise CustomInventoryLayoutError(f'checkpoint identity mismatch at row {row}: {old.get("cardId")} != {card["cardId"]}')
        quantityValues={}
        variantCells={}
        priceValues={}
        for bid,b in buckets.items():
            qcol=b["quantityColumn"]
            pcol=b["priceColumn"]
            available=bid in enabled
            if old:
                existing=old["quantities"].get(qcol)
                qvalue=(existing if existing is not None else 0) if available else None
            else:
                qvalue=0 if available else None
            quantityValues[bid]=qvalue
            variantCells[bid]={"quantityColumn":qcol,"available":available,"value":qvalue,"grey":not available}
            priceValues[bid]=old["prices"].get(pcol) if old else None
        rows.append({
            "row":row,
            "schemaCardId":card.get("schemaCardId"),
            "cardId":card["cardId"],
            "collectorNumber":str(card["number"]).zfill(3),
            "name":card["name"],
            "rarity":m["rarity"],
            "cardType":m["cardType"],
            "specialPattern":m.get("specialPattern"),
            "inventoryVariants":enabled,
            "quantityValues":quantityValues,
            "variantCells":variantCells,
            "priceValues":priceValues,
            "storage":old.get("storage") if old else None,
            "compatibilityCardId":old.get("cardId") if old else card["cardId"],
            "totalFormula":_sum_formula([b["quantityColumn"] for b in buckets.values()],row),
            "collectionValueFormula":_value_formula(list(buckets.values()),row,collection_guard_col),
        })
    source_keys={c.get("schemaCardId") or c["cardId"] for c in catalogue}
    if set(meta)!=source_keys:
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
    p.add_argument("--preservation-checkpoint")
    p.add_argument("--output")
    a=p.parse_args()
    plan=build_custom_inventory_sheet_plan(a.catalogue,a.metadata,a.layout,a.preservation_checkpoint)
    text=json.dumps(plan,indent=2,ensure_ascii=False)+"\\n"
    if a.output:
        Path(a.output).write_text(text,encoding="utf-8")
    else:
        print(text,end="")
