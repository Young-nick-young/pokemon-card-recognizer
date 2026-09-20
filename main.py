from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import cv2
import numpy as np
import gc
from pathlib import Path

from sets.destined_rivals import recognizer as destined_rivals
from sets.ascended_heroes import recognizer as ascended_heroes
from sets.perfect_order import recognizer as perfect_order
from sets.destined_rivals.public_package import (
    build_public_package as build_destined_rivals_public_package
)
from sets.perfect_order.public_package import (
    build_public_package as build_perfect_order_public_package
)

from sets.chaos_rising import recognizer as chaos_rising
from sets.chaos_rising.public_package import (
    build_public_package as build_chaos_rising_public_package
)


# =========================================================
# SCHEMA V1 SHADOW LOAD
# =========================================================

# Diagnostic only. Even an import or loader failure is
# contained so Schema v1 has no authority over service
# availability, routing or recognition behavior.
try:

    from schema_v1_loader import (
        load_schema_v1_packages_in_shadow
    )

    SCHEMA_V1_SHADOW_REPORT = (
        load_schema_v1_packages_in_shadow(
            Path(__file__).parent / "sets"
        )
    )

except Exception as error:

    SCHEMA_V1_SHADOW_REPORT = None

    print(
        "Schema v1 shadow loader unavailable:",
        error
    )


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
    "ascended-heroes": ascended_heroes,
    "perfect-order": perfect_order,
    "chaos-rising": chaos_rising
}


SET_ALIASES = {
    "destined-rivals": "destined-rivals",
    "destined_rivals": "destined-rivals",
    "dri": "destined-rivals",
    "sv10": "destined-rivals",

    "ascended-heroes": "ascended-heroes",
    "ascended_heroes": "ascended-heroes",
    "asc": "ascended-heroes",

    "perfect-order": "perfect-order",
    "perfect_order": "perfect-order",
    "por": "perfect-order",
    "me3": "perfect-order",
    "chaos-rising": "chaos-rising",
    "chaos_rising": "chaos-rising",
    "cri": "chaos-rising",
    "me4": "chaos-rising",
    "me04": "chaos-rising"
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

        # New Schema v1 wrappers expose their own unload hook so
        # internal shared-engine state and compatibility mirrors
        # are cleared together. Legacy recognizers keep the
        # established direct-state reset below.
        unload_hook = getattr(
            recognizer,
            "unload_library",
            None
        )

        if callable(unload_hook):

            unload_hook()

        else:

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
                ascended_heroes.get_status(),

            "perfect-order":
                perfect_order.get_status(),

            "chaos-rising":
                chaos_rising.get_status()
        }
    }


# =========================================================
# PUBLIC SET PACKAGE
# =========================================================

@app.get("/api/v1/sets/destined-rivals/package")
def destined_rivals_public_package():

    try:

        return build_destined_rivals_public_package()

    except Exception as error:

        print(
            "Destined Rivals public package unavailable:",
            error
        )

        raise HTTPException(
            status_code=503,
            detail={
                "error": "Public set package unavailable",
                "set": "destined-rivals"
            }
        ) from error


@app.get("/api/v1/sets/perfect-order/package")
def perfect_order_public_package():

    try:

        return build_perfect_order_public_package()

    except Exception as error:

        print(
            "Perfect Order public package unavailable:",
            error
        )

        raise HTTPException(
            status_code=503,
            detail={
                "error": "Public set package unavailable",
                "set": "perfect-order"
            }
        ) from error


@app.get("/api/v1/sets/chaos-rising/package")
def chaos_rising_public_package():
    try:
        return build_chaos_rising_public_package()
    except Exception as error:
        print("Chaos Rising public package unavailable:", error)
        raise HTTPException(status_code=503, detail={"error": "Public set package unavailable", "set": "chaos-rising"}) from error


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
