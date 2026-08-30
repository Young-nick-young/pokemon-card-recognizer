from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import cv2
import numpy as np
import urllib.request
import threading
import time


# =========================================================
# APP
# =========================================================

app = FastAPI(
    title="Pokemon Card Recognizer",
    version="4.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://young-nick-young.github.io"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# DESTINED RIVALS
# =========================================================

SET_CODE = "sv10"
SET_NAME = "Destined Rivals"
CARD_COUNT = 244
DENOMINATOR = 182

IMAGE_URL = (
    "https://images.pokemontcg.io/"
    + SET_CODE
    + "/{}.png"
)


# =========================================================
# RECOGNITION SETTINGS
# =========================================================

# Number of cards that receive full geometric verification.
GEOMETRY_CANDIDATES = 10

LOWE_RATIO = 0.74
MIN_GOOD_MATCHES = 8

# Limit features enough to remain usable on Render free CPU.
MAX_SIFT_FEATURES = 1000


# =========================================================
# GLOBAL STATE
# =========================================================

REFERENCE_CARDS = {}

library_ready = False
library_loading = False
library_error = None
library_started_at = None
library_finished_at = None

sift = cv2.SIFT_create(
    nfeatures=MAX_SIFT_FEATURES,
    contrastThreshold=0.03,
    edgeThreshold=10,
    sigma=1.6
)

matcher = cv2.BFMatcher(
    cv2.NORM_L2,
    crossCheck=False
)


# =========================================================
# IMAGE PREPARATION
# =========================================================

def normalize_card_image(image):

    if image is None:
        return None

    height, width = image.shape[:2]

    max_dimension = 900

    if max(height, width) > max_dimension:

        scale = max_dimension / max(height, width)

        image = cv2.resize(
            image,
            (
                int(width * scale),
                int(height * scale)
            ),
            interpolation=cv2.INTER_AREA
        )

    return image


def calculate_sift(image):

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY
    )

    keypoints, descriptors = sift.detectAndCompute(
        gray,
        None
    )

    return keypoints, descriptors


# =========================================================
# REFERENCE LIBRARY
# =========================================================

def download_card_image(number):

    url = IMAGE_URL.format(number)

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=20
    ) as response:

        data = response.read()

    array = np.frombuffer(
        data,
        np.uint8
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


def prepare_reference_card(number):

    image = download_card_image(number)

    image = normalize_card_image(image)

    keypoints, descriptors = calculate_sift(
        image
    )

    if descriptors is None:

        descriptors = np.empty(
            (0, 128),
            dtype=np.float32
        )

    return {
        "number": number,
        "image_url": IMAGE_URL.format(number),
        "keypoints": keypoints,
        "descriptors": descriptors
    }


def build_reference_library():

    global library_ready
    global library_loading
    global library_error
    global library_started_at
    global library_finished_at

    if library_loading:
        return

    library_loading = True
    library_ready = False
    library_error = None
    library_started_at = time.time()

    try:

        print(
            "Building Destined Rivals SIFT reference library..."
        )

        REFERENCE_CARDS.clear()

        for number in range(
            1,
            CARD_COUNT + 1
        ):

            try:

                REFERENCE_CARDS[number] = (
                    prepare_reference_card(
                        number
                    )
                )

                print(
                    f"Prepared {number}/{CARD_COUNT}"
                )

            except Exception as error:

                print(
                    f"Failed card #{number}: {error}"
                )

        if len(REFERENCE_CARDS) != CARD_COUNT:

            raise RuntimeError(
                "Reference library incomplete: "
                f"{len(REFERENCE_CARDS)}/{CARD_COUNT}"
            )

        library_finished_at = time.time()
        library_ready = True

        print(
            "Reference library ready:",
            len(REFERENCE_CARDS),
            "cards"
        )

    except Exception as error:

        library_error = str(error)

        print(
            "Library build failed:",
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

    start_library_build()


# =========================================================
# FAST SIFT RANKING
# =========================================================

def fast_sift_rank(
    query_descriptors,
    reference_descriptors
):

    if (
        query_descriptors is None
        or reference_descriptors is None
        or len(query_descriptors) < 2
        or len(reference_descriptors) < 2
    ):

        return {
            "good_matches": [],
            "count": 0,
            "quality": 0.0
        }

    matches = matcher.knnMatch(
        query_descriptors,
        reference_descriptors,
        k=2
    )

    good = []

    distance_total = 0.0

    for pair in matches:

        if len(pair) != 2:
            continue

        first, second = pair

        if (
            first.distance
            <
            LOWE_RATIO * second.distance
        ):

            good.append(first)
            distance_total += first.distance

    count = len(good)

    if count == 0:

        return {
            "good_matches": [],
            "count": 0,
            "quality": 0.0
        }

    average_distance = (
        distance_total / count
    )

    # Higher is better.
    # Strong match count dominates, while lower descriptor
    # distance gives a supporting bonus.
    quality = (
        count * 10.0
        +
        max(
            0.0,
            300.0 - average_distance
        )
    )

    return {
        "good_matches": good,
        "count": count,
        "quality": quality
    }


# =========================================================
# GEOMETRIC VERIFICATION
# =========================================================

def geometric_verification(
    query_keypoints,
    reference_keypoints,
    good_matches
):

    if len(good_matches) < MIN_GOOD_MATCHES:

        return {
            "inliers": 0,
            "inlier_ratio": 0.0
        }

    source_points = np.float32([
        query_keypoints[
            match.queryIdx
        ].pt
        for match in good_matches
    ]).reshape(
        -1,
        1,
        2
    )

    destination_points = np.float32([
        reference_keypoints[
            match.trainIdx
        ].pt
        for match in good_matches
    ]).reshape(
        -1,
        1,
        2
    )

    try:

        matrix, mask = cv2.findHomography(
            source_points,
            destination_points,
            cv2.RANSAC,
            5.0
        )

        if matrix is None or mask is None:

            return {
                "inliers": 0,
                "inlier_ratio": 0.0
            }

        inliers = int(
            mask.ravel().sum()
        )

        ratio = (
            inliers /
            len(good_matches)
        )

        return {
            "inliers": inliers,
            "inlier_ratio": float(ratio)
        }

    except cv2.error:

        return {
            "inliers": 0,
            "inlier_ratio": 0.0
        }


# =========================================================
# RECOGNITION
# =========================================================

def recognize_image(image):

    started = time.time()

    image = normalize_card_image(
        image
    )

    # -----------------------------------------------------
    # QUERY SIFT
    # -----------------------------------------------------

    query_started = time.time()

    query_keypoints, query_descriptors = (
        calculate_sift(image)
    )

    query_sift_time = (
        time.time() - query_started
    )

    if (
        query_descriptors is None
        or len(query_descriptors) < 8
    ):

        return {
            "status": "no_match",
            "reason": "Not enough image features",
            "top_matches": [],
            "processing_seconds": round(
                time.time() - started,
                3
            )
        }

    # -----------------------------------------------------
    # STAGE 1
    # SIFT ranking across ALL 244 cards.
    # No colour shortlist anymore.
    # -----------------------------------------------------

    ranking_started = time.time()

    ranked = []

    for number, reference in REFERENCE_CARDS.items():

        match_result = fast_sift_rank(
            query_descriptors,
            reference["descriptors"]
        )

        ranked.append({
            "number": number,
            "good_matches":
                match_result["count"],
            "quality":
                match_result["quality"],
            "good_matches_list":
                match_result["good_matches"],
            "reference":
                reference
        })

    ranked.sort(
        key=lambda item: (
            item["good_matches"],
            item["quality"]
        ),
        reverse=True
    )

    ranking_time = (
        time.time() - ranking_started
    )

    # -----------------------------------------------------
    # STAGE 2
    # Full geometry only on strongest candidates.
    # -----------------------------------------------------

    geometry_started = time.time()

    final_results = []

    for result in ranked[
        :GEOMETRY_CANDIDATES
    ]:

        geometry = geometric_verification(
            query_keypoints,
            result["reference"]["keypoints"],
            result["good_matches_list"]
        )

        good_matches = result["good_matches"]
        inliers = geometry["inliers"]
        inlier_ratio = geometry["inlier_ratio"]

        score = (
            inliers * 6.0
            +
            inlier_ratio * 220.0
            +
            good_matches * 0.25
        )

        final_results.append({
            "number":
                result["number"],

            "display_number":
                f'{result["number"]}/{DENOMINATOR}',

            "image":
                IMAGE_URL.format(
                    result["number"]
                ),

            "good_matches":
                good_matches,

            "inliers":
                inliers,

            "inlier_ratio":
                round(
                    inlier_ratio,
                    4
                ),

            "score":
                round(
                    score,
                    3
                )
        })

    geometry_time = (
        time.time() - geometry_started
    )

    final_results.sort(
        key=lambda item:
            item["score"],
        reverse=True
    )

    if not final_results:

        return {
            "status": "no_match",
            "top_matches": [],
            "processing_seconds": round(
                time.time() - started,
                3
            )
        }

    best = final_results[0]

    second = (
        final_results[1]
        if len(final_results) > 1
        else None
    )

    score_gap = (
        best["score"] - second["score"]
        if second
        else best["score"]
    )

    # -----------------------------------------------------
    # CONFIDENCE
    # -----------------------------------------------------

    confident = False

    if (
        best["inliers"] >= 16
        and
        best["inlier_ratio"] >= 0.42
        and
        score_gap >= 18
    ):
        confident = True

    if (
        best["inliers"] >= 28
        and
        best["inlier_ratio"] >= 0.50
    ):
        confident = True

    total_time = (
        time.time() - started
    )

    return {
        "status": "matched",

        "set": SET_NAME,

        "best_match": best,

        "confident": confident,

        "score_gap":
            round(
                score_gap,
                3
            ),

        "top_matches":
            final_results[:5],

        "timing": {
            "query_sift":
                round(
                    query_sift_time,
                    3
                ),

            "all_card_sift_ranking":
                round(
                    ranking_time,
                    3
                ),

            "geometry":
                round(
                    geometry_time,
                    3
                ),

            "total":
                round(
                    total_time,
                    3
                )
        }
    }


# =========================================================
# ROUTES
# =========================================================

@app.get("/")
def home():

    return {
        "status": "online",
        "service":
            "Pokemon Card Recognizer",
        "version": "4.0",
        "set": SET_NAME,
        "library_ready":
            library_ready,
        "library_loading":
            library_loading,
        "cards_prepared":
            len(
                REFERENCE_CARDS
            ),
        "cards_expected":
            CARD_COUNT,
        "library_error":
            library_error
    }


@app.get("/health")
def health():

    return {
        "status":
            "ok"
            if library_ready
            else "loading",

        "library_ready":
            library_ready,

        "cards_prepared":
            len(
                REFERENCE_CARDS
            ),

        "cards_expected":
            CARD_COUNT,

        "error":
            library_error
    }


@app.get("/library")
def library():

    return {
        "set": SET_NAME,
        "ready": library_ready,
        "loading": library_loading,
        "cards": len(
            REFERENCE_CARDS
        ),
        "expected": CARD_COUNT,
        "started_at": library_started_at,
        "finished_at": library_finished_at,
        "error": library_error
    }


@app.post("/recognize")
async def recognize(
    file: UploadFile = File(...)
):

    if not library_ready:

        raise HTTPException(
            status_code=503,
            detail=(
                "Reference card library "
                "is still loading."
            )
        )

    try:

        contents = await file.read()

        array = np.frombuffer(
            contents,
            np.uint8
        )

        image = cv2.imdecode(
            array,
            cv2.IMREAD_COLOR
        )

        if image is None:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Uploaded file is not "
                    "a valid image."
                )
            )

        return recognize_image(
            image
        )

    except HTTPException:
        raise

    except Exception as error:

        print(
            "Recognition error:",
            error
        )

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )
