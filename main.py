from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import cv2
import numpy as np
import urllib.request
import threading
import time

app = FastAPI(
    title="Pokemon Card Recognizer",
    version="2.0"
)

# Allow the GitHub scanner app to use this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://young-nick-young.github.io"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# DESTINED RIVALS
# ---------------------------------------------------------

SET_CODE = "sv10"
SET_NAME = "Destined Rivals"
CARD_COUNT = 244

REFERENCE_CARDS = {}
library_ready = False
library_loading = False
library_error = None
library_started_at = None
library_finished_at = None

# SIFT works much better for matching card artwork than
# the simple browser colour/edge matcher we tested earlier.
sift = cv2.SIFT_create(
    nfeatures=1800,
    contrastThreshold=0.025,
    edgeThreshold=12,
    sigma=1.6
)

matcher = cv2.BFMatcher(cv2.NORM_L2)


def prepare_image(image):
    """
    Prepare an image for feature detection.
    """
    if image is None:
        return None

    height, width = image.shape[:2]

    # Keep enough detail for card text/artwork while avoiding
    # unnecessarily huge images.
    max_height = 800

    if height > max_height:
        scale = max_height / height
        image = cv2.resize(
            image,
            (
                int(width * scale),
                int(height * scale)
            ),
            interpolation=cv2.INTER_AREA
        )

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Slight contrast enhancement helps with phone-camera images.
    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8)
    )

    gray = clahe.apply(gray)

    return gray


def calculate_features(image):
    gray = prepare_image(image)

    if gray is None:
        return [], None

    keypoints, descriptors = sift.detectAndCompute(
        gray,
        None
    )

    return keypoints, descriptors


def download_card_image(number):
    url = (
        f"https://images.pokemontcg.io/"
        f"{SET_CODE}/{number}.png"
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "PokemonCardRecognizer/2.0"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=20
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

    return image


def build_reference_library():
    global library_ready
    global library_loading
    global library_error
    global library_started_at
    global library_finished_at

    if library_loading or library_ready:
        return

    library_loading = True
    library_error = None
    library_started_at = time.time()

    try:

        for number in range(1, CARD_COUNT + 1):

            try:
                image = download_card_image(number)

                if image is None:
                    print(
                        f"Could not decode card #{number}"
                    )
                    continue

                keypoints, descriptors = calculate_features(
                    image
                )

                if descriptors is None:
                    print(
                        f"No features found for card #{number}"
                    )
                    continue

                points = np.float32(
                    [kp.pt for kp in keypoints]
                )

                REFERENCE_CARDS[number] = {
                    "descriptors": descriptors,
                    "points": points
                }

                print(
                    f"Prepared {number}/{CARD_COUNT}"
                )

            except Exception as error:
                print(
                    f"Card #{number} failed: {error}"
                )

        if len(REFERENCE_CARDS) == 0:
            raise RuntimeError(
                "No reference cards could be prepared."
            )

        library_ready = True
        library_finished_at = time.time()

        print(
            f"Reference library ready: "
            f"{len(REFERENCE_CARDS)} cards"
        )

    except Exception as error:

        library_error = str(error)

        print(
            "Reference library failed:",
            error
        )

    finally:
        library_loading = False


def start_library_build():
    thread = threading.Thread(
        target=build_reference_library,
        daemon=True
    )

    thread.start()


@app.on_event("startup")
def startup_event():
    # Build once when the Render service starts.
    # It does NOT rebuild for every scan.
    start_library_build()


@app.get("/")
def home():
    return {
        "status": "online",
        "service": "Pokemon Card Recognizer",
        "version": "2.0",
        "set": SET_NAME,
        "library_ready": library_ready,
        "cards_prepared": len(REFERENCE_CARDS),
        "cards_expected": CARD_COUNT
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "opencv": cv2.__version__,
        "sift": True,
        "library_ready": library_ready,
        "library_loading": library_loading,
        "cards_prepared": len(REFERENCE_CARDS),
        "cards_expected": CARD_COUNT,
        "error": library_error
    }


@app.get("/library")
def library_status():

    elapsed = None

    if library_started_at is not None:

        end_time = (
            library_finished_at
            if library_finished_at is not None
            else time.time()
        )

        elapsed = round(
            end_time - library_started_at,
            1
        )

    return {
        "ready": library_ready,
        "loading": library_loading,
        "cards_prepared": len(REFERENCE_CARDS),
        "cards_expected": CARD_COUNT,
        "elapsed_seconds": elapsed,
        "error": library_error
    }


def compare_card(
    query_keypoints,
    query_descriptors,
    reference
):
    reference_descriptors = reference[
        "descriptors"
    ]

    reference_points = reference[
        "points"
    ]

    if (
        query_descriptors is None
        or reference_descriptors is None
    ):
        return None

    try:

        matches = matcher.knnMatch(
            query_descriptors,
            reference_descriptors,
            k=2
        )

    except cv2.error:
        return None

    good_matches = []

    for pair in matches:

        if len(pair) < 2:
            continue

        first, second = pair

        if first.distance < 0.72 * second.distance:
            good_matches.append(first)

    good_count = len(good_matches)

    if good_count < 6:
        return {
            "good_matches": good_count,
            "inliers": 0,
            "inlier_ratio": 0.0,
            "score": float(good_count)
        }

    query_points = np.float32([
        query_keypoints[
            match.queryIdx
        ].pt
        for match in good_matches
    ]).reshape(-1, 1, 2)

    matched_reference_points = np.float32([
        reference_points[
            match.trainIdx
        ]
        for match in good_matches
    ]).reshape(-1, 1, 2)

    inliers = 0
    inlier_ratio = 0.0

    if good_count >= 8:

        try:

            _, mask = cv2.findHomography(
                query_points,
                matched_reference_points,
                cv2.RANSAC,
                5.0
            )

            if mask is not None:

                inliers = int(
                    mask.ravel().sum()
                )

                inlier_ratio = (
                    inliers / good_count
                )

        except cv2.error:
            pass

    # Homography inliers are much more valuable than
    # raw feature matches because they confirm that the
    # matching features form the same physical card.
    score = (
        good_count
        + (inliers * 4.0)
        + (inlier_ratio * 20.0)
    )

    return {
        "good_matches": good_count,
        "inliers": inliers,
        "inlier_ratio": round(
            inlier_ratio,
            4
        ),
        "score": round(
            float(score),
            3
        )
    }


@app.post("/recognize")
async def recognize(
    file: UploadFile = File(...)
):

    if not library_ready:

        raise HTTPException(
            status_code=503,
            detail={
                "message":
                    "Card library is still preparing.",
                "cards_prepared":
                    len(REFERENCE_CARDS),
                "cards_expected":
                    CARD_COUNT
            }
        )

    try:

        contents = await file.read()

        image_array = np.frombuffer(
            contents,
            dtype=np.uint8
        )

        image = cv2.imdecode(
            image_array,
            cv2.IMREAD_COLOR
        )

        if image is None:

            raise HTTPException(
                status_code=400,
                detail="Could not read image."
            )

        query_keypoints, query_descriptors = (
            calculate_features(image)
        )

        if (
            query_descriptors is None
            or len(query_keypoints) < 8
        ):

            raise HTTPException(
                status_code=422,
                detail=(
                    "Not enough visual detail "
                    "was detected in the card."
                )
            )

        results = []

        for number, reference in (
            REFERENCE_CARDS.items()
        ):

            comparison = compare_card(
                query_keypoints,
                query_descriptors,
                reference
            )

            if comparison is None:
                continue

            results.append({
                "number": number,
                "display_number":
                    f"{number}/182",
                "image":
                    (
                        "https://images."
                        "pokemontcg.io/"
                        f"{SET_CODE}/"
                        f"{number}.png"
                    ),
                **comparison
            })

        results.sort(
            key=lambda item: item["score"],
            reverse=True
        )

        top_matches = results[:5]

        if len(top_matches) == 0:

            raise HTTPException(
                status_code=404,
                detail="No card match found."
            )

        best = top_matches[0]

        second_score = (
            top_matches[1]["score"]
            if len(top_matches) > 1
            else 0
        )

        score_gap = (
            best["score"] - second_score
        )

        # Confidence here is deliberately based on
        # match quality AND separation from #2.
        confident = (
            best["inliers"] >= 10
            and best["good_matches"] >= 14
            and score_gap >= 8
        )

        return {
            "status": "matched",
            "set": SET_NAME,
            "best_match": best,
            "confident": confident,
            "score_gap": round(
                score_gap,
                3
            ),
            "top_matches": top_matches
        }

    except HTTPException:
        raise

    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )
