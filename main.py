import cv2
import numpy as np
import urllib.request
import pickle
import time


SET_CODE = "sv10"
CARD_COUNT = 244

IMAGE_URL = (
    "https://images.pokemontcg.io/"
    + SET_CODE
    + "/{}.png"
)

OUTPUT_FILE = "card_library.pkl"

MAX_SIFT_FEATURES = 900


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
            "User-Agent":
                "Mozilla/5.0"
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
            f"Could not decode "
            f"card #{number}"
        )

    return image


def normalize(image):

    height, width = (
        image.shape[:2]
    )

    max_dimension = 800

    if max(height, width) > (
        max_dimension
    ):

        scale = (
            max_dimension /
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


def prepare_card(number):

    print(
        f"Preparing card "
        f"{number}/{CARD_COUNT}..."
    )

    image = download_card(
        number
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

        descriptors = (
            descriptors.astype(
                np.float32
            )
        )

    keypoint_coordinates = (
        np.float32([
            kp.pt
            for kp
            in keypoints
        ])
    )

    return {
        "number":
            number,

        "keypoints":
            keypoint_coordinates,

        "descriptors":
            descriptors
    }


def main():

    started = time.time()

    print(
        "================================"
    )

    print(
        "Building Destined Rivals "
        "SIFT library"
    )

    print(
        "================================"
    )

    cards = {}

    descriptor_blocks = []
    card_number_blocks = []

    for number in range(
        1,
        CARD_COUNT + 1
    ):

        card = prepare_card(
            number
        )

        cards[number] = card

        descriptors = (
            card["descriptors"]
        )

        if len(descriptors) > 0:

            descriptor_blocks.append(
                descriptors
            )

            card_number_blocks.extend(
                [number] *
                len(descriptors)
            )

    global_descriptors = (
        np.vstack(
            descriptor_blocks
        ).astype(
            np.float32
        )
    )

    global_card_numbers = (
        np.asarray(
            card_number_blocks,
            dtype=np.int32
        )
    )

    library = {
        "cards":
            cards,

        "global_descriptors":
            global_descriptors,

        "global_card_numbers":
            global_card_numbers
    }

    print(
        "Saving library..."
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

    print(
        "================================"
    )

    print(
        "BUILD COMPLETE"
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
        "File:",
        OUTPUT_FILE
    )

    print(
        "Time:",
        round(elapsed, 1),
        "seconds"
    )

    print(
        "================================"
    )


if __name__ == "__main__":

    main()
