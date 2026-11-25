#!/usr/bin/env python3
"""Benchmark shared SIFT engine with local labelled phone photographs; no network or inventory."""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cv2
from sets.perfect_order import recognizer

def run(samples, repeats):
    recognizer.load_library()
    if not recognizer.library_ready:
        raise RuntimeError(recognizer.library_error)
    results=[]
    try:
        for sample in samples:
            image=cv2.imread(sample["path"])
            if image is None:
                raise ValueError("Unreadable image: "+sample["path"])
            for _ in range(repeats):
                start=time.perf_counter()
                result=recognizer.recognize_image(image)
                elapsed=time.perf_counter()-start
                best=result.get("best_match",{}).get("number")
                results.append({"path":sample["path"],"expected":sample["number"],"actual":best,"correct":best==sample["number"],"confident":result.get("confident",False),"seconds":elapsed,"timing":result.get("timing")})
        if not results:
            raise ValueError("No samples")
        return {"count":len(results),"correct":sum(x["correct"] for x in results),"false_confident":sum(x["confident"] and not x["correct"] for x in results),"median_seconds":statistics.median(x["seconds"] for x in results),"results":results}
    finally:
        recognizer.unload_library()

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("samples",type=Path)
    p.add_argument("--repeats",type=int,default=3)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    if a.repeats<1 or a.output.exists():
        p.error("Invalid repeat count or existing output")
    report=run(json.loads(a.samples.read_text()),a.repeats)
    with a.output.open("x") as f:
        json.dump(report,f,indent=2)
