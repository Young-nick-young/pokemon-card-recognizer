#!/usr/bin/env python3
"""Test fingerprint-only shortlist vs full SIFT. Synthetic stress cases; never deployed."""
import json
import statistics
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from tools.benchmark_sift_parameters import card_images,samples
from tools.benchmark_sift_threads import build
from tools.benchmark_hybrid_screening import fingerprint,rank_shortlist

def queries(images):
    out=samples(images)
    rng=np.random.default_rng(301)
    for i in range(0,len(images),7):
        img=images[i].copy()
        h,w=img.shape[:2]
        src=np.float32([[0,0],[w-1,0],[w-1,h-1],[0,h-1]])
        dst=np.float32([[18,7],[w-9,24],[w-23,h-13],[5,h-25]])
        q=cv2.warpPerspective(img,cv2.getPerspectiveTransform(src,dst),(w,h),borderValue=(160,160,160))
        out.append((i+1,q))
        mask=np.zeros((h,w),np.uint8)
        cv2.ellipse(mask,(w//2,h//3),(w//5,h//12),-30,0,360,150,-1)
        alpha=mask[...,None].astype(np.float32)/255
        glare=(img*(1-alpha)+255*alpha).astype(np.uint8)
        glare=cv2.GaussianBlur(glare,(5,5),1.0)
        out.append((i+1,glare))
    # Unrelated image and card-like distractor, not included in the library.
    out.append((None,rng.integers(0,256,(483,360,3),dtype=np.uint8)))
    distractor=images[0].copy()
    cv2.rectangle(distractor,(12,45),(348,470),(35,85,165),-1)
    cv2.putText(distractor,"NOT IN SET",(25,245),cv2.FONT_HERSHEY_SIMPLEX,1,(255,255,255),2)
    out.append((None,distractor))
    return out

def run():
    cv2.setNumThreads(4)
    images=card_images()
    engine=build(images)
    refs=np.stack([fingerprint(i) for i in images])
    data=queries(images)
    original=engine.rank_cards_global
    configs=[0,4,8,12]
    rows={k:[] for k in configs}
    engine.recognize_image(data[0][1])
    for i,(expected,img) in enumerate(data):
        for k in configs[i%len(configs):]+configs[:i%len(configs)]:
            cv2.setRNGSeed(137)
            start=time.perf_counter()
            fallback=False
            rank=None
            if k:
                ids=np.argsort(np.count_nonzero(refs!=fingerprint(img),axis=1),kind="stable")+1
                if expected is not None:
                    rank=int(np.where(ids==expected)[0][0]+1)
                chosen=list(map(int,ids[:k]))
                engine.rank_cards_global=lambda desc:rank_shortlist(engine,desc,chosen)
            try:
                r=engine.recognize_image(img)
            finally:
                engine.rank_cards_global=original
            if k and not r.get("confident",False):
                fallback=True
                cv2.setRNGSeed(137)
                r=engine.recognize_image(img)
            ms=(time.perf_counter()-start)*1000
            rows[k].append({"expected":expected,"actual":r.get("best_match",{}).get("number"),"confident":r.get("confident",False),"rank":rank,"fallback":fallback,"ms":ms})
    result=[]
    for k in configs:
        rs=rows[k]
        result.append({"shortlist":k,"samples":len(rs),"correct":sum(r["actual"]==r["expected"] for r in rs),"false_confident":sum(r["confident"] and r["actual"]!=r["expected"] for r in rs),"identity_confidence_agreement":sum((r["actual"],r["confident"])==(b["actual"],b["confident"]) for r,b in zip(rs,rows[0])),"shortlist_misses":sum(r["rank"] is not None and r["rank"]>k for r in rs) if k else None,"fallbacks":sum(r["fallback"] for r in rs),"median_ms":round(statistics.median(r["ms"] for r in rs),3)})
    print(json.dumps({"synthetic_only":True,"reference_cards":len(images),"results":result},indent=2))

if __name__=="__main__":
    run()
