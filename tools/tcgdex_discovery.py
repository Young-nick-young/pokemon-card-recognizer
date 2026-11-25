#!/usr/bin/env python3
"""Retrieve TCGdex metadata for offline review; never writes production files."""
import argparse
import json
import re
import time
from pathlib import Path
from urllib.request import urlopen

BASE = "https://api.tcgdex.net/v2"
MAPPING = {"normal":"normal", "reverse":"reverse-holo", "holo":"holo"}


def fetch_json(url):
    with urlopen(url, timeout=20) as response:
        return json.load(response)


def retrieve(language, set_id, expected, get=fetch_json, pause=time.sleep):
    if not re.fullmatch(r"[a-z]{2}(?:-[a-z]{2,4})?", language) or not re.fullmatch(r"[A-Za-z0-9-]+", set_id):
        raise ValueError("Invalid language or set ID")
    base = f"{BASE}/{language}"
    source = get(f"{base}/sets/{set_id}")
    if source["id"] != set_id or len(source["cards"]) != expected:
        raise ValueError("Set identity or count mismatch")
    cards = []
    seen = set()
    for brief in source["cards"]:
        cid = brief["id"]
        if not re.fullmatch(r"[A-Za-z0-9-]+", cid) or cid in seen:
            raise ValueError("Invalid or duplicate card ID")
        seen.add(cid)
        pause(0.2)
        card = get(f"{base}/cards/{cid}")
        if card["id"] != cid or card["set"]["id"] != set_id or card["localId"] != brief["localId"] or card["name"] != brief["name"]:
            raise ValueError("Card identity mismatch")
        variants = card.get("variants", {})
        known = [v for k,v in MAPPING.items() if variants.get(k) is True]
        cards.append({"source_id":cid,"local_id":card["localId"],"name":card["name"],
                      "rarity":card.get("rarity"),"category":card.get("category"),
                      "standard_variants":known,"variant_flags":variants})
    return {"status":"REVIEW_REQUIRED","source":"TCGdex API v2","language":language,
            "source_set_id":set_id,"set":source["name"],"exclusive_printings_verified":False,
            "card_count":len(cards),"cards":cards}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--language", default="en")
    p.add_argument("--set-id", required=True)
    p.add_argument("--expected", required=True, type=int)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        p.error("Refusing to overwrite output")
    report = retrieve(a.language,a.set_id,a.expected)
    with a.output.open("x",encoding="utf-8") as f:
        json.dump(report,f,ensure_ascii=False,indent=2)
    print(f'{report["card_count"]} cards; REVIEW_REQUIRED')


if __name__ == "__main__":
    main()
