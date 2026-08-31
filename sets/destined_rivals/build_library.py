import cv2
import numpy as np
import urllib.request
import pickle
import time
import os


SET_CODE = "sv10"
CARD_COUNT = 244

IMAGE_URL = (
    "https://images.pokemontcg.io/"
    + SET_CODE
    + "/{}.png"
)

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


def download_card(number):

    url = IMAGE_URL.format(number)

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
            f"Failed to download card {number}:",
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


def build_library():

    print(
        "Building Destined Rivals card library..."
    )

    print(
        "Cards expected:",
        CARD_COUNT
    )

    cards = {}

    descriptor_blocks = []

    card_number_blocks = []

    descriptor_offset = 0

    started = time.time()

    successful_cards = 0

    total_features = 0

    for number in range(
        1,
        CARD_COUNT + 1
    ):

        print(
            f"[{number}/{CARD_COUNT}] "
            f"Downloading card {number}..."
        )

        image = download_card(
            number
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
            SET_CODE,

        "card_count":
            CARD_COUNT,

        "cards":
            cards,

        "global_descriptors":
            global_descriptors,

        "global_card_numbers":
            global_card_numbers
    }

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
        CARD_COUNT
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
        OUTPUT_FILE
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

    if successful_cards != CARD_COUNT:

        raise RuntimeError(
            f"Library incomplete: "
            f"expected {CARD_COUNT} cards, "
            f"prepared {successful_cards}."
        )


if __name__ == "__main__":
    build_library()
