#!/usr/bin/env python3
"""Build a deterministic Google Sheets inventory plan from Schema v1 + inventory metadata.

Inventory Sheet Automation v2 standardizes the modern bulk-inventory layout:
- rows 1:11 reserved for logo + summary boxes
- row 12 header, frozen
- rows 13+ card inventory
- 001 collector-number display
- blank + grey unavailable variant cells
- live summary formulas for total copies/value/Normal/Holo/Reverse Holo

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
COLUMN_WIDTHS = [80,108,180,110,120,120,113,118,116,100,101,99,100,100,100,100,96]
VARIANT_TO_COL = {"normal":"F","reverse-holo":"G","holo":"H","other":"I"}
VARIANT_TO_KEY = {"normal":"normalQty","reverse-holo":"reverseHoloQty","holo":"holoQty","other":"otherQty"}
MODERN_GREEN = {"red":0.20784314,"green":0.40784314,"blue":0.32941177}
WHITE = {"red":1,"green":1,"blue":1}
TEXT = {"red":0.2627451,"green":0.2627451,"blue":0.2627451}
UNAVAILABLE_GREY = {"red":0.8509804,"green":0.8509804,"blue":0.8509804}
ALT_GREY = {"red":0.9647059,"green":0.972549,"blue":0.9764706}

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
    if data.get("inventoryMetadataVersion") not in (1,2):
        raise InventoryPlanError("inventory_metadata.json must use inventoryMetadataVersion 1 or 2.")
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

def _summary_boxes(end_row):
    return [
        {"label":"Total Bulk Copies","labelRange":"F1:G2","valueRange":"F3:G3","formula":f"=SUM(J13:J{end_row})","numberFormat":"0"},
        {"label":"Total Bulk Value","labelRange":"F6:G7","valueRange":"F8:G8","formula":f"=SUM(O13:O{end_row})","numberFormat":"\"BHD \"0.000"},
        {"label":"Normal","labelRange":"I1:J2","valueRange":"I3:J3","formula":f"=SUM(F13:F{end_row})","numberFormat":"0"},
        {"label":"Holo","labelRange":"L1:M2","valueRange":"L3:M3","formula":f"=SUM(H13:H{end_row})","numberFormat":"0"},
        {"label":"Reverse Holo","labelRange":"O1:P2","valueRange":"O3:P3","formula":f"=SUM(G13:G{end_row})","numberFormat":"0"},
    ]

def build_inventory_sheet_plan(package_directory):
    package_dir=Path(package_directory)
    package=load_schema_v1_package(package_dir)
    manifest=package.manifest
    inv=manifest.get("inventory") or {}
    start_row=inv.get("startRow")
    if start_row != 13:
        raise InventoryPlanError(f"Inventory Sheet Automation v2 requires startRow 13; got {start_row!r}.")
    variant_ids=[v.get("variantId") for v in manifest.get("variants",[]) if isinstance(v,dict)]
    if variant_ids != ["normal","reverse-holo","holo","other"]:
        raise InventoryPlanError(
            "Inventory Sheet Automation v2 standard layout requires variants "
            "normal, reverse-holo, holo, other in that order. Special sets need an explicit custom layout."
        )
    metadata=_metadata_map(package_dir,package.set_id)
    cards=sorted(package.cards,key=lambda c:(c["number"]["sortKey"],c["cardId"]))
    if len(metadata)!=len(cards):
        raise InventoryPlanError(f"inventory metadata count {len(metadata)} != Schema card count {len(cards)}.")
    declared=set(variant_ids)
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
            "imageFormula": '=IMAGE(' + json.dumps(card["referenceImage"]) + ',4,90,65)',
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
    end_row=12+len(rows)
    return {
        "inventorySheetPlanVersion":2,
        "setId":package.set_id,
        "sheetName":inv.get("sheetName"),
        "headerRow":12,
        "startRow":13,
        "endRow":end_row,
        "freezeRows":12,
        "range":"A1:Q"+str(end_row),
        "logoRange":"A1:E10",
        "columns":_column_spec(),
        "rowHeights":{"topRows":{"start":1,"end":11,"pixelSize":21},"header":{"row":12,"pixelSize":42},"body":{"start":13,"end":end_row,"pixelSize":96}},
        "summaryBoxes":_summary_boxes(end_row),
        "summaryStyle":{
            "backgroundColor":WHITE,
            "foregroundColor":TEXT,
            "fontFamily":"Roboto",
            "labelFontSize":20,
            "valueFontSize":18,
            "valueBold":True,
            "horizontalAlignment":"CENTER",
            "verticalAlignment":"MIDDLE",
            "borderColor":{"red":0,"green":0,"blue":0},
        },
        "headerStyle":{
            "backgroundColor":MODERN_GREEN,
            "foregroundColor":WHITE,
            "fontFamily":"Roboto","fontSize":10,"bold":True,
            "horizontalAlignment":"CENTER","verticalAlignment":"MIDDLE","wrapStrategy":"WRAP",
        },
        "bodyStyle":{
            "foregroundColor":TEXT,
            "fontFamily":"Roboto","fontSize":10,"verticalAlignment":"MIDDLE",
            "oddRowColor":WHITE,"evenRowColor":ALT_GREY,
            "unavailableVariantColor":UNAVAILABLE_GREY,
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
        "Inventory Sheet Automation v2 — DRY RUN",
        f'Set: {plan["setId"]}',
        f'Planned production sheet name: {plan["sheetName"]}',
        f'Rows: {plan["startRow"]}–{plan["endRow"]} ({len(plan["rows"])} cards)',
        f'Header row: {plan["headerRow"]}; frozen rows: {plan["freezeRows"]}',
        "Write range: "+plan["range"],
        "Top layout: logo A1:E10 + five live summary boxes",
        "Unavailable quantity cells: blank + grey",
        "Unavailable counts: "+", ".join(f"{k}={v}" for k,v in unavailable.items()),
        "Card numbers display as 001/002/003 via number format 000",
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
