import cv2
import numpy as np
import urllib.request
import json
import pickle
import time
import os


# =========================================================
# ASCENDED HEROES
# =========================================================

SET_ID = "ascended-heroes"
SET_CODE = "ASC"
SET_NAME = "Ascended Heroes"

CARD_COUNT = 295

OUTPUT_FILE = os.path.join(
    os.path.dirname(__file__),
    "card_library.pkl"
)

# Same recognition settings as the working
# Destined Rivals v6.1 recognizer.
MAX_SIFT_FEATURES = 500


# =========================================================
# ASCENDED HEROES CARD DATA
# =========================================================

# This is the working Ascended Heroes Google Apps Script API.
# It returns all 295 cards and their correct TCGplayer image URLs.

CARD_API_URL = (
    "https://script.google.com/macros/s/"
    "AKfycbxzaDPrnUX_a8P7UXxAQ-lWCCbJ9RG_kiXzvUfERWk41cCDhdY5yIr8S1PK9CAD10vv"
    "/exec?api=cards"
)


# =========================================================
# SIFT
# =========================================================

sift = cv2.SIFT_create(
    nfeatures=MAX_SIFT_FEATURES,
    contrastThreshold=0.03,
    edgeThreshold=10,
    sigma=1.6
)


# =========================================================
# DOWNLOAD CARD LIST
# =========================================================

def download_card_list():

    print("Downloading Ascended Heroes card list...")

    request = urllib.request.Request(
        CARD_API_URL,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=60
    ) as response:

        data = response.read()

    cards = json.loads(
        data.decode("utf-8")
    )

    if not isinstance(cards, list):

        raise RuntimeError(
            "Ascended Heroes API did not return a card list."
        )

    if len(cards) != CARD_COUNT:

        raise RuntimeError(
            f"Expected {CARD_COUNT} cards, "
            f"but API returned {len(cards)}."
        )

    print(
        "Cards received:",
        len(cards)
    )

    return cards


# =========================================================
# DOWNLOAD CARD IMAGE
# =========================================================

def download_card_image(card):

    number = int(card["number"])

    image_url = card.get(
        "imageUrl",
        ""
    )

    if not image_url:

        raise RuntimeError(
            f"No image URL for card #{number}"
        )

    request = urllib.request.Request(
        image_url,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:

        data = response.read()

    array = np.frombuffer(
        data,
        dtype=np.uint8
    )

    image = cv2.imdecode(
        array,
        cv2.IMREAD_COLOR
    )

    if image is None:

        raise RuntimeError(
            f"Could not decode card #{number}"
        )

    return image


# =========================================================
# NORMALIZE IMAGE
# =========================================================

def normalize(image):

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


# =========================================================
# PREPARE CARD
# =========================================================

def prepare_card(card):

    number = int(card["number"])

    name = card.get(
        "name",
        ""
    )

    print(
        f"Preparing card "
        f"{number}/{CARD_COUNT}: "
        f"{name}"
    )

    image = download_card_image(
        card
    )

    image = normalize(
        image
    )

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

        descriptors = np.empty(
            (0, 128),
            dtype=np.float32
        )

    else:

        descriptors = descriptors.astype(
            np.float32
        )

    keypoint_coordinates = np.float32([
        kp.pt
        for kp in keypoints
    ])

    return (
        keypoint_coordinates,
        descriptors
    )


# =========================================================
# BUILD LIBRARY
# =========================================================

def main():

    started = time.time()

    print(
        "================================"
    )

    print(
        "Building memory-optimized "
        "Ascended Heroes SIFT library"
    )

    print(
        "================================"
    )

    card_data = download_card_list()

    cards = {}

    descriptor_blocks = []

    card_number_blocks = []

    current_index = 0

    for card in card_data:

        number = int(
            card["number"]
        )

        (
            keypoints,
            descriptors
        ) = prepare_card(
            card
        )

        start_index = current_index

        end_index = (
            start_index
            +
            len(descriptors)
        )

        cards[number] = {

            "number":
                number,

            "card_id":
                card.get(
                    "cardId",
                    f"ASC-{number:03d}"
                ),

            "name":
                card.get(
                    "name",
                    ""
                ),

            "image_url":
                card.get(
                    "imageUrl",
                    ""
                ),

            "keypoints":
                keypoints,

            "descriptor_start":
                start_index,

            "descriptor_end":
                end_index
        }

        if len(descriptors) > 0:

            descriptor_blocks.append(
                descriptors
            )

            card_number_blocks.extend(
                [number]
                *
                len(descriptors)
            )

        current_index = end_index

    if not descriptor_blocks:

        raise RuntimeError(
            "No SIFT descriptors were generated."
        )

    global_descriptors = np.vstack(
        descriptor_blocks
    ).astype(
        np.float32
    )

    # uint16 easily supports all 295
    # Ascended Heroes card numbers.

    global_card_numbers = np.asarray(
        card_number_blocks,
        dtype=np.uint16
    )

    library = {

        "set_id":
            SET_ID,

        "set_code":
            SET_CODE,

        "set_name":
            SET_NAME,

        "card_count":
            CARD_COUNT,

        "cards":
            cards,

        "global_descriptors":
            global_descriptors,

        "global_card_numbers":
            global_card_numbers
    }

    print(
        "Saving Ascended Heroes library..."
    )

    with open(
        OUTPUT_FILE,
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

    size_mb = (
        global_descriptors.nbytes
        /
        1024
        /
        1024
    )

    print(
        "================================"
    )

    print(
        "BUILD COMPLETE"
    )

    print(
        "Set:",
        SET_NAME
    )

    print(
        "Cards:",
        len(cards)
    )

    print(
        "SIFT features:",
        len(global_descriptors)
    )

    print(
        "Descriptor memory:",
        round(
            size_mb,
            1
        ),
        "MB"
    )

    print(
        "File:",
        OUTPUT_FILE
    )

    print(
        "Time:",
        round(
            elapsed,
            1
        ),
        "seconds"
    )

    print(
        "================================"
    )


if __name__ == "__main__":

    main()
