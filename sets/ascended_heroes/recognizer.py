"""Ascended Heroes recognizer wrapper over the shared Schema v1 engine."""
import os
from schema_v1_recognizer_engine import SchemaV1RecognizerEngine
from sets.ascended_heroes.runtime_metadata import load_runtime_metadata

LIBRARY_FILE=os.path.join(os.path.dirname(__file__),"card_library.pkl")
RUNTIME_METADATA=None; RUNTIME_METADATA_ERROR=None; ENGINE=None
SET_ID="ascended-heroes"; SET_CODE="ASC"; SET_NAME="Ascended Heroes"; CARD_COUNT=295
REFERENCE_CARDS={}; GLOBAL_DESCRIPTORS=None; GLOBAL_CARD_NUMBERS=None; global_matcher=None
library_ready=False; library_error=None

def _sync_compatibility_state():
    global REFERENCE_CARDS,GLOBAL_DESCRIPTORS,GLOBAL_CARD_NUMBERS,global_matcher,library_ready,library_error
    if ENGINE is None:
        REFERENCE_CARDS={}; GLOBAL_DESCRIPTORS=None; GLOBAL_CARD_NUMBERS=None; global_matcher=None
        library_ready=False; library_error=RUNTIME_METADATA_ERROR; return
    REFERENCE_CARDS=ENGINE.reference_cards; GLOBAL_DESCRIPTORS=ENGINE.global_descriptors
    GLOBAL_CARD_NUMBERS=ENGINE.global_card_numbers; global_matcher=ENGINE.global_matcher
    library_ready=ENGINE.library_ready; library_error=ENGINE.library_error

def configure_runtime_metadata(package_directory=None):
    global SET_ID,SET_CODE,SET_NAME,CARD_COUNT,RUNTIME_METADATA,RUNTIME_METADATA_ERROR,ENGINE
    args={}
    if package_directory is not None: args["package_directory"]=package_directory
    try: metadata=load_runtime_metadata(**args)
    except Exception as error:
        RUNTIME_METADATA=None; RUNTIME_METADATA_ERROR=str(error); _sync_compatibility_state(); raise
    SET_ID=metadata.set_id; SET_CODE=metadata.set_code; SET_NAME=metadata.set_name; CARD_COUNT=metadata.card_count
    RUNTIME_METADATA=metadata; RUNTIME_METADATA_ERROR=None
    if ENGINE is None:
        ENGINE=SchemaV1RecognizerEngine(set_id=metadata.set_id,set_name=metadata.set_name,card_count=metadata.card_count,library_file=LIBRARY_FILE,cards_by_number=metadata.cards_by_number)
    else:
        ENGINE.configure_metadata(set_id=metadata.set_id,set_name=metadata.set_name,card_count=metadata.card_count,cards_by_number=metadata.cards_by_number)
    _sync_compatibility_state(); return metadata

def get_runtime_card_metadata(number):
    if RUNTIME_METADATA is None: raise RuntimeError("Ascended Heroes runtime metadata unavailable: "+str(RUNTIME_METADATA_ERROR))
    item=RUNTIME_METADATA.cards_by_number.get(number)
    if item is None: raise RuntimeError("Ascended Heroes runtime metadata has no collector number "+str(number)+".")
    return item

def load_library():
    if ENGINE is None: _sync_compatibility_state(); return
    ENGINE.load_library(); _sync_compatibility_state()

def unload_library():
    if ENGINE is not None: ENGINE.unload_library()
    _sync_compatibility_state()

def recognize_image(image):
    if ENGINE is None: return {"status":"error","reason":"Ascended Heroes library unavailable","library_error":RUNTIME_METADATA_ERROR,"top_matches":[]}
    result=ENGINE.recognize_image(image); _sync_compatibility_state(); return result

def get_status():
    if ENGINE is None: return {"set":SET_NAME,"set_id":SET_ID,"library_ready":False,"cards_prepared":0,"cards_expected":CARD_COUNT,"global_features":0,"library_error":RUNTIME_METADATA_ERROR}
    _sync_compatibility_state(); return ENGINE.get_status()

try: configure_runtime_metadata()
except Exception as error:
    RUNTIME_METADATA=None; RUNTIME_METADATA_ERROR=str(error); _sync_compatibility_state()
    print("Ascended Heroes runtime metadata load failed:",error)
