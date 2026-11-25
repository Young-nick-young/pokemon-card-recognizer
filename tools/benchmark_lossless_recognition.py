#!/usr/bin/env python3
"""Compare complete non-timing output against the accepted shared recognizer."""
import importlib.util
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from tools.benchmark_sift_parameters import card_images,samples
from tools.benchmark_sift_threads import build

BASELINE="a2708f79dc8d008ea62540edfb0450785827c0e4"
ROOT=Path(__file__).resolve().parents[1]

def run():
    cv2.setNumThreads(4)
    images=card_images()
    candidate=build(images)
    with tempfile.TemporaryDirectory() as d:
        path=Path(d)/"baseline.py"
        path.write_bytes(subprocess.check_output(["git","show",BASELINE+":schema_v1_recognizer_engine.py"],cwd=ROOT))
        spec=importlib.util.spec_from_file_location("accepted_engine",path)
        mod=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        baseline=mod.SchemaV1RecognizerEngine(set_id=candidate.set_id,set_name=candidate.set_name,card_count=candidate.card_count,library_file="",cards_by_number=candidate.cards_by_number)
        for field in ("reference_cards","global_descriptors","global_card_numbers","global_matcher","library_ready"):
            setattr(baseline,field,getattr(candidate,field))
        queries=samples(images)
        for i in range(0,len(images),11):
            q=cv2.GaussianBlur(images[i],(7,7),2)
            q[160:210,40:320]=255
            queries.append((i+1,q))
        rng=np.random.default_rng(42)
        queries.extend([(None,rng.integers(0,256,(483,360,3),dtype=np.uint8)),(None,np.zeros((483,360,3),np.uint8))])
        engines={"baseline":baseline,"candidate":candidate}
        times={k:[] for k in engines}; counts={k:0 for k in engines}
        for k,engine in engines.items():
            original=engine.geometric_verification
            def wrap(*args,_k=k,_orig=original,**kwargs):
                counts[_k]+=1
                return _orig(*args,**kwargs)
            engine.geometric_verification=wrap
            engine.recognize_image(queries[0][1])
            counts[k]=0
        mismatches=[]; correct=0; false_confident=0
        for rep in range(2):
            for i,(expected,img) in enumerate(queries):
                results={}
                order=list(engines) if (rep+i)%2==0 else list(reversed(engines))
                for k in order:
                    cv2.setRNGSeed(137)
                    t=time.perf_counter()
                    r=engines[k].recognize_image(img)
                    times[k].append(time.perf_counter()-t)
                    results[k]={a:b for a,b in r.items() if a!="timing"}
                if results["baseline"]!=results["candidate"]:
                    mismatches.append({"sample":i,"repeat":rep,"expected":expected})
                actual=results["baseline"].get("best_match",{}).get("number")
                correct+=int(actual==expected)
                false_confident+=int(results["baseline"].get("confident",False) and actual!=expected)
        print(json.dumps({"synthetic_only":True,"baseline_commit":BASELINE,"samples":len(times["baseline"]),"baseline_correct":correct,"baseline_false_confident":false_confident,"exact_non_timing_matches":len(times["baseline"])-len(mismatches),"mismatches":mismatches,"geometry_calls":counts,"median_ms":{k:round(statistics.median(v)*1000,3) for k,v in times.items()}},indent=2))
        if mismatches:
            raise RuntimeError("Candidate changed recognition output")
if __name__=="__main__":
    run()
