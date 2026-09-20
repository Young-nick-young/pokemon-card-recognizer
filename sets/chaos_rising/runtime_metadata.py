"""Schema v1 runtime metadata for Chaos Rising."""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from schema_v1_loader import load_schema_v1_package

DEFAULT_PACKAGE_DIRECTORY = Path(__file__).resolve().parent
EXPECTED_SET_ID = 'chaos-rising'
EXPECTED_DISPLAY_CODE = 'CRI'
EXPECTED_DATASET_ID = 'me4'
LEGACY_CARD_ID_KEY = "legacyInventoryCardId"
CANONICAL_PREFIX = 'cri-'
LEGACY_PREFIX = 'CRI-'

@dataclass(frozen=True)
class RuntimeCardMetadata:
    number: int
    display_number: str
    reference_image: str
    card_id: Optional[str]
    legacy_card_id: Optional[str]
    name: Optional[str]

@dataclass(frozen=True)
class RuntimeMetadata:
    source: str
    set_id: str
    set_code: str
    set_name: str
    card_count: int
    cards_by_number: dict

def load_runtime_metadata(package_directory=DEFAULT_PACKAGE_DIRECTORY):
    package = load_schema_v1_package(package_directory)
    if package.set_id != EXPECTED_SET_ID:
        raise RuntimeError("Runtime expected setId " + repr(EXPECTED_SET_ID) + ", found " + repr(package.set_id) + ".")
    external_ids = package.manifest.get("externalIds", {})
    if external_ids.get("displayCode") != EXPECTED_DISPLAY_CODE:
        raise RuntimeError("manifest.externalIds.displayCode does not match runtime metadata.")
    if external_ids.get("pokemonTcgData") != EXPECTED_DATASET_ID:
        raise RuntimeError("manifest.externalIds.pokemonTcgData does not match runtime metadata.")
    cards_by_number = {}
    for card in package.cards:
        number = card["number"]["sortKey"]
        if number in cards_by_number:
            raise RuntimeError("Duplicate collector number " + str(number) + ".")
        expected_card_id = CANONICAL_PREFIX + str(number).zfill(3)
        expected_legacy_id = LEGACY_PREFIX + str(number).zfill(3)
        legacy_id = card.get("externalIds", {}).get(LEGACY_CARD_ID_KEY)
        if card["cardId"] != expected_card_id:
            raise RuntimeError("Collector number " + str(number) + " must use cardId " + repr(expected_card_id) + ".")
        if legacy_id != expected_legacy_id:
            raise RuntimeError("Card " + repr(card["cardId"]) + " must use legacyInventoryCardId " + repr(expected_legacy_id) + ".")
        cards_by_number[number] = RuntimeCardMetadata(number, card["number"]["display"], card["referenceImage"], card["cardId"], legacy_id, card["name"])
    expected_numbers = list(range(1, 122 + 1))
    if list(cards_by_number) != expected_numbers:
        raise RuntimeError("Schema v1 runtime metadata must remain ordered collector numbers 1 through 122.")
    return RuntimeMetadata("schema-v1", package.set_id, EXPECTED_DATASET_ID, package.manifest["displayName"], len(package.cards), cards_by_number)
