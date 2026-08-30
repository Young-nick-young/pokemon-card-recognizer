from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import cv2
import numpy as np
import urllib.request
import threading
import time
from collections import defaultdict


# =========================================================
# APP
# =========================================================

app = FastAPI(
    title="Pokemon Card Recognizer",
    version="5.0"
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

GEOMETRY_CANDIDATES = 10

MAX_SIFT_FEATURES = 900

LOWE_RATIO = 0.78

MIN_GOOD_MATCHES = 8


# =========================================================
# GLOBAL STATE
# =========================================================

REFERENCE_CARDS = {}

GLOBAL_DESCRIPTORS = None
GLOBAL_CARD_NUMBERS = None

library_ready = False
library_loading = False
library_error = None
library_started_at = None
library_finished_at = None


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
# FLANN
# =========================================================

FLANN_INDEX_KDTREE = 1

index_params = dict(
    algorithm=FLANN_INDEX_KDTREE,
    trees=4
)

search_params = dict(
    checks=32
)

global_matcher = cv2.FlannBasedMatcher(
    index_params,
    search_params
)


# =========================================================
# IMAGE PREPARATION
# =========================================================

def normalize_card_image(image):

    if image is None:
        return None

    height, width = image.shape[:2]

    max_dimension = 800

    if max(height, width) > max_dimension:

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


def calculate_sift(image):

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

    if descriptors is not None:

        descriptors = descriptors.astype(
            np.float32
        )

    return keypoints, descriptors


# =========================================================
# DOWNLOAD REFERENCES
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
# PREPARE REFERENCE CARD
# =========================================================

def prepare_reference_card(number):

    image = download_card_image(
        number
    )

    image = normalize_card_image(
        image
    )

    keypoints, descriptors = (
        calculate_sift(
            image
        )
    )

    if descriptors is None:

        descriptors = np.empty(
            (0, 128),
            dtype=np.float32
        )

    return {
        "number": number,
        "image_url":
            IMAGE_URL.format(number),
        "keypoints": keypoints,
        "descriptors": descriptors
    }


# =========================================================
# BUILD GLOBAL INDEX
# =========================================================

def build_global_descriptor_index():

    global GLOBAL_DESCRIPTORS
    global GLOBAL_CARD_NUMBERS
    global global_matcher

    descriptor_blocks = []
    card_numbers = []

    for number in range(
        1,
        CARD_COUNT + 1
    ):

        card = REFERENCE_CARDS[
            number
        ]

        descriptors = card[
            "descriptors"
        ]

        if descriptors is None:
            continue

        if len(descriptors) == 0:
            continue

        descriptor_blocks.append(
            descriptors
        )

        card_numbers.extend(
            [number] *
            len(descriptors)
        )

    if not descriptor_blocks:

        raise RuntimeError(
            "No descriptors available "
            "for global index."
        )

    GLOBAL_DESCRIPTORS = (
        np.vstack(
            descriptor_blocks
        ).astype(
            np.float32
        )
    )

    GLOBAL_CARD_NUMBERS = (
        np.asarray(
            card_numbers,
            dtype=np.int32
        )
    )

    global_matcher = (
        cv2.FlannBasedMatcher(
            index_params,
            search_params
        )
    )

    global_matcher.add(
        [GLOBAL_DESCRIPTORS]
    )

    global_matcher.train()

    print(
        "Global descriptor index:",
        len(GLOBAL_DESCRIPTORS),
        "features"
    )


# =========================================================
# BUILD LIBRARY
# =========================================================

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

    library_started_at = (
        time.time()
    )

    try:

        print(
            "Building Destined Rivals "
            "reference library..."
        )

        REFERENCE_CARDS.clear()

        for number in range(
            1,
            CARD_COUNT + 1
        ):

            REFERENCE_CARDS[
                number
            ] = prepare_reference_card(
                number
            )

            print(
                f"Prepared "
                f"{number}/{CARD_COUNT}"
            )

        if (
            len(REFERENCE_CARDS)
            != CARD_COUNT
        ):

            raise RuntimeError(
                "Reference library "
                "incomplete."
            )

        print(
            "Building global "
            "SIFT search index..."
        )

        build_global_descriptor_index()

        library_finished_at = (
            time.time()
        )

        library_ready = True

        print(
            "Library ready:",
            CARD_COUNT,
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
# GLOBAL FEATURE VOTING
# =========================================================

def rank_cards_global(
    query_descriptors
):

    if (
        query_descriptors is None
        or
        len(query_descriptors) < 2
    ):

        return []

    matches = (
        global_matcher.knnMatch(
            query_descriptors,
            k=2
        )
    )

    votes = defaultdict(int)

    distance_scores = (
        defaultdict(float)
    )

    matched_query_indices = (
        defaultdict(list)
    )

    for pair in matches:

        if len(pair) < 2:
            continue

        first, second = pair

        if (
            first.distance
            >=
            LOWE_RATIO *
            second.distance
        ):
            continue

        train_index = (
            first.trainIdx
        )

        if (
            train_index < 0
            or
            train_index
            >= len(
                GLOBAL_CARD_NUMBERS
            )
        ):
            continue

        card_number = int(
            GLOBAL_CARD_NUMBERS[
                train_index
            ]
        )

        votes[
            card_number
        ] += 1

        distance_scores[
            card_number
        ] += first.distance

        matched_query_indices[
            card_number
        ].append(
            first.queryIdx
        )

    results = []

    for (
        number,
        vote_count
    ) in votes.items():

        avg_distance = (
            distance_scores[number]
            /
            vote_count
        )

        results.append({
            "number": number,
            "votes": vote_count,
            "avg_distance":
                avg_distance
        })

    results.sort(
        key=lambda item: (
            item["votes"],
            -item["avg_distance"]
        ),
        reverse=True
    )

    return results


# =========================================================
# PER-CARD MATCHING FOR GEOMETRY
# =========================================================

def get_card_matches(
    query_descriptors,
    reference_descriptors
):

    if (
        query_descriptors is None
        or
        reference_descriptors is None
        or
        len(query_descriptors) < 2
        or
        len(reference_descriptors) < 2
    ):

        return []

    matcher = cv2.BFMatcher(
        cv2.NORM_L2,
        crossCheck=False
    )

    pairs = matcher.knnMatch(
        query_descriptors,
        reference_descriptors,
        k=2
    )

    good = []

    for pair in pairs:

        if len(pair) < 2:
            continue

        first, second = pair

        if (
            first.distance
            <
            LOWE_RATIO *
            second.distance
        ):

            good.append(first)

    return good


# =========================================================
# GEOMETRIC VERIFICATION
# =========================================================

def geometric_verification(
    query_keypoints,
    reference_keypoints,
    good_matches
):

    if (
        len(good_matches)
        <
        MIN_GOOD_MATCHES
    ):

        return {
            "inliers": 0,
            "inlier_ratio": 0.0
        }

    source_points = np.float32([
        query_keypoints[
            match.queryIdx
        ].pt

        for match
        in good_matches
    ]).reshape(
        -1,
        1,
        2
    )

    destination_points = (
        np.float32([
            reference_keypoints[
                match.trainIdx
            ].pt

            for match
            in good_matches
        ])
        .reshape(
            -1,
            1,
            2
        )
    )

    try:

        matrix, mask = (
            cv2.findHomography(
                source_points,
                destination_points,
                cv2.RANSAC,
                5.0
            )
        )

        if (
            matrix is None
            or
            mask is None
        ):

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
            "inlier_ratio":
                float(ratio)
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
    # Query SIFT once
    # -----------------------------------------------------

    query_started = (
        time.time()
    )

    (
        query_keypoints,
        query_descriptors
    ) = calculate_sift(
        image
    )

    query_time = (
        time.time()
        -
        query_started
    )

    if (
        query_descriptors is None
        or
        len(query_descriptors) < 8
    ):

        return {
            "status": "no_match",
            "reason":
                "Not enough image features",
            "top_matches": [],
            "processing_seconds":
                round(
                    time.time()
                    -
                    started,
                    3
                )
        }

    # -----------------------------------------------------
    # Global SIFT index search
    # -----------------------------------------------------

    search_started = (
        time.time()
    )

    ranked = rank_cards_global(
        query_descriptors
    )

    global_search_time = (
        time.time()
        -
        search_started
    )

    if not ranked:

        return {
            "status": "no_match",
            "reason":
                "No feature matches",
            "top_matches": [],
            "processing_seconds":
                round(
                    time.time()
                    -
                    started,
                    3
                )
        }

    # -----------------------------------------------------
    # Geometric verification only on strongest cards
    # -----------------------------------------------------

    geometry_started = (
        time.time()
    )

    final_results = []

    for candidate in ranked[
        :GEOMETRY_CANDIDATES
    ]:

        number = candidate[
            "number"
        ]

        reference = (
            REFERENCE_CARDS[
                number
            ]
        )

        good_matches = (
            get_card_matches(
                query_descriptors,
                reference[
                    "descriptors"
                ]
            )
        )

        geometry = (
            geometric_verification(
                query_keypoints,
                reference[
                    "keypoints"
                ],
                good_matches
            )
        )

        inliers = (
            geometry[
                "inliers"
            ]
        )

        inlier_ratio = (
            geometry[
                "inlier_ratio"
            ]
        )

        good_count = len(
            good_matches
        )

        score = (
            inliers * 6.0
            +
            inlier_ratio * 220.0
            +
            good_count * 0.25
            +
            candidate["votes"] * 0.5
        )

        final_results.append({
            "number":
                number,

            "display_number":
                f"{number}/"
                f"{DENOMINATOR}",

            "image":
                IMAGE_URL.format(
                    number
                ),

            "global_votes":
                candidate[
                    "votes"
                ],

            "good_matches":
                good_count,

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
        time.time()
        -
        geometry_started
    )

    final_results.sort(
        key=lambda item:
            item["score"],
        reverse=True
    )

    if not final_results:

        return {
            "status": "no_match",
            "top_matches": []
        }

    best = (
        final_results[0]
    )

    second = (
        final_results[1]
        if
        len(final_results) > 1
        else
        None
    )

    score_gap = (
        best["score"]
        -
        second["score"]
        if second
        else
        best["score"]
    )

    # -----------------------------------------------------
    # Confidence
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
        time.time()
        -
        started
    )

    return {
        "status": "matched",

        "set": SET_NAME,

        "best_match":
            best,

        "confident":
            confident,

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
                    query_time,
                    3
                ),

            "global_search":
                round(
                    global_search_time,
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
        "status":
            "online",

        "service":
            "Pokemon Card Recognizer",

        "version":
            "5.0",

        "set":
            SET_NAME,

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

        "global_features":
            (
                len(
                    GLOBAL_DESCRIPTORS
                )
                if
                GLOBAL_DESCRIPTORS
                is not None
                else
                0
            ),

        "library_error":
            library_error
    }


@app.get("/health")
def health():

    return {
        "status":
            (
                "ok"
                if library_ready
                else
                "loading"
            ),

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
        "set":
            SET_NAME,

        "ready":
            library_ready,

        "loading":
            library_loading,

        "cards":
            len(
                REFERENCE_CARDS
            ),

        "expected":
            CARD_COUNT,

        "global_features":
            (
                len(
                    GLOBAL_DESCRIPTORS
                )
                if
                GLOBAL_DESCRIPTORS
                is not None
                else
                0
            ),

        "started_at":
            library_started_at,

        "finished_at":
            library_finished_at,

        "error":
            library_error
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

        contents = (
            await file.read()
        )

        array = np.frombuffer(
            contents,
            dtype=np.uint8
        )

        image = cv2.imdecode(
            array,
            cv2.IMREAD_COLOR
        )

        if image is None:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Uploaded file is "
                    "not a valid image."
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
