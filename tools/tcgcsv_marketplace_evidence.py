#!/usr/bin/env python3
"""Reconcile permitted local TCGCSV JSON exports against known card identities.
Marketplace listings are evidence only, never a complete physical printing list.
No downloads, prices, card art, or inventory writes.
"""
import argparse
import json
import re
from pathlib import Path

FINISH={"Normal":"normal","Holofoil":"holo","Reverse Holofoil":"reverse-holo"}

def rows(payload):
    if payload.get("success") is not True or payload.get("errors") or not isinstance(payload.get("results"),list):
        raise ValueError("Invalid TCGCSV export")
    return payload["results"]

def reconcile_marketplace(products, prices, catalogue, group_id):
    known={}
    for c in catalogue["cards"]:
        n=c["number"]["sortKey"]
        if n in known:
            raise ValueError("Duplicate catalogue number")
        known[n]=c
    subtypes={}
    for row in rows(prices):
        pid=row["productId"]
        subtype=row["subTypeName"]
        subtypes.setdefault(pid,set()).add(subtype)
    matches=[]; review=[]; seen=set(); excluded=0
    for product in rows(products):
        pid=product["productId"]
        if pid in seen or product.get("categoryId")!=3 or product.get("groupId")!=group_id:
            raise ValueError("Duplicate product or wrong group/category")
        seen.add(pid)
        name=product["name"]
        if re.search(r"\b(jumbo|oversized)\b",name,re.I):
            excluded+=1
            continue
        extended={v["name"]:v["value"] for v in product.get("extendedData",[])}
        raw=extended.get("Number","")
        m=re.fullmatch(r"(\d+)(?:/(\d+))?",raw.strip())
        if not m:
            review.append({"productId":pid,"name":name,"reason":"missing_or_nonstandard_number"})
            continue
        card=known.get(int(m[1]))
        if not card or name.strip().casefold()!=card["name"].strip().casefold():
            review.append({"productId":pid,"name":name,"number":raw,"reason":"identity_or_special_printing_review"})
            continue
        if m[2] is not None and "/" in card["number"]["display"] and int(m[2])!=int(card["number"]["display"].split("/")[1]):
            review.append({"productId":pid,"name":name,"number":raw,"reason":"denominator_mismatch"})
            continue
        types=sorted(subtypes.get(pid,set()))
        matches.append({"cardId":card["cardId"],"productId":pid,"marketplace_subtypes":types,
                        "standard_variant_evidence":[FINISH[t] for t in types if t in FINISH],
                        "unmapped_subtypes":[t for t in types if t not in FINISH]})
    return {"status":"REVIEW_REQUIRED","source":"local TCGCSV products/prices export","group_id":group_id,
            "matches":matches,"review":review,"excluded_jumbo":excluded,"exclusive_printings_verified":False,
            "missing_marketplace_card_ids":sorted({c["cardId"] for c in known.values()}-{m["cardId"] for m in matches})}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ("products","prices","catalogue","output"):
        p.add_argument("--"+arg,type=Path,required=True)
    p.add_argument("--group-id",type=int,required=True)
    a=p.parse_args()
    read=lambda path:json.loads(path.read_text(encoding="utf-8"))
    report=reconcile_marketplace(read(a.products),read(a.prices),read(a.catalogue),a.group_id)
    with a.output.open("x",encoding="utf-8") as f:
        json.dump(report,f,ensure_ascii=False,indent=2)
    print(f'{len(report["matches"])} exact listings; {len(report["review"])} require review; no inventory changes')

if __name__=="__main__":
    main()
