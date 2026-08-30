from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import cv2
import numpy as np
import urllib.request
import threading
import time
import math


# =========================================================
# APP
# =========================================================

app = FastAPI(
    title="Pokemon Card Recognizer",
    version="3.0"
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

# First we cheaply narrow 244 cards down to 24.
SHORTLIST_SIZE = 24

# Then we perform geometric verification only on
# the strongest 8 candidates.
HOMOGRAPHY_CANDIDATES = 8

LOWE_RATIO = 0.73
MIN_GOOD_MATCHES = 8

THUMB_WIDTH = 72
THUMB_HEIGHT = 101


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
    nfeatures=1200,
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


def grayscale_thumbnail(image):

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY
    )

    gray = cv2.resize(
        gray,
        (
            THUMB_WIDTH,
            THUMB_HEIGHT
        ),
        interpolation=cv2.INTER_AREA
    )

    gray = cv2.equalizeHist(gray)

    return gray.astype(np.float32) / 255.0


def color_histogram(image):

    small = cv2.resize(
        image,
        (96, 134),
        interpolation=cv2.INTER_AREA
    )

    hsv = cv2.cvtColor(
        small,
        cv2.COLOR_BGR2HSV
    )

    hist = cv2.calcHist(
        [hsv],
        [0, 1],
        None,
        [18, 16],
        [0, 180, 0, 256]
    )

    cv2.normalize(
        hist,
        hist,
        alpha=0,
        beta=1,
        norm_type=cv2.NORM_MINMAX
    )

    return hist


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

    thumbnail = grayscale_thumbnail(image)

    histogram = color_histogram(image)

    keypoints, descriptors = calculate_sift(image)

    if descriptors is None:

        descriptors = np.empty(
            (0, 128),
            dtype=np.float32
        )

    return {
        "number": number,
        "image_url": IMAGE_URL.format(number),
        "thumbnail": thumbnail,
        "histogram": histogram,
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
            "Building Destined Rivals reference library..."
        )

        REFERENCE_CARDS.clear()

        for number in range(
            1,
            CARD_COUNT + 1
        ):

            try:

                REFERENCE_CARDS[number] = (
                    prepare_reference_card(number)
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
# FAST SHORTLIST
# =========================================================

def thumbnail_similarity(
    query_thumb,
    reference_thumb
):

    difference = np.mean(
        np.abs(
            query_thumb -
            reference_thumb
        )
    )

    return 1.0 - float(difference)


def histogram_similarity(
    query_hist,
    reference_hist
):

    score = cv2.compareHist(
        query_hist,
        reference_hist,
        cv2.HISTCMP_CORREL
    )

    if math.isnan(score):
        return 0.0

    return float(score)


def build_shortlist(image):

    query_thumb = grayscale_thumbnail(image)
    query_hist = color_histogram(image)

    scores = []

    for number, card in REFERENCE_CARDS.items():

        gray_score = thumbnail_similarity(
            query_thumb,
            card["thumbnail"]
        )

        color_score = histogram_similarity(
            query_hist,
            card["histogram"]
        )

        coarse_score = (
            gray_score * 0.40
            +
            color_score * 0.60
        )

        scores.append({
            "number": number,
            "coarse_score": coarse_score
        })

    scores.sort(
        key=lambda item: item["coarse_score"],
        reverse=True
    )

    return scores[:SHORTLIST_SIZE]


# =========================================================
# SIFT MATCHING
# =========================================================

def sift_match_score(
    query_descriptors,
    reference_descriptors
):

    if (
        query_descriptors is None
        or reference_descriptors is None
        or len(query_descriptors) < 2
        or len(reference_descriptors) < 2
    ):
        return []

    matches = matcher.knnMatch(
        query_descriptors,
        reference_descriptors,
        k=2
    )

    good = []

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

    return good


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

    image = normalize_card_image(image)

    # -----------------------------------------------------
    # STAGE 1
    # Fast comparison against all 244 cards.
    # -----------------------------------------------------

    shortlist_started = time.time()

    shortlist = build_shortlist(image)

    shortlist_time = (
        time.time() - shortlist_started
    )

    # -----------------------------------------------------
    # Calculate SIFT for the scanned card only once.
    # -----------------------------------------------------

    sift_started = time.time()

    query_keypoints, query_descriptors = (
        calculate_sift(image)
    )

    sift_extraction_time = (
        time.time() - sift_started
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
    # STAGE 2
    # SIFT only against the shortlist.
    # -----------------------------------------------------

    sift_results = []

    match_started = time.time()

    for candidate in shortlist:

        number = candidate["number"]

        reference = REFERENCE_CARDS[number]

        good_matches = sift_match_score(
            query_descriptors,
            reference["descriptors"]
        )

        sift_results.append({
            "number": number,
            "coarse_score": candidate["coarse_score"],
            "good_matches_list": good_matches,
            "good_matches": len(good_matches),
            "reference": reference
        })

    sift_results.sort(
        key=lambda item: item["good_matches"],
        reverse=True
    )

    sift_match_time = (
        time.time() - match_started
    )

    # -----------------------------------------------------
    # STAGE 3
    # Homography only against the strongest 8 candidates.
    # -----------------------------------------------------

    geometry_started = time.time()

    final_results = []

    for result in sift_results[
        :HOMOGRAPHY_CANDIDATES
    ]:

        geometry = geometric_verification(
            query_keypoints,
            result["reference"]["keypoints"],
            result["good_matches_list"]
        )

        good_matches = result["good_matches"]
        inliers = geometry["inliers"]
        inlier_ratio = geometry["inlier_ratio"]

        # Inliers matter most.
        # Ratio rewards geometrically consistent matches.
        # Good matches provide a smaller contribution.

        score = (
            inliers * 5.0
            +
            inlier_ratio * 200.0
            +
            good_matches * 0.30
        )

        final_results.append({
            "number": result["number"],

            "display_number":
                f'{result["number"]}/{DENOMINATOR}',

            "image":
                IMAGE_URL.format(
                    result["number"]
                ),

            "coarse_score":
                round(
                    result["coarse_score"],
                    4
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
        key=lambda item: item["score"],
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
        best["inliers"] >= 18
        and best["inlier_ratio"] >= 0.45
        and score_gap >= 20
    ):
        confident = True

    if (
        best["inliers"] >= 30
        and best["inlier_ratio"] >= 0.55
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

        "score_gap": round(
            score_gap,
            3
        ),

        "top_matches":
            final_results[:5],

        "timing": {
            "shortlist": round(
                shortlist_time,
                3
            ),

            "query_sift": round(
                sift_extraction_time,
                3
            ),

            "sift_matching": round(
                sift_match_time,
                3
            ),

            "geometry": round(
                geometry_time,
                3
            ),

            "total": round(
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
        "service": "Pokemon Card Recognizer",
        "version": "3.0",
        "set": SET_NAME,
        "library_ready": library_ready,
        "library_loading": library_loading,
        "cards_prepared": len(
            REFERENCE_CARDS
        ),
        "cards_expected": CARD_COUNT,
        "library_error": library_error
    }


@app.get("/health")
def health():

    return {
        "status":
            "ok"
            if library_ready
            else "loading",

        "library_ready": library_ready,

        "cards_prepared": len(
            REFERENCE_CARDS
        ),

        "cards_expected": CARD_COUNT,

        "error": library_error
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

        result = recognize_image(
            image
        )

        return result

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
