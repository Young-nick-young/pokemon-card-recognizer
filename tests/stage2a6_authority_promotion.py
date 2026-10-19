#!/usr/bin/env python3
"""Stage 2A.6 authority promotion.

Runs only in CI on the validator feature branch. Historical source artifacts are
read with git show. It generates only POR/CRI/PBL inventory authority artifacts.
DRI is deliberately untouched.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.create_set import normalize_definition, build_schema_files
from schema_v1_inventory_sheet_plan import build_inventory_sheet_plan

SOURCES = {
    "perfect-order": {
        "ref": "origin/feature/inventory-sheet-automation-v1",
        "dir": "sets/perfect_order",
        "metadata": "sets/perfect_order/inventory_metadata.json",
        "plan": "sets/perfect_order/inventory_sheet_plan.json",
    },
    "chaos-rising": {
        "ref": "origin/candidate/chaos-rising",
        "dir": "sets/chaos_rising",
        "definition": "sets/chaos_rising/normalized_definition.json",
        "metadata": "sets/chaos_rising/inventory_metadata.json",
        "plan": "sets/chaos_rising/inventory_sheet_plan.json",
    },
    "pitch-black": {
        "ref": "origin/candidate/pitch-black",
        "dir": "sets/pitch_black",
        "definition": "sets/pitch_black/normalized_definition.json",
        "metadata": "sets/pitch_black/inventory_metadata.json",
        "plan": "sets/pitch_black/inventory_sheet_plan.json",
    },
}

def git_show(ref: str, path: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=ROOT)

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def json_bytes(obj) -> bytes:
    return (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

def matrix_from_metadata(data):
    return [(row["cardId"], tuple(row["inventoryVariants"])) for row in data["cards"]]

def matrix_from_plan(data):
    return [(row["canonicalCardId"], tuple(row["inventoryVariants"])) for row in data["rows"]]

def matrix_from_definition(data, prefix):
    out = []
    for card in data["cards"]:
        out.append((prefix + str(card["number"]).zfill(3), tuple(card["inventory_variants"])))
    return out

def require_equal(label, a, b):
    if a != b:
        for i, (x, y) in enumerate(zip(a, b), start=1):
            if x != y:
                raise RuntimeError(f"{label}: first mismatch at record {i}: {x!r} != {y!r}")
        raise RuntimeError(f"{label}: length mismatch {len(a)} != {len(b)}")

def write(path: Path, data: bytes):
    path.write_bytes(data)

report = {"sets": {}, "dri": {"generated": False, "status": "NOT VERIFIED"}}

# POR: exact preserved metadata, current deterministic plan builder.
por = SOURCES["perfect-order"]
por_meta_raw = git_show(por["ref"], por["metadata"])
por_plan_raw = git_show(por["ref"], por["plan"])
por_meta = json.loads(por_meta_raw)
por_old_plan = json.loads(por_plan_raw)
por_dir = ROOT / por["dir"]
write(por_dir / "inventory_metadata.json", por_meta_raw)
por_new_plan = build_inventory_sheet_plan(por_dir)
require_equal("POR metadata vs regenerated plan", matrix_from_metadata(por_meta), matrix_from_plan(por_new_plan))
require_equal("POR preserved plan vs regenerated plan availability", matrix_from_plan(por_old_plan), matrix_from_plan(por_new_plan))
por_plan_bytes = json_bytes(por_new_plan)
write(por_dir / "inventory_sheet_plan.json", por_plan_bytes)
report["sets"]["perfect-order"] = {
    "cards": len(por_meta["cards"]),
    "sourceRef": por["ref"],
    "sourceMetadataSha256": sha256(por_meta_raw),
    "sourcePreservedPlanSha256": sha256(por_plan_raw),
    "generatedMetadataSha256": sha256(por_meta_raw),
    "generatedPlanSha256": sha256(por_plan_bytes),
    "availabilityEquivalent": True,
}

# CRI/PBL: regenerate metadata from preserved normalized definition using current
# accepted generator, then regenerate plan using current deterministic builder.
for set_id, prefix in (("chaos-rising", "cri-"), ("pitch-black", "pbl-")):
    cfg = SOURCES[set_id]
    definition_raw = git_show(cfg["ref"], cfg["definition"])
    preserved_meta_raw = git_show(cfg["ref"], cfg["metadata"])
    preserved_plan_raw = git_show(cfg["ref"], cfg["plan"])
    definition = json.loads(definition_raw)
    preserved_meta = json.loads(preserved_meta_raw)
    preserved_plan = json.loads(preserved_plan_raw)

    normalized = normalize_definition(definition, ROOT / cfg["definition"])
    _manifest, _catalogue, generated_meta = build_schema_files(normalized)

    source_matrix = matrix_from_definition(definition, prefix)
    generated_matrix = matrix_from_metadata(generated_meta)
    preserved_meta_matrix = matrix_from_metadata(preserved_meta)
    require_equal(f"{set_id} source vs regenerated metadata", source_matrix, generated_matrix)
    require_equal(f"{set_id} preserved vs regenerated metadata", preserved_meta_matrix, generated_matrix)

    package_dir = ROOT / cfg["dir"]
    meta_bytes = json_bytes(generated_meta)
    write(package_dir / "inventory_metadata.json", meta_bytes)
    generated_plan = build_inventory_sheet_plan(package_dir)
    generated_plan_matrix = matrix_from_plan(generated_plan)
    preserved_plan_matrix = matrix_from_plan(preserved_plan)
    require_equal(f"{set_id} regenerated metadata vs plan", generated_matrix, generated_plan_matrix)
    require_equal(f"{set_id} preserved vs regenerated plan", preserved_plan_matrix, generated_plan_matrix)
    plan_bytes = json_bytes(generated_plan)
    write(package_dir / "inventory_sheet_plan.json", plan_bytes)

    report["sets"][set_id] = {
        "cards": len(generated_meta["cards"]),
        "sourceRef": cfg["ref"],
        "sourceDefinitionSha256": sha256(definition_raw),
        "sourcePreservedMetadataSha256": sha256(preserved_meta_raw),
        "sourcePreservedPlanSha256": sha256(preserved_plan_raw),
        "generatedMetadataSha256": sha256(meta_bytes),
        "generatedPlanSha256": sha256(plan_bytes),
        "availabilityEquivalent": True,
    }

# DRI safety gate: this stage must not create authority files.
dri_dir = ROOT / "sets/destined_rivals"
for name in ("inventory_metadata.json", "inventory_sheet_plan.json"):
    if (dri_dir / name).exists():
        raise RuntimeError(f"DRI safety gate failed: unexpected {name} exists")

print("STAGE 2A.6 AUTHORITY PROMOTION")
print(json.dumps(report, indent=2))
