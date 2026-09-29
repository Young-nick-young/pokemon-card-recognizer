"""Read-only public projection of the Ascended Heroes Schema v1 package."""

import json
from pathlib import Path

from schema_v1_loader import SchemaV1ValidationError, load_schema_v1_package


PACKAGE_DIRECTORY = Path(__file__).parent
EXPECTED_SET_ID = "ascended-heroes"
INVENTORY_METADATA_FILENAME = "inventory_metadata.json"


def _load_display_metadata(package_directory):
    path = Path(package_directory) / INVENTORY_METADATA_FILENAME

    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    rows = payload.get("cards")
    if not isinstance(rows, list):
        raise SchemaV1ValidationError(
            package_directory,
            ["inventory_metadata.cards: expected a list"]
        )

    by_schema_id = {}

    for index, row in enumerate(rows):
        schema_card_id = row.get("schemaCardId")

        if not isinstance(schema_card_id, str) or not schema_card_id:
            raise SchemaV1ValidationError(
                package_directory,
                [
                    "inventory_metadata.cards["
                    + str(index)
                    + "].schemaCardId: expected a non-empty string"
                ]
            )

        if schema_card_id in by_schema_id:
            raise SchemaV1ValidationError(
                package_directory,
                [
                    "inventory_metadata.cards: duplicate schemaCardId "
                    + repr(schema_card_id)
                ]
            )

        by_schema_id[schema_card_id] = row

    return by_schema_id


def build_public_package(package_directory=PACKAGE_DIRECTORY):
    package = load_schema_v1_package(package_directory)

    if package.set_id != EXPECTED_SET_ID:
        raise SchemaV1ValidationError(
            package_directory,
            [
                "manifest.setId: expected "
                + repr(EXPECTED_SET_ID)
                + ", found "
                + repr(package.set_id)
            ]
        )

    manifest = package.manifest
    ordered_cards = sorted(
        package.cards,
        key=lambda card: (card["number"]["sortKey"], card["cardId"])
    )
    display_metadata = _load_display_metadata(package_directory)

    missing_metadata = [
        card["cardId"]
        for card in ordered_cards
        if card["cardId"] not in display_metadata
    ]

    extra_metadata = sorted(
        set(display_metadata) - {card["cardId"] for card in ordered_cards}
    )

    if missing_metadata or extra_metadata:
        issues = []

        if missing_metadata:
            issues.append(
                "inventory_metadata.cards: missing schemaCardId values "
                + repr(missing_metadata)
            )

        if extra_metadata:
            issues.append(
                "inventory_metadata.cards: unknown schemaCardId values "
                + repr(extra_metadata)
            )

        raise SchemaV1ValidationError(package_directory, issues)

    cards = []

    for card in ordered_cards:
        metadata = display_metadata[card["cardId"]]

        cards.append({
            "cardId": card["cardId"],
            "legacyInventoryCardId": card["externalIds"][
                "legacyInventoryCardId"
            ],
            "number": card["number"]["display"],
            "name": card["name"],
            "referenceImage": card["referenceImage"],
            "variants": list(card["variants"]),
            "rarity": metadata.get("rarity") or "",
            "type": metadata.get("cardType") or "",
            "specialPattern": metadata.get("specialPattern")
        })

    return {
        "schemaVersion": manifest["schemaVersion"],
        "setId": manifest["setId"],
        "displayName": manifest["displayName"],
        "language": manifest["language"],
        "variants": [
            {
                "variantId": variant["variantId"],
                "label": variant["label"]
            }
            for variant in manifest["variants"]
        ],
        "cards": cards
    }
