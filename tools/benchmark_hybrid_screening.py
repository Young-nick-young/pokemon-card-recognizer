#!/usr/bin/env python3
"""Offline screening experiment: image fingerprints and OCR hints.
Never used by the production recognizer. Synthetic images only.
"""
import json
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path
from collections import defaultdict

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from tools.benchmark_sift_parameters import card_images,samples
from tools.benchmark_sift_threads import build

def fingerprint(image):
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    h,w=gray.shape
    crop=gray[int(h*.08):int(h*.67),int(w*.08):int(w*.92)]
    small=cv2.resize(crop,(32,32),interpolation=cv2.INTER_AREA).astype(np.float32)
    low=cv2.dct(small)[:12,:12].ravel()[1:]
    return low>np.median(low)

def ocr_hint(image):
    if shutil.which("tesseract") is None:
        return None
    h,w=image.shape[:2]
    crop=image[int(h*.86):h,:int(w*.60)]
    gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
    gray=cv2.resize(gray,None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC)
    ok,png=cv2.imencode(".png",gray)
    if not ok:
        return None
    proc=subprocess.run(["tesseract","stdin","stdout","--psm","11","-c","tessedit_char_whitelist=0123456789/"],input=png.tobytes(),capture_output=True,timeout=5)
    matches=re.findall(r"(?<!\d)(\d{1,3})\s*/\s*124(?!\d)",proc.stdout.decode("utf-8","replace"))
    ids={int(v) for v in matches if 1<=int(v)<=124}
    return next(iter(ids)) if len(ids)==1 else None

def rank_shortlist(engine,descriptors,ids):
    if descriptors is None or len(descriptors)<2:
        return []
    blocks=[]; labels=[]
    for n in ids:
        block=engine.get_reference_descriptors(engine.reference_cards[n])
        blocks.append(block)
        labels.extend([n]*len(block))
    train=np.concatenate(blocks)
    if len(train)<2:
        return []
    pairs=cv2.BFMatcher(cv2.NORM_L2).knnMatch(descriptors,train,k=2)
    votes=defaultdict(list)
    for pair in pairs:
        if len(pair)==2 and pair[0].distance<engine.LOWE_RATIO*pair[1].distance:
            votes[labels[pair[0].trainIdx]].append(pair[0].distance)
    return sorted([{"number":n,"votes":len(ds),"avg_distance":sum(ds)/len(ds)} for n,ds in votes.items()],key=lambda x:(-x["votes"],x["avg_distance"]))

def run():
    cv2.setNumThreads(4)
    images=card_images()
    engine=build(images)
    refs=np.stack([fingerprint(i) for i in images])
    queries=samples(images)
    for i in range(0,len(images),11):
        q=cv2.GaussianBlur(images[i],(7,7),2)
        q[160:210,40:320]=255
        queries.append((i+1,q))
    rng=np.random.default_rng(42)
    queries.extend([(None,rng.integers(0,256,(483,360,3),dtype=np.uint8)),(None,np.zeros((483,360,3),np.uint8))])
    original_rank=engine.rank_cards_global
    rows=[]
    for expected,img in queries:
        t=time.perf_counter()
        ids=np.argsort(np.count_nonzero(refs!=fingerprint(img),axis=1),kind="stable")+1
        fp_ms=(time.perf_counter()-t)*1000
        t=time.perf_counter()
        try:
            hint=ocr_hint(img)
        except subprocess.TimeoutExpired:
            hint=None
        ocr_ms=(time.perf_counter()-t)*1000
        cv2.setRNGSeed(137)
        t=time.perf_counter()
        baseline=engine.recognize_image(img)
        baseline_ms=(time.perf_counter()-t)*1000
        chosen=list(map(int,ids[:12]))
        if hint is not None and hint not in chosen:
            chosen.append(hint)
        cv2.setRNGSeed(137)
        t=time.perf_counter()
        engine.rank_cards_global=lambda desc:rank_shortlist(engine,desc,chosen)
        try:
            fast=engine.recognize_image(img)
        finally:
            engine.rank_cards_global=original_rank
        fallback=not fast.get("confident",False)
        if fallback:
            cv2.setRNGSeed(137)
            fast=engine.recognize_image(img)
        hybrid_ms=(time.perf_counter()-t)*1000+fp_ms+ocr_ms
        actual=lambda r:r.get("best_match",{}).get("number")
        rows.append({"expected":expected,"rank":int(np.where(ids==expected)[0][0]+1) if expected is not None else None,"hint":hint,"fp_ms":fp_ms,"ocr_ms":ocr_ms,"baseline_ms":baseline_ms,"hybrid_ms":hybrid_ms,"baseline":actual(baseline),"hybrid":actual(fast),"baseline_confident":baseline.get("confident",False),"hybrid_confident":fast.get("confident",False),"fallback":fallback})
    positives=[r for r in rows if r["expected"] is not None]
    median=lambda k:round(statistics.median(r[k] for r in rows),3)
    print(json.dumps({"synthetic_only":True,"samples":len(rows),"positive_samples":len(positives),"top_4_recall":sum(r["rank"]<=4 for r in positives),"top_12_recall":sum(r["rank"]<=12 for r in positives),"ocr_available":bool(shutil.which("tesseract")),"ocr_correct":sum(r["hint"]==r["expected"] for r in positives),"ocr_wrong":sum(r["hint"] is not None and r["hint"]!=r["expected"] for r in rows),"baseline_correct":sum(r["baseline"]==r["expected"] for r in rows),"hybrid_correct":sum(r["hybrid"]==r["expected"] for r in rows),"baseline_false_confident":sum(r["baseline_confident"] and r["baseline"]!=r["expected"] for r in rows),"hybrid_false_confident":sum(r["hybrid_confident"] and r["hybrid"]!=r["expected"] for r in rows),"fallbacks":sum(r["fallback"] for r in rows),"median_ms":{k:median(k) for k in ("fp_ms","ocr_ms","baseline_ms","hybrid_ms")}},indent=2))

if __name__=="__main__":
    run()
