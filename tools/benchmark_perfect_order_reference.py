#!/usr/bin/env python3
"""Use existing approved Perfect Order reference source in an ephemeral test.
Digital reference transformations are NOT physical-phone-photo validation.
No inventory changes, image artifacts, or production deployment.
"""
import importlib.util
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import cv2
import numpy as np
import schema_v1_library_builder as builder
from schema_v1_recognizer_engine import SchemaV1RecognizerEngine
from tools.benchmark_hybrid_screening import fingerprint,rank_shortlist

BASELINE="a2708f79dc8d008ea62540edfb0450785827c0e4"

def run():
    cv2.setNumThreads(4)
    package=ROOT/"sets/perfect_order"
    cards=json.loads((package/"cards.json").read_text())["cards"]
    meta={c["number"]["sortKey"]:SimpleNamespace(number=c["number"]["sortKey"],display_number=c["number"]["display"],reference_image=c["referenceImage"]) for c in cards}
    with tempfile.TemporaryDirectory() as d:
        d=Path(d)
        images={}
        download=builder.download_card
        def capture(card):
            img=download(card)
            images[card.number]=cv2.resize(img,(360,483),interpolation=cv2.INTER_AREA)
            return img
        builder.download_card=capture
        try:
            builder.build_library(set_id="perfect-order",package_directory=package,output_path=d/"library.pkl",expected_records=124)
        finally:
            builder.download_card=download
        ids=sorted(meta)
        if sorted(images)!=ids:
            raise ValueError("Reference coverage mismatch")
        refs=np.stack([fingerprint(images[n]) for n in ids])
        path=d/"baseline.py"
        path.write_bytes(subprocess.check_output(["git","show",BASELINE+":schema_v1_recognizer_engine.py"],cwd=ROOT))
        spec=importlib.util.spec_from_file_location("accepted_engine",path)
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        kwargs=dict(set_id="perfect-order",set_name="Perfect Order",card_count=124,library_file=str(d/"library.pkl"),cards_by_number=meta)
        baseline=mod.SchemaV1RecognizerEngine(**kwargs)
        baseline.load_library()
        if not baseline.library_ready:
            raise RuntimeError(baseline.library_error)
        candidate=SchemaV1RecognizerEngine(**kwargs)
        for field in ("reference_cards","global_descriptors","global_card_numbers","global_matcher","library_ready"):
            setattr(candidate,field,getattr(baseline,field))
        data=[]
        rng=np.random.default_rng(137)
        for n in ids:
            img=images[n]
            for kind in ("tilt","glare"):
                if kind=="tilt":
                    a=cv2.getRotationMatrix2D((180,241),3 if n%2 else -3,.94)
                    q=cv2.warpAffine(img,a,(360,483),borderValue=(180,180,180))
                    q=np.clip(q.astype(np.int16)+rng.normal(0,4,q.shape),0,255).astype(np.uint8)
                else:
                    mask=np.zeros((483,360),np.uint8)
                    cv2.ellipse(mask,(185,150),(80,30),-25,0,360,125,-1)
                    alpha=mask[...,None].astype(np.float32)/255
                    q=cv2.GaussianBlur((img*(1-alpha)+255*alpha).astype(np.uint8),(5,5),1)
                ok,j=cv2.imencode(".jpg",q,[cv2.IMWRITE_JPEG_QUALITY,82])
                if not ok: raise RuntimeError("Encoding failed")
                data.append((n,kind,cv2.imdecode(j,cv2.IMREAD_COLOR)))
        data.extend([(None,"blank",np.zeros((483,360,3),np.uint8)),(None,"noise",rng.integers(0,256,(483,360,3),dtype=np.uint8))])
        results=[]; original=candidate.rank_cards_global
        baseline.recognize_image(data[0][2]);candidate.recognize_image(data[0][2])
        for i,(expected,kind,img) in enumerate(data):
            row={"expected":expected,"kind":kind}
            for mode in (("baseline","candidate") if i%2==0 else ("candidate","baseline")):
                cv2.setRNGSeed(137);start=time.perf_counter()
                engine=baseline if mode=="baseline" else candidate
                fallback=False
                if mode=="candidate":
                    order=np.argsort(np.count_nonzero(refs!=fingerprint(img),axis=1),kind="stable")
                    chosen=[ids[int(j)] for j in order[:4]]
                    row["shortlist_miss"]=expected is not None and expected not in chosen
                    engine.rank_cards_global=lambda desc:rank_shortlist(engine,desc,chosen)
                try:
                    r=engine.recognize_image(img)
                finally:
                    if mode=="candidate":candidate.rank_cards_global=original
                if mode=="candidate" and not r.get("confident",False):
                    fallback=True
                    cv2.setRNGSeed(137)
                    r=baseline.recognize_image(img)
                row[mode]={"actual":r.get("best_match",{}).get("number"),"confident":bool(r.get("confident",False)),"ms":(time.perf_counter()-start)*1000,"fallback":fallback}
            results.append(row)
        summary={}
        for mode in ("baseline","candidate"):
            summary[mode]={"correct":sum(r[mode]["actual"]==r["expected"] for r in results),"false_confident":sum(r[mode]["confident"] and r[mode]["actual"]!=r["expected"] for r in results),"median_ms":round(statistics.median(r[mode]["ms"] for r in results),3)}
        mismatches=[{"expected":r["expected"],"kind":r["kind"],"baseline":r["baseline"]["actual"],"candidate":r["candidate"]["actual"],"baseline_confident":r["baseline"]["confident"],"candidate_confident":r["candidate"]["confident"]} for r in results if (r["baseline"]["actual"],r["baseline"]["confident"])!=(r["candidate"]["actual"],r["candidate"]["confident"])]
        print(json.dumps({"reference_transformations_only":True,"reference_cards":len(ids),"samples":len(results),"shortlist_misses":sum(r["shortlist_miss"] for r in results),"fallbacks":sum(r["candidate"]["fallback"] for r in results),"results":summary,"identity_confidence_mismatches":mismatches},indent=2))
if __name__=="__main__":
    run()
