from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import cv2
import numpy as np
import gc

from sets.destined_rivals import recognizer as destined_rivals
from sets.ascended_heroes import recognizer as ascended_heroes


# =========================================================
# APP
# =========================================================

app = FastAPI(
    title="Pokemon Card Recognizer",
    version="7.0"
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
# SET ROUTER
# =========================================================

RECOGNIZERS = {
    "destined-rivals": destined_rivals,
    "ascended-heroes": ascended_heroes
}


SET_ALIASES = {
    "destined-rivals": "destined-rivals",
    "destined_rivals": "destined-rivals",
    "dri": "destined-rivals",
    "sv10": "destined-rivals",

    "ascended-heroes": "ascended-heroes",
    "ascended_heroes": "ascended-heroes",
    "asc": "ascended-heroes"
}


active_set_id = None


# =========================================================
# SET HELPERS
# =========================================================

def normalize_set_id(set_id):

    if not set_id:
        return "destined-rivals"

    normalized = str(set_id).strip().lower()

    return SET_ALIASES.get(
        normalized,
        normalized
    )


def get_recognizer(set_id):

    normalized = normalize_set_id(
        set_id
    )

    recognizer = RECOGNIZERS.get(
        normalized
    )

    if recognizer is None:

        raise HTTPException(
            status_code=400,
            detail={
                "error": "Unknown set",
                "requested_set": set_id,
                "available_sets": list(
                    RECOGNIZERS.keys()
                )
            }
        )

    return (
        normalized,
        recognizer
    )


# =========================================================
# MEMORY MANAGEMENT
# =========================================================

def unload_recognizer(recognizer):

    try:

        recognizer.REFERENCE_CARDS = {}

        recognizer.GLOBAL_DESCRIPTORS = None

        recognizer.GLOBAL_CARD_NUMBERS = None

        recognizer.global_matcher = None

        recognizer.library_ready = False

        recognizer.library_error = None

        gc.collect()

    except Exception as error:

        print(
            "Recognizer unload warning:",
            error
        )


def activate_recognizer(
    set_id,
    recognizer
):

    global active_set_id

    # Already loaded and ready.
    if (
        active_set_id == set_id
        and
        recognizer.library_ready
    ):
        return

    # Remove the previous set from memory.
    if (
        active_set_id is not None
        and
        active_set_id != set_id
    ):

        previous = RECOGNIZERS.get(
            active_set_id
        )

        if previous is not None:

            print(
                "Unloading:",
                active_set_id
            )

            unload_recognizer(
                previous
            )

    # Load only the requested set.
    if not recognizer.library_ready:

        print(
            "Loading requested set:",
            set_id
        )

        recognizer.load_library()

    if not recognizer.library_ready:

        # Do not mark a failed library as active.
        active_set_id = None

        raise HTTPException(
            status_code=503,
            detail={
                "error": "Card library unavailable",
                "set": set_id,
                "library_error":
                    recognizer.library_error
            }
        )

    active_set_id = set_id

    print(
        "Active recognition set:",
        active_set_id
    )


# =========================================================
# IMAGE DECODING
# =========================================================

async def decode_upload(file):

    image_bytes = await file.read()

    if not image_bytes:

        raise HTTPException(
            status_code=400,
            detail="Uploaded image is empty."
        )

    image_array = np.frombuffer(
        image_bytes,
        dtype=np.uint8
    )

    image = cv2.imdecode(
        image_array,
        cv2.IMREAD_COLOR
    )

    if image is None:

        raise HTTPException(
            status_code=400,
            detail="Could not decode uploaded image."
        )

    return image


# =========================================================
# ROOT STATUS
# =========================================================

@app.get("/")
def root():

    return {
        "status": "online",
        "service": "Pokemon Card Recognizer",
        "version": "7.0",
        "architecture": "multi-set isolated",
        "active_set": active_set_id,
        "sets": {
            "destined-rivals":
                destined_rivals.get_status(),

            "ascended-heroes":
                ascended_heroes.get_status()
        }
    }


# =========================================================
# SET STATUS
# =========================================================

@app.get("/status/{set_id}")
def set_status(set_id: str):

    normalized, recognizer = (
        get_recognizer(
            set_id
        )
    )

    status = recognizer.get_status()

    status["requested_set"] = (
        normalized
    )

    status["currently_active"] = (
        active_set_id == normalized
    )

    return status


# =========================================================
# RECOGNIZE
# =========================================================

@app.post("/recognize")
async def recognize(
    file: UploadFile = File(...),
    set_id: str = Query(
        default="destined-rivals",
        alias="set"
    )
):

    normalized, recognizer = (
        get_recognizer(
            set_id
        )
    )

    activate_recognizer(
        normalized,
        recognizer
    )

    image = await decode_upload(
        file
    )

    try:

        result = recognizer.recognize_image(
            image
        )

    except Exception as error:

        print(
            "Recognition error:",
            normalized,
            error
        )

        raise HTTPException(
            status_code=500,
            detail={
                "error":
                    "Recognition failed",

                "set":
                    normalized,

                "message":
                    str(error)
            }
        )

    result["requested_set"] = (
        normalized
    )

    return result


# =========================================================
# SET-SPECIFIC RECOGNIZE ROUTE
# =========================================================

@app.post("/recognize/{set_id}")
async def recognize_set(
    set_id: str,
    file: UploadFile = File(...)
):

    normalized, recognizer = (
        get_recognizer(
            set_id
        )
    )

    activate_recognizer(
        normalized,
        recognizer
    )

    image = await decode_upload(
        file
    )

    try:

        result = recognizer.recognize_image(
            image
        )

    except Exception as error:

        print(
            "Recognition error:",
            normalized,
            error
        )

        raise HTTPException(
            status_code=500,
            detail={
                "error":
                    "Recognition failed",

                "set":
                    normalized,

                "message":
                    str(error)
            }
        )

    result["requested_set"] = (
        normalized
    )

    return result
