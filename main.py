from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import cv2
import numpy as np
import pickle
import os
import time
from collections import defaultdict


# =========================================================
# APP
# =========================================================

app = FastAPI(
    title="Pokemon Card Recognizer",
    version="6.0"
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
# SETTINGS
# =========================================================

SET_CODE = "sv10"
SET_NAME = "Destined Rivals"
CARD_COUNT = 244
DENOMINATOR = 182

LIBRARY_FILE = "card_library.pkl"

IMAGE_URL = (
    "https://images.pokemontcg.io/"
    + SET_CODE
    + "/{}.png"
)

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
library_error = None


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

global_matcher = None


# =========================================================
# IMAGE FUNCTIONS
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
# LOAD PREBUILT LIBRARY
# =========================================================

def load_library():

    global REFERENCE_CARDS
    global GLOBAL_DESCRIPTORS
    global GLOBAL_CARD_NUMBERS
    global global_matcher
    global library_ready
    global library_error

    try:

        print("Loading prebuilt card library...")

        if not os.path.exists(
            LIBRARY_FILE
        ):

            raise RuntimeError(
                "card_library.pkl was not found. "
                "The Render build step must run "
                "build_library.py first."
            )

        with open(
            LIBRARY_FILE,
            "rb"
        ) as file:

            data = pickle.load(file)

        REFERENCE_CARDS = (
            data["cards"]
        )

        GLOBAL_DESCRIPTORS = (
            data["global_descriptors"]
            .astype(np.float32)
        )

        GLOBAL_CARD_NUMBERS = (
            data["global_card_numbers"]
            .astype(np.int32)
        )

        if (
            len(REFERENCE_CARDS)
            != CARD_COUNT
        ):

            raise RuntimeError(
                f"Expected {CARD_COUNT} cards, "
                f"found {len(REFERENCE_CARDS)}."
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

        library_ready = True
        library_error = None

        print(
            "Library ready:",
            len(REFERENCE_CARDS),
            "cards /",
            len(GLOBAL_DESCRIPTORS),
            "features"
        )

    except Exception as error:

        library_ready = False
        library_error = str(error)

        print(
            "Library load failed:",
            error
        )


@app.on_event("startup")
def startup_event():

    load_library()


# =========================================================
# GLOBAL SEARCH
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
    distances = defaultdict(float)

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
            train_index >=
            len(GLOBAL_CARD_NUMBERS)
        ):
            continue

        number = int(
            GLOBAL_CARD_NUMBERS[
                train_index
            ]
        )

        votes[number] += 1

        distances[number] += (
            first.distance
        )

    results = []

    for number, vote_count in (
        votes.items()
    ):

        average_distance = (
            distances[number]
            /
            vote_count
        )

        results.append({
            "number":
                number,

            "votes":
                vote_count,

            "avg_distance":
                average_distance
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
# PER-CARD MATCHING
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
    reference_keypoints_data,
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

    destination_points = np.float32([
        reference_keypoints_data[
            match.trainIdx
        ]

        for match
        in good_matches
    ]).reshape(
        -1,
        1,
        2
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
            "inliers":
                inliers,

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
    # QUERY SIFT
    # -----------------------------------------------------

    sift_started = time.time()

    (
        query_keypoints,
        query_descriptors
    ) = calculate_sift(
        image
    )

    query_sift_time = (
        time.time()
        -
        sift_started
    )

    if (
        query_descriptors is None
        or
        len(query_descriptors) < 8
    ):

        return {
            "status":
                "no_match",

            "reason":
                "Not enough image features",

            "top_matches":
                [],

            "timing": {
                "query_sift":
                    round(
                        query_sift_time,
                        3
                    ),

                "total":
                    round(
                        time.time()
                        -
                        started,
                        3
                    )
            }
        }

    # -----------------------------------------------------
    # GLOBAL SIFT SEARCH
    # -----------------------------------------------------

    search_started = time.time()

    ranked = rank_cards_global(
        query_descriptors
    )

    search_time = (
        time.time()
        -
        search_started
    )

    if not ranked:

        return {
            "status":
                "no_match",

            "reason":
                "No feature matches",

            "top_matches":
                [],

            "timing": {
                "query_sift":
                    round(
                        query_sift_time,
                        3
                    ),

                "global_search":
                    round(
                        search_time,
                        3
                    ),

                "total":
                    round(
                        time.time()
                        -
                        started,
                        3
                    )
            }
        }

    # -----------------------------------------------------
    # GEOMETRIC VERIFICATION
    # -----------------------------------------------------

    geometry_started = time.time()

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
                f"{number}/{DENOMINATOR}",

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
            "status":
                "no_match",

            "reason":
                "No verified candidates",

            "top_matches":
                []
        }

    # -----------------------------------------------------
    # BEST RESULT
    # -----------------------------------------------------

    best = final_results[0]

    second = (
        final_results[1]
        if len(final_results) > 1
        else None
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
        time.time()
        -
        started
    )

    return {
        "status":
            "matched",

        "set":
            SET_NAME,

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
                    query_sift_time,
                    3
                ),

            "global_search":
                round(
                    search_time,
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
            "6.0",

        "set":
            SET_NAME,

        "library_ready":
            library_ready,

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
                "error"
            ),

        "library_ready":
            library_ready,

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
                "Reference library "
                "is unavailable."
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
