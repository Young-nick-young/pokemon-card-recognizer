"""Read-only public projection of the Chaos Rising Schema v1 package."""

from pathlib import Path

from schema_v1_loader import SchemaV1ValidationError, load_schema_v1_package

PACKAGE_DIRECTORY = Path(__file__).parent
EXPECTED_SET_ID = 'chaos-rising'

def build_public_package(package_directory=PACKAGE_DIRECTORY):
    package = load_schema_v1_package(package_directory)
    if package.set_id != EXPECTED_SET_ID:
        raise SchemaV1ValidationError(package_directory, [
            "manifest.setId: expected " + repr(EXPECTED_SET_ID) + ", found " + repr(package.set_id)
        ])
    manifest = package.manifest
    ordered_cards = sorted(package.cards, key=lambda card: (card["number"]["sortKey"], card["cardId"]))
    return {
        "schemaVersion": manifest["schemaVersion"],
        "setId": manifest["setId"],
        "displayName": manifest["displayName"],
        "language": manifest["language"],
        "variants": [{"variantId": value["variantId"], "label": value["label"]} for value in manifest["variants"]],
        "cards": [{
            "cardId": card["cardId"],
            "number": card["number"]["display"],
            "name": card["name"],
            "referenceImage": card["referenceImage"],
            "variants": list(card["variants"]),
        } for card in ordered_cards],
    }
