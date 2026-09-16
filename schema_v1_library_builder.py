"""Generic Schema v1 recognition-library builder.

The builder is deliberately set-agnostic. Set identity, package location,
record expectations and output location come from command-line arguments and
the validated Schema v1 package.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import pickle
import time
import urllib.request

import cv2
import numpy as np

from schema_v1_loader import load_schema_v1_package


MAX_SIFT_FEATURES = 500
MAX_IMAGE_DIMENSION = 700


@dataclass(frozen=True)
class LibraryBuildCard:
    card_id: str
    number: int
    name: str
    reference_image: str


@dataclass(frozen=True)
class LibraryBuildCatalogue:
    set_id: str
    set_code: str
    cards: tuple[LibraryBuildCard, ...]


def load_build_catalogue(
    package_directory: Path,
    expected_set_id: str,
    expected_records: int | None = None,
) -> LibraryBuildCatalogue:
    package = load_schema_v1_package(package_directory)

    if package.set_id != expected_set_id:
        raise RuntimeError(
            f"Builder expected setId {expected_set_id!r}, "
            f"found {package.set_id!r}."
        )

    manifest_expected = package.manifest.get("catalogue", {}).get(
        "expectedRecords"
    )
    resolved_expected = (
        expected_records if expected_records is not None else manifest_expected
    )

    if not isinstance(resolved_expected, int) or resolved_expected < 1:
        raise RuntimeError(
            "Expected record count must be supplied by --expected-records "
            "or manifest catalogue.expectedRecords."
        )

    if manifest_expected is not None and manifest_expected != resolved_expected:
        raise RuntimeError(
            "Command-line expected record count does not match the manifest."
        )

    if len(package.cards) != resolved_expected:
        raise RuntimeError(
            f"Package contains {len(package.cards)} cards; "
            f"expected {resolved_expected}."
        )

    external_ids = package.manifest.get("externalIds", {})
    set_code = external_ids.get("displayCode") or package.set_id
    cards: list[LibraryBuildCard] = []

    for card_data in package.cards:
        sort_key = card_data["number"]["sortKey"]
        if not isinstance(sort_key, int) or sort_key < 1:
            raise RuntimeError(
                f"Card {card_data['cardId']!r} has an invalid integer sortKey."
            )

        cards.append(
            LibraryBuildCard(
                card_id=card_data["cardId"],
                number=sort_key,
                name=card_data["name"],
                reference_image=card_data["referenceImage"],
            )
        )

    numbers = [card.number for card in cards]
    expected_numbers = list(range(1, resolved_expected + 1))
    if numbers != expected_numbers:
        raise RuntimeError(
            "Package order must be contiguous collector-number sort keys "
            f"1 through {resolved_expected}."
        )

    return LibraryBuildCatalogue(
        set_id=package.set_id,
        set_code=set_code,
        cards=tuple(cards),
    )


def download_card(card: LibraryBuildCard):
    request = urllib.request.Request(
        card.reference_image,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read()

    image_array = np.asarray(bytearray(data), dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Could not decode image for {card.card_id}.")
    return image


def prepare_image(image):
    height, width = image.shape[:2]
    if max(height, width) <= MAX_IMAGE_DIMENSION:
        return image

    scale = MAX_IMAGE_DIMENSION / max(height, width)
    return cv2.resize(
        image,
        (int(width * scale), int(height * scale)),
        interpolation=cv2.INTER_AREA,
    )


def extract_features(image, sift):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    keypoints, descriptors = sift.detectAndCompute(gray, None)
    if descriptors is None:
        return np.empty((0, 2), dtype=np.float32), None

    coordinates = np.asarray(
        [keypoint.pt for keypoint in keypoints], dtype=np.float32
    )
    return coordinates, descriptors.astype(np.float32)


def build_library(
    *,
    set_id: str,
    package_directory: Path,
    output_path: Path,
    expected_records: int | None = None,
) -> dict:
    catalogue = load_build_catalogue(
        package_directory=Path(package_directory),
        expected_set_id=set_id,
        expected_records=expected_records,
    )

    sift = cv2.SIFT_create(
        nfeatures=MAX_SIFT_FEATURES,
        contrastThreshold=0.03,
        edgeThreshold=10,
        sigma=1.6,
    )
    cards = {}
    descriptor_blocks = []
    card_number_blocks = []
    descriptor_offset = 0
    started = time.time()

    for index, card in enumerate(catalogue.cards, start=1):
        print(
            f"[{index}/{len(catalogue.cards)}] "
            f"Preparing {card.card_id}: {card.name}"
        )
        image = prepare_image(download_card(card))
        keypoints, descriptors = extract_features(image, sift)
        if descriptors is None or len(descriptors) == 0:
            raise RuntimeError(f"No SIFT features for {card.card_id}.")

        descriptor_end = descriptor_offset + len(descriptors)
        cards[card.number] = {
            "number": card.number,
            "keypoints": keypoints,
            "descriptor_start": descriptor_offset,
            "descriptor_end": descriptor_end,
        }
        descriptor_blocks.append(descriptors)
        card_number_blocks.append(
            np.full(len(descriptors), card.number, dtype=np.uint16)
        )
        descriptor_offset = descriptor_end

    library = {
        "set_code": catalogue.set_code,
        "card_count": len(catalogue.cards),
        "cards": cards,
        "global_descriptors": np.vstack(descriptor_blocks).astype(
            np.float32, copy=False
        ),
        "global_card_numbers": np.concatenate(card_number_blocks).astype(
            np.uint16, copy=False
        ),
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as output_file:
        pickle.dump(library, output_file, protocol=pickle.HIGHEST_PROTOCOL)

    print(
        f"Built {catalogue.set_id}: {library['card_count']} cards, "
        f"{len(library['global_descriptors'])} descriptors in "
        f"{time.time() - started:.1f}s -> {output_path}"
    )
    return library


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Build a recognition library from a Schema v1 package."
    )
    parser.add_argument("--set-id", required=True)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--expected-records", type=int)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    build_library(
        set_id=args.set_id,
        package_directory=args.package,
        expected_records=args.expected_records,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()

