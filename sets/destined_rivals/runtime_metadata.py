"""Destined Rivals runtime metadata sources.

Schema v1 is authoritative by default. The explicit legacy source exists only
as the Milestone 4 rollback path and preserves the accepted v12 response data.
"""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Optional

from schema_v1_loader import load_schema_v1_package


METADATA_SOURCE_ENVIRONMENT_VARIABLE = (
    "DRI_METADATA_SOURCE"
)

SCHEMA_V1_SOURCE = "schema-v1"
LEGACY_SOURCE = "legacy"

DEFAULT_PACKAGE_DIRECTORY = Path(
    __file__
).resolve().parent

EXPECTED_SET_ID = "destined-rivals"
EXPECTED_DISPLAY_CODE = "DRI"

POKEMON_TCG_SET_ID_KEY = "pokemonTcgIo"
DISPLAY_CODE_KEY = "displayCode"
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
class DestinedRivalsRuntimeMetadata:

    source: str
    set_id: str
    set_code: str
    set_name: str
    card_count: int
    cards_by_number: dict


def _required_external_id(
    external_ids,
    key,
    path
):

    value = external_ids.get(key)

    if not value:

        raise RuntimeError(
            path
            + "."
            + key
            + " is required for the Destined Rivals runtime."
        )

    return value


def load_schema_v1_runtime_metadata(
    package_directory=DEFAULT_PACKAGE_DIRECTORY
):

    package = load_schema_v1_package(
        package_directory
    )

    if package.set_id != EXPECTED_SET_ID:

        raise RuntimeError(
            "Destined Rivals runtime expected setId "
            + repr(EXPECTED_SET_ID)
            + ", found "
            + repr(package.set_id)
            + "."
        )

    manifest = package.manifest

    manifest_external_ids = manifest.get(
        "externalIds",
        {}
    )

    set_code = _required_external_id(
        manifest_external_ids,
        POKEMON_TCG_SET_ID_KEY,
        "manifest.externalIds"
    )

    display_code = _required_external_id(
        manifest_external_ids,
        DISPLAY_CODE_KEY,
        "manifest.externalIds"
    )

    if display_code != EXPECTED_DISPLAY_CODE:

        raise RuntimeError(
            "Destined Rivals runtime expected displayCode "
            + repr(EXPECTED_DISPLAY_CODE)
            + ", found "
            + repr(display_code)
            + "."
        )

    denominators = {
        namespace["namespaceId"]:
            namespace.get("denominator")
        for namespace
        in manifest["numberingNamespaces"]
    }

    cards_by_number = {}

    for card_data in package.cards:

        number_data = card_data["number"]
        number = number_data["sortKey"]
        namespace_id = number_data["namespaceId"]
        denominator = denominators.get(namespace_id)

        if not denominator:

            raise RuntimeError(
                "Destined Rivals card "
                + repr(card_data["cardId"])
                + " requires a denominator for numbering namespace "
                + repr(namespace_id)
                + "."
            )

        expected_card_id = (
            "dri-"
            + str(number).zfill(3)
        )

        if card_data["cardId"] != expected_card_id:

            raise RuntimeError(
                "Destined Rivals collector number "
                + str(number)
                + " must use canonical cardId "
                + repr(expected_card_id)
                + ", found "
                + repr(card_data["cardId"])
                + "."
            )

        legacy_card_id = _required_external_id(
            card_data.get("externalIds", {}),
            LEGACY_CARD_ID_KEY,
            "catalogue card "
            + repr(card_data["cardId"])
            + " externalIds"
        )

        expected_legacy_card_id = (
            display_code
            + "-"
            + str(number).zfill(3)
        )

        if legacy_card_id != expected_legacy_card_id:

            raise RuntimeError(
                "Destined Rivals card "
                + repr(card_data["cardId"])
                + " must use legacyInventoryCardId "
                + repr(expected_legacy_card_id)
                + ", found "
                + repr(legacy_card_id)
                + "."
            )

        if number in cards_by_number:

            raise RuntimeError(
                "Destined Rivals runtime found duplicate collector "
                "number "
                + str(number)
                + "."
            )

        cards_by_number[number] = RuntimeCardMetadata(
            number=number,
            display_number=(
                str(number)
                + "/"
                + denominator
            ),
            reference_image=card_data["referenceImage"],
            card_id=card_data["cardId"],
            legacy_card_id=legacy_card_id,
            name=card_data["name"]
        )

    expected_numbers = list(
        range(
            1,
            len(package.cards) + 1
        )
    )

    if list(cards_by_number) != expected_numbers:

        raise RuntimeError(
            "Destined Rivals Schema v1 runtime metadata must remain "
            "ordered collector numbers 1 through "
            + str(len(package.cards))
            + "."
        )

    return DestinedRivalsRuntimeMetadata(
        source=SCHEMA_V1_SOURCE,
        set_id=package.set_id,
        set_code=set_code,
        set_name=manifest["displayName"],
        card_count=len(package.cards),
        cards_by_number=cards_by_number
    )


def load_legacy_runtime_metadata():
    """Reproduce the accepted Milestone 3 DRI response metadata."""

    set_code = "sv10"
    denominator = 182
    card_count = 244

    cards_by_number = {
        number: RuntimeCardMetadata(
            number=number,
            display_number=(
                str(number)
                + "/"
                + str(denominator)
            ),
            reference_image=(
                "https://images.pokemontcg.io/"
                + set_code
                + "/"
                + str(number)
                + ".png"
            ),
            card_id=None,
            legacy_card_id=None,
            name=None
        )
        for number in range(1, card_count + 1)
    }

    return DestinedRivalsRuntimeMetadata(
        source=LEGACY_SOURCE,
        set_id=EXPECTED_SET_ID,
        set_code=set_code,
        set_name="Destined Rivals",
        card_count=card_count,
        cards_by_number=cards_by_number
    )


def get_requested_metadata_source():

    return os.environ.get(
        METADATA_SOURCE_ENVIRONMENT_VARIABLE,
        SCHEMA_V1_SOURCE
    ).strip().lower()


def load_runtime_metadata(
    source=None,
    package_directory=DEFAULT_PACKAGE_DIRECTORY
):

    if source is None:

        source = get_requested_metadata_source()

    normalized_source = str(source).strip().lower()

    if normalized_source == SCHEMA_V1_SOURCE:

        return load_schema_v1_runtime_metadata(
            package_directory
        )

    if normalized_source == LEGACY_SOURCE:

        return load_legacy_runtime_metadata()

    raise RuntimeError(
        "Unsupported Destined Rivals metadata source "
        + repr(source)
        + ". Expected 'schema-v1' or 'legacy'."
    )
