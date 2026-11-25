#!/usr/bin/env python3
"""Single entrypoint for new-set discovery; output is review evidence only."""
import argparse
import json
from collections import Counter
from pathlib import Path
from catalogue_discovery import discover, compare
from tcgdex_discovery import retrieve
from reconcile_catalogues import reconcile

def run(set_name, expected, denominator, csv_path=None, tcgdex_id=None, language="en", catalogue=None):
    if expected < 1 or denominator < 1:
        raise ValueError("Positive expected count and denominator required")
    if not csv_path and not tcgdex_id:
        raise ValueError("At least one source required")
    if csv_path and language != "en":
        raise ValueError("CSV adapter currently supports English only")
    reports=[]
    if csv_path:
        cards=discover(csv_path,set_name,expected,denominator)
        counts=Counter(v for c in cards for v in c["standard_variants"])
        reports.append({"status":"REVIEW_REQUIRED","source":"user-supplied treatment CSV","set":set_name,"language":language,"card_count":len(cards),"printing_counts":dict(counts),"cards":cards})
    if tcgdex_id:
        report=retrieve(language,tcgdex_id,expected)
        if report["set"].strip().casefold()!=set_name.strip().casefold():
            raise ValueError("TCGdex set name mismatch")
        reports.append(report)
    result={"status":"REVIEW_REQUIRED","exclusive_printings_verified":False,"source_independence_verified":False,"reports":reports}
    if len(reports)==2:
        result["reconciliation"]=reconcile(*reports)
    if catalogue is not None:
        for report in reports:
            numeric=[]
            for c in report["cards"]:
                number=c.get("number",c.get("local_id"))
                if not str(number).isdigit():
                    raise ValueError("Non-numeric numbering not supported")
                numeric.append({**c,"number":int(number)})
            report["differences"]=compare(numeric,catalogue)
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--set-name",required=True)
    p.add_argument("--expected",type=int,required=True)
    p.add_argument("--denominator",type=int,required=True)
    p.add_argument("--csv",type=Path)
    p.add_argument("--tcgdex-id")
    p.add_argument("--language",default="en")
    p.add_argument("--catalogue",type=Path)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():
        p.error("Refusing to overwrite existing report")
    catalogue=json.loads(a.catalogue.read_text(encoding="utf-8")) if a.catalogue else None
    report=run(a.set_name,a.expected,a.denominator,a.csv,a.tcgdex_id,a.language,catalogue)
    with a.output.open("x",encoding="utf-8") as f:
        json.dump(report,f,ensure_ascii=False,indent=2)
    print("Discovery evidence saved; review required. No deployment.")
if __name__=="__main__":
    main()
