#!/usr/bin/env python3
"""Compare OpenCV thread settings on deterministic synthetic cards using the actual shared engine.
This is a CPU microbenchmark, not evidence of phone-photo recognition accuracy.
"""
import json
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from schema_v1_recognizer_engine import SchemaV1RecognizerEngine

def synthetic_cards():
    rng=np.random.default_rng(137)
    images=[]
    for number in range(1,13):
        img=np.full((560,400,3),240,np.uint8)
        for _ in range(100):
            x,y=rng.integers([10,10],[390,550])
            color=tuple(int(c) for c in rng.integers(0,220,3))
            cv2.circle(img,(int(x),int(y)),int(rng.integers(4,20)),color,-1)
        cv2.putText(img,f"TEST {number:03}",(30,500),cv2.FONT_HERSHEY_SIMPLEX,1,(0,0,0),2)
        images.append(img)
    return images

def build(images):
    meta={i:SimpleNamespace(number=i,display_number=str(i),reference_image="synthetic") for i in range(1,len(images)+1)}
    engine=SchemaV1RecognizerEngine(set_id="synthetic",set_name="Synthetic",card_count=len(images),library_file="",cards_by_number=meta)
    arrays=[]; nums=[]; offset=0
    for i,img in enumerate(images,1):
        kp,desc=engine.calculate_sift(img)
        engine.reference_cards[i]={"descriptor_start":offset,"descriptor_end":offset+len(desc),"keypoints":[k.pt for k in kp]}
        arrays.append(desc); nums.extend([i]*len(desc)); offset+=len(desc)
    engine.global_descriptors=np.concatenate(arrays)
    engine.global_card_numbers=np.asarray(nums)
    cv2.setRNGSeed(137)
    engine.global_matcher=cv2.FlannBasedMatcher(engine.index_params,engine.search_params)
    engine.global_matcher.add([engine.global_descriptors])
    engine.global_matcher.train()
    engine.library_ready=True
    return engine

def run():
    original=cv2.getNumThreads()
    images=synthetic_cards()
    samples=[(i,cv2.warpAffine(img,cv2.getRotationMatrix2D((200,280),3,0.93),(400,560),borderValue=(225,225,225))) for i,img in enumerate(images,1)]
    try:
        cv2.setNumThreads(1)
        engine=build(images)
        results=[]
        for threads in dict.fromkeys([original,1,2]):
            cv2.setNumThreads(threads)
            for _,img in samples[:2]:
                engine.recognize_image(img)
            times=[]; signatures=[]
            for _ in range(3):
                for expected,img in samples:
                    cv2.setRNGSeed(137)
                    t=time.perf_counter()
                    result=engine.recognize_image(img)
                    times.append(time.perf_counter()-t)
                    signatures.append({"expected":expected,"best":result.get("best_match"),"confident":result.get("confident"),"top":result.get("top_matches")})
            correct=sum(x["best"] is not None and x["best"]["number"]==x["expected"] for x in signatures)
            results.append({"threads":threads,"samples":len(times),"correct":correct,"median_ms":round(statistics.median(times)*1000,3),"signatures":signatures})
        baseline=results[0]["signatures"]
        for r in results:
            r["exact_output_equivalence"]=r.pop("signatures")==baseline
        print(json.dumps({"synthetic_only":True,"baseline_threads":original,"results":results},indent=2))
        if results[0]["correct"]!=len(baseline):
            raise RuntimeError("Synthetic recognition baseline failed")
    finally:
        cv2.setNumThreads(original)

if __name__=="__main__":
    run()
