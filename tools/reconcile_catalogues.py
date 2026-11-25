#!/usr/bin/env python3
"""Compare discovery reports without altering inventory or approving printings."""
import argparse
import json
import re
from pathlib import Path


def index(report):
    if report.get("status") != "REVIEW_REQUIRED":
        raise ValueError("Expected a discovery report")
    rows = {}
    for card in report["cards"]:
        raw = str(card.get("number", card.get("local_id", "")))
        if not re.fullmatch(r"[0-9]+", raw):
            raise ValueError("Non-numeric numbering requires a dedicated namespace adapter")
        n = int(raw)
        if n < 1 or n in rows:
            raise ValueError("Invalid or duplicate collector number")
        variants = card["standard_variants"]
        if not isinstance(variants,list) or len(set(variants)) != len(variants) or not set(variants) <= {"normal","reverse-holo","holo"}:
            raise ValueError("Invalid standard variants")
        rows[n] = card
    if len(rows) != report["card_count"]:
        raise ValueError("Report count mismatch")
    return rows


def reconcile(left, right):
    if left["set"].strip().casefold() != right["set"].strip().casefold():
        raise ValueError("Set names disagree")
    if left.get("language","en") != right.get("language","en"):
        raise ValueError("Language mismatch")
    a,b = index(left),index(right)
    records = []
    for n in sorted(a.keys() | b.keys()):
        x,y = a.get(n),b.get(n)
        issues = []
        if x is None or y is None:
            issues.append("missing_identity")
        else:
            for key in ("name","rarity","category"):
                if not x.get(key) or not y.get(key) or x[key].strip().casefold() != y[key].strip().casefold():
                    issues.append(key+"_mismatch_or_missing")
            if set(x["standard_variants"]) != set(y["standard_variants"]):
                issues.append("variant_disagreement")
            if not x["standard_variants"] or not y["standard_variants"]:
                issues.append("variant_evidence_missing")
        records.append({"number":n,"left":x,"right":y,"issues":issues})
    return {"status":"REVIEW_REQUIRED","set":left["set"],"sources":[left["source"],right["source"]],
            "source_independence_verified":False,"exclusive_printings_verified":False,
            "card_count":len(records),"agreement_count":sum(not r["issues"] for r in records),
            "conflict_count":sum(bool(r["issues"]) for r in records),"cards":records}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("left",type=Path)
    p.add_argument("right",type=Path)
    p.add_argument("--output",type=Path,required=True)
    a = p.parse_args()
    result = reconcile(json.loads(a.left.read_text(encoding="utf-8")),json.loads(a.right.read_text(encoding="utf-8")))
    with a.output.open("x",encoding="utf-8") as f:
        json.dump(result,f,ensure_ascii=False,indent=2)
    print(f'{result["agreement_count"]} agreements; {result["conflict_count"]} conflicts; REVIEW_REQUIRED')


if __name__ == "__main__":
    main()
