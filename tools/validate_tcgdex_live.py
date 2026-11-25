#!/usr/bin/env python3
"""Read-only live metadata validation. No card image downloads or inventory writes."""
import json
import sys
from pathlib import Path
from collections import Counter
from tcgdex_discovery import retrieve

if __name__=="__main__":
    root=Path(__file__).resolve().parents[1]
    report=retrieve("en","me03",124)
    existing=json.loads((root/"sets/perfect_order/cards.json").read_text())
    expected={c["number"]["sortKey"]:c["name"] for c in existing["cards"]}
    actual={int(c["local_id"]):c["name"] for c in report["cards"]}
    if len(actual)!=124 or actual!=expected:
        raise RuntimeError("Live source does not match existing catalogue identities")
    counts=Counter(v for c in report["cards"] for v in c["standard_variants"])
    missing=[c["local_id"] for c in report["cards"] if not c["standard_variants"]]
    print(json.dumps({"identities":len(actual),"standard_variant_counts":dict(counts),"missing_variant_evidence":missing,"exclusive_printings_verified":False},indent=2))
    if missing:
        raise RuntimeError("Missing standard printing evidence")
