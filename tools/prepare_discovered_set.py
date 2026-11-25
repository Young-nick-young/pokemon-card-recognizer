#!/usr/bin/env python3
"""Prepare a new-set definition from reviewed discovery evidence and explicit images."""
import argparse
import json
from pathlib import Path
from reconcile_catalogues import index
from create_set import normalize_definition, build_schema_files

def prepare(report, template, approvals):
    if report.get("language","en") != "en":
        raise ValueError("Existing scaffold supports English only")
    if report["set"].strip().casefold() != template["name"].strip().casefold():
        raise ValueError("Set name mismatch")
    cards=index(report)
    if set(cards) != set(range(1,template["expected_cards"]+1)):
        raise ValueError("Numbering or count mismatch")
    if set(approvals) != {str(n) for n in cards}:
        raise ValueError("Explicit per-card review required")
    result=dict(template)
    result.pop("cards_file",None)
    result["cards"]=[]
    for n,c in sorted(cards.items()):
        a=approvals[str(n)]
        variants=a["inventory_variants"]
        if a.get("reviewed") is not True or not a.get("reference_image") or not a.get("evidence"):
            raise ValueError(f"Missing approval, image or evidence for {n}")
        if not isinstance(variants,list) or not variants or len(set(variants))!=len(variants) or not set(variants)<= {"normal","reverse-holo","holo","other"}:
            raise ValueError(f"Invalid variants for {n}")
        if not set(c["standard_variants"])<=set(variants):
            raise ValueError(f"Discovered printing omitted for {n}")
        result["cards"].append({"number":n,"name":c["name"],"rarity":c["rarity"],"card_type":a["card_type"],"reference_image":a["reference_image"],"variants":variants,"inventory_variants":variants})
    config = normalize_definition(result, Path("candidate.json"))
    _, catalogue, inventory = build_schema_files(config)
    for source, schema, row in zip(result["cards"], catalogue["cards"], inventory["cards"]):
        if schema["variants"] != source["inventory_variants"] or row["inventoryVariants"] != source["inventory_variants"]:
            raise ValueError("Existing scaffold overrides reviewed variants for " + str(source["number"]))
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("report","template","approvals","output"):
        p.add_argument("--"+k,type=Path,required=True)
    a=p.parse_args()
    read=lambda f:json.loads(f.read_text(encoding="utf-8"))
    result=prepare(read(a.report),read(a.template),read(a.approvals))
    with a.output.open("x",encoding="utf-8") as f:
        json.dump(result,f,ensure_ascii=False,indent=2)
    print("Candidate definition prepared. Existing onboarding validation still required.")

if __name__=="__main__":
    main()
