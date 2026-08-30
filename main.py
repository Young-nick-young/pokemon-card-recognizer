from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import cv2
import numpy as np

app = FastAPI(
    title="Pokemon Card Recognizer",
    version="1.0"
)

# Allow the GitHub scanner app to talk to this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://young-nick-young.github.io"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return {
        "status": "online",
        "service": "Pokemon Card Recognizer"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "opencv": cv2.__version__
    }


@app.post("/recognize")
async def recognize(file: UploadFile = File(...)):

    try:
        image_bytes = await file.read()

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
                detail="Could not read image."
            )

        height, width = image.shape[:2]

        return JSONResponse({
            "status": "received",
            "width": width,
            "height": height,
            "message": "Card image successfully received."
        })

    except HTTPException:
        raise

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error)
        )
