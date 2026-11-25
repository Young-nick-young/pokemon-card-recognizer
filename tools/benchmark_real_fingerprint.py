#!/usr/bin/env python3
"""Local-only real photo A/B test for fingerprint shortlisting.
Supply an existing locally built library, its approved local reference images,
and labelled phone captures. No downloads, uploads, or inventory writes.
"""
import argparse
import importlib.util
import subprocess
import tempfile
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
from tools.benchmark_hybrid_screening import fingerprint,rank_shortlist

def read_image(path):
    image=cv2.imread(str(path))
    if image is None:
        raise ValueError("Unreadable image: "+str(path))
    return image

def run(package,library,refs_dir,labels,shortlist):
    cards=json.loads((package/"cards.json").read_text(encoding="utf-8"))["cards"]
    meta={c["number"]["sortKey"]:SimpleNamespace(number=c["number"]["sortKey"],display_number=c["number"]["display"],reference_image=c["referenceImage"]) for c in cards}
    # Compare with the exact accepted production engine, not a candidate used as its own baseline.
    with tempfile.TemporaryDirectory() as d:
        baseline_path=Path(d)/'baseline.py'
        baseline_path.write_bytes(subprocess.check_output(['git','show','a2708f79dc8d008ea62540edfb0450785827c0e4:schema_v1_recognizer_engine.py'],cwd=Path(__file__).resolve().parents[1]))
        spec=importlib.util.spec_from_file_location('accepted_engine',baseline_path)
        mod=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    kwargs=dict(set_id=package.name,set_name=package.name,card_count=len(meta),library_file=str(library),cards_by_number=meta)
    baseline=mod.SchemaV1RecognizerEngine(**kwargs)
    baseline.load_library()
    if not baseline.library_ready:
        raise RuntimeError(baseline.library_error)
    engine=SchemaV1RecognizerEngine(**kwargs)
    for field in ('reference_cards','global_descriptors','global_card_numbers','global_matcher','library_ready'):
        setattr(engine,field,getattr(baseline,field))
    ids=sorted(meta)
    if set(ids)!=set(engine.reference_cards):
        raise ValueError("Reference library identities do not match catalogue")
    refs=np.stack([fingerprint(read_image(refs_dir/f"{n}.jpg")) for n in ids])
    data=json.loads(labels.read_text(encoding="utf-8"))
    if not isinstance(data,list) or not data:
        raise ValueError("Nonempty array of labelled photos required")
    records=[]; original=engine.rank_cards_global
    warmup=read_image(labels.parent/data[0]["path"])
    baseline.recognize_image(warmup); engine.recognize_image(warmup)
    for i,row in enumerate(data):
        expected=row["number"]
        if expected is not None and expected not in meta:
            raise ValueError("Unknown expected identity")
        img=read_image(labels.parent/row["path"])
        pair={}
        for mode in (("baseline","candidate") if i%2==0 else ("candidate","baseline")):
            cv2.setRNGSeed(137)
            start=time.perf_counter()
            fallback=False
            if mode=="candidate":
                order=np.argsort(np.count_nonzero(refs!=fingerprint(img),axis=1),kind="stable")
                chosen=[ids[int(j)] for j in order[:shortlist]]
                engine.rank_cards_global=lambda desc:rank_shortlist(engine,desc,chosen)
            try:
                result=(baseline if mode=="baseline" else engine).recognize_image(img)
            finally:
                engine.rank_cards_global=original
            if mode=="candidate" and not result.get("confident",False):
                fallback=True
                cv2.setRNGSeed(137)
                result=baseline.recognize_image(img)
            actual=result.get("best_match",{}).get("number")
            confident=bool(result.get("confident",False))
            pair[mode]={"actual":actual,"confident":confident,"ms":(time.perf_counter()-start)*1000,"fallback":fallback}
        records.append({"expected":expected,**pair})
    result={}
    for mode in ("baseline","candidate"):
        result[mode]={"correct":sum(r[mode]["actual"]==r["expected"] for r in records),"false_confident":sum(r[mode]["confident"] and r[mode]["actual"]!=r["expected"] for r in records),"median_ms":statistics.median(r[mode]["ms"] for r in records)}
    return {"samples":len(records),"shortlist":shortlist,"identity_confidence_agreement":sum((r["baseline"]["actual"],r["baseline"]["confident"])==(r["candidate"]["actual"],r["candidate"]["confident"]) for r in records),"results":result,"records":records}

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ("package","library","refs","labels","output"):
        p.add_argument("--"+arg,type=Path,required=True)
    p.add_argument("--shortlist",type=int,default=4)
    a=p.parse_args()
    if a.shortlist<1 or a.output.exists():
        p.error("Invalid shortlist size or output already exists")
    report=run(a.package,a.library,a.refs,a.labels,a.shortlist)
    with a.output.open("x",encoding="utf-8") as f:
        json.dump(report,f,indent=2)
    print(json.dumps({k:v for k,v in report.items() if k!="records"},indent=2))
