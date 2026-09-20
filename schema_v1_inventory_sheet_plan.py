#!/usr/bin/env python3
"""Build a deterministic Google Sheets inventory plan from Schema v1 + inventory metadata.

This module performs no Google API calls and no network writes.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from schema_v1_loader import load_schema_v1_package

HEADERS = [
    "Image","Card #","Card Name","Rarity","Card Type",
    "Normal","Reverse Holo","Holo","Other","Total",
    "Normal Price (BHD)","Reverse Price (BHD)","Holo Price (BHD)","Other Price (BHD)",
    "Collection Value (BHD)","Storage Location","Card ID",
]
COLUMN_KEYS = [
    "image","collectorNumber","name","rarity","cardType",
    "normalQty","reverseHoloQty","holoQty","otherQty","totalQty",
    "normalPriceBhd","reversePriceBhd","holoPriceBhd","otherPriceBhd",
    "collectionValueBhd","storageLocation","compatibilityCardId",
]
COLUMN_WIDTHS = [110,72,190,150,105,78,92,78,78,78,110,120,105,105,135,145,105]
VARIANT_TO_COL = {"normal":"F","reverse-holo":"G","holo":"H","other":"I"}
VARIANT_TO_KEY = {"normal":"normalQty","reverse-holo":"reverseHoloQty","holo":"holoQty","other":"otherQty"}

class InventoryPlanError(RuntimeError):
    pass

def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise InventoryPlanError(f"Unable to read {path}: {exc}") from exc

def _metadata_map(package_dir: Path, expected_set_id: str):
    path = package_dir / "inventory_metadata.json"
    data = _load_json(path)
    if data.get("inventoryMetadataVersion") != 1:
        raise InventoryPlanError("inventory_metadata.json must use inventoryMetadataVersion 1.")
    if data.get("setId") != expected_set_id:
        raise InventoryPlanError("inventory metadata setId does not match Schema v1.")
    rows = data.get("cards")
    if not isinstance(rows, list):
        raise InventoryPlanError("inventory metadata cards must be an array.")
    out = {}
    for entry in rows:
        if not isinstance(entry, dict):
            raise InventoryPlanError("inventory metadata entries must be objects.")
        card_id = entry.get("cardId")
        rarity = entry.get("rarity")
        card_type = entry.get("cardType")
        variants = entry.get("inventoryVariants")
        if not isinstance(card_id, str) or not card_id:
            raise InventoryPlanError("inventory metadata cardId is required.")
        if card_id in out:
            raise InventoryPlanError(f"duplicate inventory metadata cardId: {card_id}")
        if not isinstance(rarity, str) or not rarity.strip():
            raise InventoryPlanError(f"{card_id}: rarity is required.")
        if card_type is not None and not isinstance(card_type, str):
            raise InventoryPlanError(f"{card_id}: cardType must be text or null.")
        if not isinstance(variants, list) or not variants:
            raise InventoryPlanError(f"{card_id}: inventoryVariants must be a non-empty array.")
        if len(variants) != len(set(variants)):
            raise InventoryPlanError(f"{card_id}: inventoryVariants contains duplicates.")
        unknown = [v for v in variants if v not in VARIANT_TO_COL]
        if unknown:
            raise InventoryPlanError(f"{card_id}: unknown inventoryVariants: {unknown}")
        out[card_id] = {
            "rarity": rarity.strip(),
            "cardType": card_type.strip() if isinstance(card_type, str) and card_type.strip() else None,
            "inventoryVariants": variants,
        }
    return out

def _column_spec():
    cols=[]
    for idx,(key,header,width) in enumerate(zip(COLUMN_KEYS,HEADERS,COLUMN_WIDTHS), start=1):
        letter=chr(64+idx)
        number_format = None
        alignment = "LEFT"
        if letter == "B":
            number_format="000"; alignment="RIGHT"
        elif letter in ("F","G","H","I","J"):
            number_format="0"; alignment="RIGHT"
        elif letter in ("K","L","M","N","O"):
            number_format="0.000"; alignment="RIGHT"
        cols.append({"index":idx,"letter":letter,"key":key,"header":header,"widthPx":width,"alignment":alignment,"numberFormat":number_format})
    return cols

def build_inventory_sheet_plan(package_directory):
    package_dir=Path(package_directory)
    package=load_schema_v1_package(package_dir)
    manifest=package.manifest
    inv=manifest.get("inventory") or {}
    start_row=inv.get("startRow")
    if start_row != 13:
        raise InventoryPlanError(f"Inventory Sheet Automation v1 requires startRow 13; got {start_row!r}.")
    metadata=_metadata_map(package_dir,package.set_id)
    cards=sorted(package.cards,key=lambda c:(c["number"]["sortKey"],c["cardId"]))
    if len(metadata)!=len(cards):
        raise InventoryPlanError(f"inventory metadata count {len(metadata)} != Schema card count {len(cards)}.")
    declared={v.get("variantId") for v in manifest.get("variants",[]) if isinstance(v,dict)}
    rows=[]
    for offset,card in enumerate(cards):
        row=start_row+offset
        card_id=card["cardId"]
        m=metadata.get(card_id)
        if m is None:
            raise InventoryPlanError(f"missing inventory metadata for {card_id}.")
        if any(v not in declared for v in m["inventoryVariants"]):
            raise InventoryPlanError(f"{card_id}: inventory variant not declared by Schema manifest.")
        legacy=(card.get("externalIds") or {}).get("legacyInventoryCardId")
        if not isinstance(legacy,str) or not legacy:
            raise InventoryPlanError(f"{card_id}: legacyInventoryCardId is required.")
        sort_key=card["number"]["sortKey"]
        display=str(card["number"]["display"]).split("/",1)[0]
        values={
            "imageFormula": '=IMAGE(' + json.dumps(card["referenceImage"]) + ')',
            "collectorNumber": int(sort_key),
            "collectorDisplay": display,
            "name": card["name"],
            "rarity": m["rarity"],
            "cardType": m["cardType"],
            "normalQty": 0 if "normal" in m["inventoryVariants"] else None,
            "reverseHoloQty": 0 if "reverse-holo" in m["inventoryVariants"] else None,
            "holoQty": 0 if "holo" in m["inventoryVariants"] else None,
            "otherQty": 0 if "other" in m["inventoryVariants"] else None,
            "totalFormula": f"=SUM(F{row}:I{row})",
            "normalPriceBhd": None,
            "reversePriceBhd": None,
            "holoPriceBhd": None,
            "otherPriceBhd": None,
            "collectionValueFormula": f'=IF(B{row}="","",IFERROR((F{row}*K{row})+(G{row}*L{row})+(H{row}*M{row})+(I{row}*N{row}),0))',
            "storageLocation": None,
            "compatibilityCardId": legacy,
        }
        rows.append({
            "row": row,
            "canonicalCardId": card_id,
            "compatibilityCardId": legacy,
            "collectorNumber": display,
            "name": card["name"],
            "rarity": m["rarity"],
            "cardType": m["cardType"],
            "imageUrl": card["referenceImage"],
            "inventoryVariants": list(m["inventoryVariants"]),
            "values": values,
        })
    extra=sorted(set(metadata)-{c["cardId"] for c in cards})
    if extra:
        raise InventoryPlanError("inventory metadata contains unknown card IDs: "+", ".join(extra[:20]))
    return {
        "inventorySheetPlanVersion":1,
        "setId":package.set_id,
        "sheetName":inv.get("sheetName"),
        "headerRow":12,
        "startRow":13,
        "endRow":12+len(rows),
        "freezeRows":12,
        "range":"A12:Q"+str(12+len(rows)),
        "columns":_column_spec(),
        "headerStyle":{
            "backgroundColor":{"red":0.20784314,"green":0.40784314,"blue":0.32941177},
            "foregroundColor":{"red":1,"green":1,"blue":1},
            "fontFamily":"Roboto","fontSize":10,"bold":True,
            "horizontalAlignment":"CENTER","verticalAlignment":"MIDDLE","wrapStrategy":"WRAP",
        },
        "bodyStyle":{
            "foregroundColor":{"red":0.2627451,"green":0.2627451,"blue":0.2627451},
            "fontFamily":"Roboto","fontSize":10,"verticalAlignment":"MIDDLE",
        },
        "rows":rows,
    }

def dry_run_report(plan):
    unavailable={v:0 for v in VARIANT_TO_COL}
    for row in plan["rows"]:
        enabled=set(row["inventoryVariants"])
        for v in unavailable:
            if v not in enabled: unavailable[v]+=1
    lines=[
        "Inventory Sheet Automation v1 — DRY RUN",
        f'Set: {plan["setId"]}',
        f'Planned production sheet name: {plan["sheetName"]}',
        f'Rows: {plan["startRow"]}–{plan["endRow"]} ({len(plan["rows"])} cards)',
        f'Header row: {plan["headerRow"]}; frozen rows: {plan["freezeRows"]}',
        "Write range: "+plan["range"],
        "Unavailable quantity cells left blank: "+", ".join(f"{k}={v}" for k,v in unavailable.items()),
        "Price columns K:N: blank",
        "Storage column P: blank",
        "Identity: explicit collector numbers + compatibility IDs; no ROW()-based identity formulas",
        "Google writes: NONE",
    ]
    return "\n".join(lines)

def parse_args(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("package",type=Path)
    p.add_argument("--output",type=Path)
    p.add_argument("--dry-run",action="store_true")
    return p.parse_args(argv)

def main(argv=None):
    a=parse_args(argv)
    try:
        plan=build_inventory_sheet_plan(a.package)
        if a.output:
            a.output.parent.mkdir(parents=True,exist_ok=True)
            a.output.write_text(json.dumps(plan,indent=2)+"\n",encoding="utf-8")
            print("Wrote",a.output)
        if a.dry_run or not a.output:
            print(dry_run_report(plan))
        return 0
    except Exception as exc:
        print("FAIL:",exc,file=sys.stderr); return 1

if __name__=="__main__":
    raise SystemExit(main())
