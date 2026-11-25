#!/usr/bin/env python3
"""Benchmark candidate SIFT settings on generated card-like images.
No copyrighted images, network requests, or production modifications.
Synthetic results do not qualify a setting for promotion.
"""
import json
import statistics
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from tools.benchmark_sift_threads import build

def card_images(count=124):
    rng=np.random.default_rng(20261125)
    families=[]
    for f in range(31):
        img=np.full((483,360,3),232,np.uint8)
        cv2.rectangle(img,(8,8),(351,474),(40,175,230),5)
        cv2.putText(img,f"FAMILY {f:02}",(20,40),cv2.FONT_HERSHEY_SIMPLEX,.85,(20,20,20),2)
        for _ in range(65):
            x,y=rng.integers([28,60],[330,300])
            c=tuple(map(int,rng.integers(10,220,3)))
            cv2.circle(img,(int(x),int(y)),int(rng.integers(4,16)),c,-1)
        for y in (335,360,385,410):
            cv2.putText(img,"SYNTHETIC CARD TEXT",(23,y),cv2.FONT_HERSHEY_SIMPLEX,.54,(35,35,35),1)
        families.append(img)
    images=[]
    for i in range(count):
        img=families[i//4].copy()
        for _ in range(12):
            x,y=rng.integers([30,65],[330,300])
            cv2.rectangle(img,(int(x),int(y)),(int(x)+10,int(y)+10),tuple(map(int,rng.integers(0,255,3))),-1)
        cv2.putText(img,f"{i+1:03}/124",(18,455),cv2.FONT_HERSHEY_SIMPLEX,.72,(15,15,15),2)
        images.append(img)
    return images

def samples(images):
    rng=np.random.default_rng(19)
    out=[]
    for i in range(0,len(images),5):
        img=images[i]
        a=cv2.getRotationMatrix2D((180,241),3 if i%2 else -3,.95)
        q=cv2.warpAffine(img,a,(360,483),borderValue=(180,180,180))
        q=np.clip(q.astype(np.int16)+rng.normal(0,4,q.shape),0,255).astype(np.uint8)
        ok,j=cv2.imencode(".jpg",q,[cv2.IMWRITE_JPEG_QUALITY,82])
        out.append((i+1,cv2.imdecode(j,cv2.IMREAD_COLOR)))
    out.append((None,np.full((483,360,3),127,np.uint8)))
    return out

def run():
    cv2.setNumThreads(4)
    images=card_images()
    engine=build(images)
    queries=samples(images)
    configs=[(500,24,8),(400,24,8),(350,24,8),(500,12,8),(500,24,6),(500,24,4)]
    output=[]; baseline=None
    for features,checks,geometry in configs:
        engine.sift=cv2.SIFT_create(nfeatures=features,contrastThreshold=.03,edgeThreshold=10,sigma=1.6)
        engine.GEOMETRY_CANDIDATES=geometry
        engine.global_matcher=cv2.FlannBasedMatcher(engine.index_params,dict(checks=checks))
        cv2.setRNGSeed(137)
        engine.global_matcher.add([engine.global_descriptors]);engine.global_matcher.train()
        times=[]; records=[]
        for expected,img in queries:
            cv2.setRNGSeed(137)
            start=time.perf_counter(); r=engine.recognize_image(img); times.append(time.perf_counter()-start)
            records.append({"expected":expected,"actual":r.get("best_match",{}).get("number"),"confident":r.get("confident",False),"status":r["status"],"best":r.get("best_match"),"top":r.get("top_matches"),"gap":r.get("score_gap")})
        if baseline is None: baseline=records
        output.append({"features":features,"checks":checks,"geometry":geometry,"samples":len(records),"correct":sum(r["actual"]==r["expected"] for r in records),"false_confident":sum(r["confident"] and r["actual"]!=r["expected"] for r in records),"median_ms":round(statistics.median(times)*1000,2),"exact_results":records==baseline,"identity_and_confidence_agreement":sum((a["actual"],a["confident"],a["status"])==(b["actual"],b["confident"],b["status"]) for a,b in zip(records,baseline))})
    print(json.dumps({"synthetic_only":True,"opencv":cv2.__version__,"reference_cards":len(images),"descriptors":len(engine.global_descriptors),"results":output},indent=2))
if __name__=="__main__":
    run()
