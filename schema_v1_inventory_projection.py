"""Generic read-only inventory projection for Schema v1 sets.

Derives stable inventory rows and variant columns from a validated Schema v1
manifest. This module performs no Google Sheets or network writes.
"""
from __future__ import annotations
from pathlib import Path
from schema_v1_loader import SchemaV1ValidationError, load_schema_v1_package


def _fail(package_directory, issue):
    raise SchemaV1ValidationError(Path(package_directory), [issue])


def _prefixes(manifest):
    inventory = manifest.get("inventory", {})
    external_ids = manifest.get("externalIds", {})
    display_code = str(external_ids.get("displayCode") or "").strip()
    canonical = str(inventory.get("canonicalCardPrefix") or "").strip()
    legacy = str(inventory.get("legacyCardPrefix") or "").strip()
    if not canonical:
        if not display_code:
            raise ValueError("manifest.externalIds.displayCode is required to derive canonical IDs.")
        canonical = display_code.lower() + "-"
    if not legacy:
        if not display_code:
            raise ValueError("manifest.externalIds.displayCode is required to derive legacy IDs.")
        legacy = display_code.upper() + "-"
    return canonical, legacy


def build_inventory_projection(package_directory):
    package_directory = Path(package_directory)
    package = load_schema_v1_package(package_directory)
    manifest = package.manifest
    inventory = manifest.get("inventory", {})
    start_row = inventory.get("startRow")
    card_id_column = inventory.get("cardIdColumn")
    quantity_columns = inventory.get("quantityColumns", {})
    sheet_name = inventory.get("sheetName")
    if not isinstance(start_row, int) or isinstance(start_row, bool) or start_row < 1:
        _fail(package_directory, "manifest.inventory.startRow must be a positive integer.")
    if not isinstance(card_id_column, int) or isinstance(card_id_column, bool) or card_id_column < 1:
        _fail(package_directory, "manifest.inventory.cardIdColumn must be a positive integer.")
    if not isinstance(sheet_name, str) or not sheet_name.strip():
        _fail(package_directory, "manifest.inventory.sheetName is required.")
    variants = manifest.get("variants", [])
    variant_ids = [v.get("variantId") for v in variants]
    if len(variant_ids) != len(set(variant_ids)):
        _fail(package_directory, "manifest.variants contains duplicate variantId values.")
    inventory_keys = {v.get("variantId"): v.get("inventoryKey") for v in variants}
    variant_columns = {}
    for variant_id in variant_ids:
        column = quantity_columns.get(inventory_keys.get(variant_id))
        if not isinstance(column, int) or isinstance(column, bool) or column < 1:
            _fail(package_directory, "manifest.inventory.quantityColumns is missing a valid column for " + repr(variant_id) + ".")
        variant_columns[variant_id] = column
    if len(set(variant_columns.values())) != len(variant_columns):
        _fail(package_directory, "Inventory variant columns must be unique.")
    try:
        canonical_prefix, legacy_prefix = _prefixes(manifest)
    except ValueError as error:
        _fail(package_directory, str(error))
    ordered_cards = sorted(package.cards, key=lambda c: (c["number"]["sortKey"], c["cardId"]))
    expected_count = manifest.get("catalogue", {}).get("expectedRecords")
    if len(ordered_cards) != expected_count:
        _fail(package_directory, "catalogue record count does not match manifest.catalogue.expectedRecords.")
    rows, seen_ids, seen_legacy, seen_numbers = [], set(), set(), set()
    for index, card in enumerate(ordered_cards, start=1):
        sort_key = card["number"]["sortKey"]
        card_id = card["cardId"]
        legacy_id = card.get("externalIds", {}).get("legacyInventoryCardId")
        expected_card_id = canonical_prefix + str(sort_key).zfill(3)
        expected_legacy_id = legacy_prefix + str(sort_key).zfill(3)
        if sort_key in seen_numbers:
            _fail(package_directory, "duplicate collector sortKey " + str(sort_key) + ".")
        seen_numbers.add(sort_key)
        if sort_key != index:
            _fail(package_directory, "catalogue numbering must be contiguous 1 through " + str(expected_count) + ".")
        if card_id != expected_card_id:
            _fail(package_directory, "card " + repr(card_id) + " must use canonical cardId " + repr(expected_card_id) + ".")
        if legacy_id != expected_legacy_id:
            _fail(package_directory, "card " + repr(card_id) + " must use legacyInventoryCardId " + repr(expected_legacy_id) + ".")
        if card_id in seen_ids:
            _fail(package_directory, "duplicate canonical cardId " + repr(card_id) + ".")
        if legacy_id in seen_legacy:
            _fail(package_directory, "duplicate legacyInventoryCardId " + repr(legacy_id) + ".")
        seen_ids.add(card_id)
        seen_legacy.add(legacy_id)
        card_variants = list(card.get("variants", []))
        undeclared = [v for v in card_variants if v not in variant_columns]
        if undeclared:
            _fail(package_directory, "card " + repr(card_id) + " contains undeclared variants: " + ", ".join(undeclared) + ".")
        rows.append({
            "row": start_row + index - 1,
            "cardId": card_id,
            "legacyInventoryCardId": legacy_id,
            "collectorNumber": card["number"]["display"],
            "name": card["name"],
            "referenceImage": card["referenceImage"],
            "variantColumns": {v: variant_columns[v] for v in card_variants},
        })
    return {
        "setId": package.set_id,
        "sheetName": sheet_name,
        "startRow": start_row,
        "endRow": start_row + len(rows) - 1,
        "cardIdColumn": card_id_column,
        "variantColumns": variant_columns,
        "canonicalCardPrefix": canonical_prefix,
        "legacyCardPrefix": legacy_prefix,
        "cardCount": len(rows),
        "rows": rows,
    }
