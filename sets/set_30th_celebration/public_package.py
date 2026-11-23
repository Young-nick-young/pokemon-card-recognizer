"""Read-only public projection of the 30th Celebration Schema v1 package."""

import json
from pathlib import Path

from schema_v1_loader import SchemaV1ValidationError, load_schema_v1_package

PACKAGE_DIRECTORY = Path(__file__).parent
EXPECTED_SET_ID = "30th-celebration"


def _load_inventory_variants(package_directory):
    path = Path(package_directory) / "inventory_metadata.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    if data.get("setId") != EXPECTED_SET_ID:
        raise SchemaV1ValidationError(
            package_directory,
            [
                "inventory_metadata.setId: expected "
                + repr(EXPECTED_SET_ID)
                + ", found "
                + repr(data.get("setId"))
            ],
        )

    cards = data.get("cards")
    if not isinstance(cards, list):
        raise SchemaV1ValidationError(
            package_directory,
            ["inventory_metadata.cards must be an array"],
        )

    by_id = {}
    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            raise SchemaV1ValidationError(
                package_directory,
                [f"inventory_metadata.cards[{index}] must be an object"],
            )

        card_id = card.get("cardId")
        variants = card.get("inventoryVariants")

        if not isinstance(card_id, str) or not card_id:
            raise SchemaV1ValidationError(
                package_directory,
                [f"inventory_metadata.cards[{index}].cardId must be non-empty text"],
            )

        if not isinstance(variants, list) or not variants:
            raise SchemaV1ValidationError(
                package_directory,
                [f"inventory_metadata.cards[{index}].inventoryVariants must be a non-empty array"],
            )

        by_id[card_id] = list(variants)

    return by_id


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
            ],
        )

    inventory_variants = _load_inventory_variants(package_directory)

    manifest = package.manifest
    ordered_cards = sorted(
        package.cards,
        key=lambda card: (
            card["number"]["sortKey"],
            card["cardId"],
        ),
    )

    public_cards = []

    for card in ordered_cards:
        card_id = card["cardId"]

        if card_id not in inventory_variants:
            raise SchemaV1ValidationError(
                package_directory,
                [
                    "Missing explicit inventory variants for "
                    + repr(card_id)
                ],
            )

        public_cards.append(
            {
                "cardId": card_id,
                "number": {
                    "display": card["number"]["display"],
                    "sortKey": card["number"]["sortKey"],
                },
                "name": card["name"],
                "referenceImage": card["referenceImage"],
                "variants": inventory_variants[card_id],
            }
        )

    return {
        "schemaVersion": manifest["schemaVersion"],
        "setId": manifest["setId"],
        "displayName": manifest["displayName"],
        "language": manifest["language"],
        "variants": [
            {
                "variantId": value["variantId"],
                "label": value["label"],
                "inventoryKey": value.get(
                    "inventoryKey",
                    value["variantId"],
                ),
            }
            for value in manifest["variants"]
        ],
        "cards": public_cards,
    }
