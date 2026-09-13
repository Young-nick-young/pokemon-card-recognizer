import cv2
import numpy as np
import urllib.request
import pickle
import time
import os
from dataclasses import dataclass
from pathlib import Path
import sys


REPOSITORY_ROOT = (
    Path(__file__).resolve().parents[2]
)

if str(REPOSITORY_ROOT) not in sys.path:

    sys.path.insert(
        0,
        str(REPOSITORY_ROOT)
    )

from schema_v1_loader import (
    load_schema_v1_package
)


PACKAGE_DIRECTORY = Path(__file__).resolve().parent

EXPECTED_SET_ID = "destined-rivals"

POKEMON_TCG_SET_ID_KEY = "pokemonTcgIo"
DISPLAY_CODE_KEY = "displayCode"
LEGACY_CARD_ID_KEY = "legacyInventoryCardId"

OUTPUT_FILE = os.path.join(
    os.path.dirname(__file__),
    "card_library.pkl"
)

# Reduced from 900.
# Still plenty for card recognition but much lighter in RAM.
MAX_SIFT_FEATURES = 500


sift = cv2.SIFT_create(
    nfeatures=MAX_SIFT_FEATURES,
    contrastThreshold=0.03,
    edgeThreshold=10,
    sigma=1.6
)


@dataclass(frozen=True)
class LibraryBuildCard:

    card_id: str
    legacy_card_id: str
    number: int
    name: str
    reference_image: str


@dataclass(frozen=True)
class LibraryBuildCatalogue:

    set_code: str
    cards: tuple

    @property
    def card_count(self):

        return len(self.cards)


def load_build_catalogue(
    package_directory=PACKAGE_DIRECTORY
):

    package = load_schema_v1_package(
        package_directory
    )

    if package.set_id != EXPECTED_SET_ID:

        raise RuntimeError(
            "Destined Rivals builder expected setId "
            + repr(EXPECTED_SET_ID)
            + ", found "
            + repr(package.set_id)
            + "."
        )

    manifest_external_ids = (
        package.manifest.get(
            "externalIds",
            {}
        )
    )

    set_code = manifest_external_ids.get(
        POKEMON_TCG_SET_ID_KEY
    )

    display_code = manifest_external_ids.get(
        DISPLAY_CODE_KEY
    )

    if not set_code:

        raise RuntimeError(
            "Destined Rivals manifest is missing externalIds."
            + POKEMON_TCG_SET_ID_KEY
            + "."
        )

    if not display_code:

        raise RuntimeError(
            "Destined Rivals manifest is missing externalIds."
            + DISPLAY_CODE_KEY
            + "."
        )

    cards = []

    for card_data in package.cards:

        number = card_data[
            "number"
        ][
            "sortKey"
        ]

        legacy_card_id = (
            card_data.get(
                "externalIds",
                {}
            ).get(
                LEGACY_CARD_ID_KEY
            )
        )

        expected_legacy_card_id = (
            display_code
            + "-"
            + str(number).zfill(3)
        )

        if (
            legacy_card_id
            != expected_legacy_card_id
        ):

            raise RuntimeError(
                "Destined Rivals card "
                + repr(card_data["cardId"])
                + " must provide externalIds."
                + LEGACY_CARD_ID_KEY
                + " as "
                + repr(expected_legacy_card_id)
                + ", found "
                + repr(legacy_card_id)
                + "."
            )

        cards.append(
            LibraryBuildCard(
                card_id=card_data[
                    "cardId"
                ],
                legacy_card_id=
                    legacy_card_id,
                number=number,
                name=card_data["name"],
                reference_image=
                    card_data[
                        "referenceImage"
                    ]
            )
        )

    numbers = [
        card.number
        for card in cards
    ]

    expected_numbers = list(
        range(
            1,
            len(cards) + 1
        )
    )

    if numbers != expected_numbers:

        raise RuntimeError(
            "Destined Rivals package order must remain "
            "collector numbers 1 through "
            + str(len(cards))
            + "."
        )

    return LibraryBuildCatalogue(
        set_code=set_code,
        cards=tuple(cards)
    )


def download_card(card):

    url = card.reference_image

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:

            data = response.read()

        image_array = np.asarray(
            bytearray(data),
            dtype=np.uint8
        )

        image = cv2.imdecode(
            image_array,
            cv2.IMREAD_COLOR
        )

        return image

    except Exception as error:

        print(
            "Failed to download card "
            + card.legacy_card_id
            + ":",
            error
        )

        return None


def prepare_image(image):

    if image is None:
        return None

    height, width = image.shape[:2]

    max_dimension = 700

    if max(height, width) > max_dimension:

        scale = (
            max_dimension
            /
            max(height, width)
        )

        image = cv2.resize(
            image,
            (
                int(width * scale),
                int(height * scale)
            ),
            interpolation=cv2.INTER_AREA
        )

    return image


def extract_features(image):

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY
    )

    keypoints, descriptors = (
        sift.detectAndCompute(
            gray,
            None
        )
    )

    if descriptors is None:
        return [], None

    descriptors = descriptors.astype(
        np.float32
    )

    keypoint_coordinates = np.array(
        [
            keypoint.pt
            for keypoint in keypoints
        ],
        dtype=np.float32
    )

    return (
        keypoint_coordinates,
        descriptors
    )


def build_library(
    package_directory=PACKAGE_DIRECTORY,
    output_file=OUTPUT_FILE
):

    catalogue = load_build_catalogue(
        package_directory
    )

    card_count = catalogue.card_count

    print(
        "Building Destined Rivals card library..."
    )

    print(
        "Cards expected:",
        card_count
    )

    cards = {}

    descriptor_blocks = []

    card_number_blocks = []

    descriptor_offset = 0

    started = time.time()

    successful_cards = 0

    total_features = 0

    for index, card in enumerate(
        catalogue.cards,
        start=1
    ):

        number = card.number

        print(
            f"[{index}/{card_count}] "
            "Downloading "
            + card.legacy_card_id
            + ": "
            + card.name
            + "..."
        )

        image = download_card(
            card
        )

        if image is None:

            print(
                f"Skipping card {number}: "
                f"download failed."
            )

            continue

        image = prepare_image(
            image
        )

        (
            keypoints,
            descriptors
        ) = extract_features(
            image
        )

        if (
            descriptors is None
            or
            len(descriptors) == 0
        ):

            print(
                f"Skipping card {number}: "
                f"no SIFT features."
            )

            continue

        descriptor_count = len(
            descriptors
        )

        descriptor_start = (
            descriptor_offset
        )

        descriptor_end = (
            descriptor_start
            +
            descriptor_count
        )

        cards[number] = {
            "number":
                number,

            "keypoints":
                keypoints,

            "descriptor_start":
                descriptor_start,

            "descriptor_end":
                descriptor_end
        }

        descriptor_blocks.append(
            descriptors
        )

        card_number_blocks.append(
            np.full(
                descriptor_count,
                number,
                dtype=np.uint16
            )
        )

        descriptor_offset = (
            descriptor_end
        )

        successful_cards += 1

        total_features += (
            descriptor_count
        )

        print(
            f"Card {number}: "
            f"{descriptor_count} features"
        )

    if not descriptor_blocks:

        raise RuntimeError(
            "No card descriptors were created."
        )

    global_descriptors = np.vstack(
        descriptor_blocks
    ).astype(
        np.float32,
        copy=False
    )

    global_card_numbers = np.concatenate(
        card_number_blocks
    ).astype(
        np.uint16,
        copy=False
    )

    library = {
        "set_code":
            catalogue.set_code,

        "card_count":
            card_count,

        "cards":
            cards,

        "global_descriptors":
            global_descriptors,

        "global_card_numbers":
            global_card_numbers
    }

    with open(
        output_file,
        "wb"
    ) as file:

        pickle.dump(
            library,
            file,
            protocol=pickle.HIGHEST_PROTOCOL
        )

    elapsed = (
        time.time()
        -
        started
    )

    descriptor_mb = (
        global_descriptors.nbytes
        /
        1024
        /
        1024
    )

    mapping_mb = (
        global_card_numbers.nbytes
        /
        1024
        /
        1024
    )

    print()
    print(
        "========================================"
    )
    print(
        "DESTINED RIVALS BUILD COMPLETE"
    )
    print(
        "========================================"
    )
    print(
        "Cards prepared:",
        successful_cards,
        "/",
        card_count
    )
    print(
        "Total SIFT features:",
        total_features
    )
    print(
        "Descriptor memory:",
        round(
            descriptor_mb,
            1
        ),
        "MB"
    )
    print(
        "Card mapping memory:",
        round(
            mapping_mb,
            2
        ),
        "MB"
    )
    print(
        "Output:",
        output_file
    )
    print(
        "Build time:",
        round(
            elapsed,
            1
        ),
        "seconds"
    )
    print(
        "========================================"
    )

    if successful_cards != card_count:

        raise RuntimeError(
            f"Library incomplete: "
            f"expected {card_count} cards, "
            f"prepared {successful_cards}."
        )


if __name__ == "__main__":
    build_library()
