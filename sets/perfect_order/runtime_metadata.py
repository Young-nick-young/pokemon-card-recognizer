"""Perfect Order Schema v1 runtime metadata.

Perfect Order has no legacy runtime path. Schema v1 is authoritative for this
isolated Gate A candidate.
"""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Optional

from schema_v1_loader import load_schema_v1_package


METADATA_SOURCE_ENVIRONMENT_VARIABLE = "POR_METADATA_SOURCE"
SCHEMA_V1_SOURCE = "schema-v1"
DEFAULT_PACKAGE_DIRECTORY = Path(__file__).resolve().parent
EXPECTED_SET_ID = "perfect-order"
EXPECTED_DISPLAY_CODE = "POR"
EXPECTED_DATASET_ID = "me3"
DISPLAY_CODE_KEY = "displayCode"
DATASET_ID_KEY = "pokemonTcgData"
LEGACY_CARD_ID_KEY = "legacyInventoryCardId"


@dataclass(frozen=True)
class RuntimeCardMetadata:
    number: int
    display_number: str
    reference_image: str
    card_id: Optional[str]
    legacy_card_id: Optional[str]
    name: Optional[str]


@dataclass(frozen=True)
class PerfectOrderRuntimeMetadata:
    source: str
    set_id: str
    set_code: str
    set_name: str
    card_count: int
    cards_by_number: dict


def _required_external_id(external_ids, key, path):
    value = external_ids.get(key)
    if not value:
        raise RuntimeError(path + "." + key + " is required for the Perfect Order runtime.")
    return value


def load_schema_v1_runtime_metadata(package_directory=DEFAULT_PACKAGE_DIRECTORY):
    package = load_schema_v1_package(package_directory)
    if package.set_id != EXPECTED_SET_ID:
        raise RuntimeError(
            "Perfect Order runtime expected setId " + repr(EXPECTED_SET_ID)
            + ", found " + repr(package.set_id) + "."
        )

    manifest = package.manifest
    external_ids = manifest.get("externalIds", {})
    display_code = _required_external_id(external_ids, DISPLAY_CODE_KEY, "manifest.externalIds")
    dataset_id = _required_external_id(external_ids, DATASET_ID_KEY, "manifest.externalIds")

    if display_code != EXPECTED_DISPLAY_CODE:
        raise RuntimeError(
            "Perfect Order runtime expected displayCode " + repr(EXPECTED_DISPLAY_CODE)
            + ", found " + repr(display_code) + "."
        )
    if dataset_id != EXPECTED_DATASET_ID:
        raise RuntimeError(
            "Perfect Order runtime expected pokemonTcgData " + repr(EXPECTED_DATASET_ID)
            + ", found " + repr(dataset_id) + "."
        )

    denominators = {
        namespace["namespaceId"]: namespace.get("denominator")
        for namespace in manifest["numberingNamespaces"]
    }
    cards_by_number = {}

    for card_data in package.cards:
        number_data = card_data["number"]
        number = number_data["sortKey"]
        denominator = denominators.get(number_data["namespaceId"])
        if not denominator:
            raise RuntimeError("Perfect Order card numbering namespace requires a denominator.")

        expected_card_id = "por-" + str(number).zfill(3)
        if card_data["cardId"] != expected_card_id:
            raise RuntimeError(
                "Perfect Order collector number " + str(number)
                + " must use canonical cardId " + repr(expected_card_id) + "."
            )

        legacy_card_id = _required_external_id(
            card_data.get("externalIds", {}),
            LEGACY_CARD_ID_KEY,
            "catalogue card " + repr(card_data["cardId"]) + " externalIds"
        )
        expected_legacy_card_id = "POR-" + str(number).zfill(3)
        if legacy_card_id != expected_legacy_card_id:
            raise RuntimeError(
                "Perfect Order card " + repr(card_data["cardId"])
                + " must use legacyInventoryCardId " + repr(expected_legacy_card_id) + "."
            )
        if number in cards_by_number:
            raise RuntimeError("Perfect Order runtime found duplicate collector number " + str(number) + ".")

        cards_by_number[number] = RuntimeCardMetadata(
            number=number,
            display_number=str(number) + "/" + denominator,
            reference_image=card_data["referenceImage"],
            card_id=card_data["cardId"],
            legacy_card_id=legacy_card_id,
            name=card_data["name"]
        )

    expected_numbers = list(range(1, 125))
    if list(cards_by_number) != expected_numbers:
        raise RuntimeError("Perfect Order Schema v1 runtime metadata must remain ordered collector numbers 1 through 124.")

    return PerfectOrderRuntimeMetadata(
        source=SCHEMA_V1_SOURCE,
        set_id=package.set_id,
        set_code=dataset_id,
        set_name=manifest["displayName"],
        card_count=len(package.cards),
        cards_by_number=cards_by_number
    )


def get_requested_metadata_source():
    return os.environ.get(METADATA_SOURCE_ENVIRONMENT_VARIABLE, SCHEMA_V1_SOURCE).strip().lower()


def load_runtime_metadata(source=None, package_directory=DEFAULT_PACKAGE_DIRECTORY):
    requested = get_requested_metadata_source() if source is None else str(source).strip().lower()
    if requested != SCHEMA_V1_SOURCE:
        raise RuntimeError("Perfect Order supports only the schema-v1 metadata source.")
    return load_schema_v1_runtime_metadata(package_directory)
