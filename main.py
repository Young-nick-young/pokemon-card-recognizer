from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import cv2
import numpy as np
import pickle
import os
import time
from collections import defaultdict


app = FastAPI(
    title="Pokemon Card Recognizer",
    version="6.0"
)
