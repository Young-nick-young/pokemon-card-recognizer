#!/usr/bin/env python3
"""Pre-flight validator for Schema v1 Pokémon scanner set candidates."""
from __future__ import annotations
import argparse, importlib, json, pickle, re, sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VARIANTS=["normal","reverse-holo","holo","other"]

class Report:
    def __init__(self,set_id): self.set_id=set_id; self.passes=[]; self.failures=[]; self.warnings=[]
    def passed(self,m): self.passes.append(m)
    def failed(self,m): self.failures.append(m)
    def warned(self,m): self.warnings.append(m)
    def render(self,display_name=None):
        print("Pokémon Scanner — Set Pre-flight"); print("Set:",display_name or self.set_id,"["+self.set_id+"]"); print()
        for m in self.passes: print("PASS ",m)
        for m in self.warnings: print("WARN ",m)
        for m in self.failures: print("FAIL ",m)
        print()
        if self.failures: print("RESULT: FAIL —",len(self.failures),"blocking error(s)"); return False
        print("RESULT: PASS" + ((" — "+str(len(self.warnings))+" warning(s)") if self.warnings else "")); return True

def read_json(path,report,label):
    try: v=json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError: report.failed(label+" missing: "+str(path)); return None
    except (OSError,json.JSONDecodeError) as e: report.failed(label+" unreadable/malformed: "+str(e)); return None
    report.passed(label+" parses as JSON"); return v

def valid_http_url(v):
    if not isinstance(v,str) or not v.strip(): return False
    p=urlparse(v); return p.scheme in ("http","https") and bool(p.netloc)
def python_name(set_id): return set_id.replace("-","_").replace(".","_")
def expected_prefixes(manifest):
    code=str((manifest.get("externalIds") or {}).get("displayCode") or "").strip(); return code.lower()+"-",code.upper()+"-"

def check_schema(root,package_dir,manifest,catalogue,report):
    if manifest is None or catalogue is None: return None
    try:
        sys.path.insert(0,str(root)); from schema_v1_loader import load_schema_v1_package; package=load_schema_v1_package(package_dir)
    except Exception as e: report.failed("Schema v1 package validation: "+str(e).replace("\n"," | ")); return None
    finally:
        if sys.path and sys.path[0]==str(root): sys.path.pop(0)
    report.passed("Schema v1 package is valid"); return package

def check_manifest_and_cards(set_id,manifest,catalogue,report):
    if not isinstance(manifest,dict): report.failed("manifest root must be an object"); return
    required=["schemaVersion","setId","displayName","language","market","collections","numberingNamespaces","variants","catalogue","inventory"]
    missing=[k for k in required if k not in manifest]
    report.failed("manifest missing required metadata: "+", ".join(missing)) if missing else report.passed("required manifest metadata present")
    if manifest.get("setId")!=set_id: report.failed("manifest.setId is "+repr(manifest.get("setId"))+", expected "+repr(set_id))
    external=manifest.get("externalIds") or {}; bad=[k for k in ("displayCode","officialCode","pokemonTcgData") if not isinstance(external.get(k),str) or not external.get(k).strip()]
    report.failed("required external IDs missing: "+", ".join(bad)) if bad else report.passed("required external IDs present")
    aliases=manifest.get("aliases",[])
    if not isinstance(aliases,list): report.failed("manifest.aliases must be an array")
    elif len(aliases)!=len(set(aliases)): report.failed("manifest.aliases contains duplicates")
    else: report.passed(str(len(aliases))+" unique manifest aliases")
    if not isinstance(catalogue,dict): report.failed("cards.json root must be an object"); return
    cards=catalogue.get("cards")
    if not isinstance(cards,list): report.failed("cards.json cards must be an array"); return
    expected=(manifest.get("catalogue") or {}).get("expectedRecords")
    report.passed(str(len(cards))+"/"+str(expected)+" catalogue records") if len(cards)==expected else report.failed("catalogue has "+str(len(cards))+" cards; expected "+str(expected))
    ids=[c.get("cardId") for c in cards if isinstance(c,dict)]; dups=sorted({v for v in ids if v and ids.count(v)>1})
    if dups: report.failed("duplicate canonical card IDs: "+", ".join(dups))
    elif len(ids)==len(cards) and all(isinstance(v,str) and v for v in ids): report.passed(str(len(ids))+" unique canonical IDs")
    else: report.failed("one or more cards are missing canonical cardId")
    numbers=[(c.get("number") or {}).get("sortKey") for c in cards if isinstance(c,dict)]; expected_numbers=list(range(1,len(cards)+1))
    if numbers==expected_numbers: report.passed("collector numbering is contiguous 1 through "+str(len(cards)))
    else: report.failed("collector numbering/order mismatch")
    bad_images=[str(c.get("cardId") or "<unknown>") for c in cards if isinstance(c,dict) and not valid_http_url(c.get("referenceImage"))]
    report.failed("missing/invalid recognition image URL: "+", ".join(bad_images[:20])) if bad_images else report.passed(str(len(cards))+" recognition image URLs present")
    variants=manifest.get("variants")
    if not isinstance(variants,list) or not variants: report.failed("manifest variants are missing/invalid"); return
    variant_ids=[v.get("variantId") for v in variants if isinstance(v,dict)]
    report.failed("manifest contains duplicate variant IDs") if len(variant_ids)!=len(set(variant_ids)) else report.passed("variant IDs are unique")
    if variant_ids!=DEFAULT_VARIANTS: report.warned("non-standard variant definition is in use; confirm this is intentional")
    declared=set(variant_ids); bad=[]
    for c in cards:
        if isinstance(c,dict):
            vals=c.get("variants")
            if not isinstance(vals,list) or not vals or any(v not in declared for v in vals): bad.append(str(c.get("cardId")))
    report.failed("card variant definitions invalid for: "+", ".join(bad[:20])) if bad else report.passed("all card variants are declared by the manifest")


def check_inventory_metadata(package_dir,set_id,manifest,catalogue,report):
    metadata=read_json(package_dir/"inventory_metadata.json",report,"inventory metadata")
    if not isinstance(metadata,dict): return None
    if metadata.get("inventoryMetadataVersion")!=1: report.failed("inventory metadata version must be 1")
    if metadata.get("setId")!=set_id: report.failed("inventory metadata setId mismatch")
    rows=metadata.get("cards")
    cards=catalogue.get("cards") if isinstance(catalogue,dict) else None
    if not isinstance(rows,list) or not isinstance(cards,list): report.failed("inventory metadata cards must be an array"); return metadata
    if len(rows)!=len(cards): report.failed("inventory metadata card count differs from Schema catalogue")
    declared={v.get("variantId") for v in (manifest.get("variants") or []) if isinstance(v,dict)}
    expected_ids=[c.get("cardId") for c in cards if isinstance(c,dict)]
    actual_ids=[]; bad=[]
    for entry in rows:
        if not isinstance(entry,dict): bad.append("<non-object>"); continue
        cid=entry.get("cardId"); actual_ids.append(cid)
        rarity=entry.get("rarity"); card_type=entry.get("cardType"); variants=entry.get("inventoryVariants")
        if not isinstance(cid,str) or not cid or not isinstance(rarity,str) or not rarity.strip(): bad.append(str(cid))
        if card_type is not None and not isinstance(card_type,str): bad.append(str(cid))
        if not isinstance(variants,list) or not variants or len(variants)!=len(set(variants)) or any(v not in declared for v in variants): bad.append(str(cid))
    if actual_ids!=expected_ids: report.failed("inventory metadata card order/identity differs from Schema catalogue")
    elif bad: report.failed("invalid inventory metadata entries: "+", ".join(bad[:20]))
    else: report.passed(str(len(rows))+" explicit inventory metadata records match Schema catalogue")
    return metadata

def check_projection(root,package_dir,manifest,report):
    try:
        sys.path.insert(0,str(root)); from schema_v1_inventory_projection import build_inventory_projection; p=build_inventory_projection(package_dir)
    except Exception as e: report.failed("inventory projection consistency: "+str(e).replace("\n"," | ")); return None
    finally:
        if sys.path and sys.path[0]==str(root): sys.path.pop(0)
    expected=(manifest.get("catalogue") or {}).get("expectedRecords")
    if p["cardCount"]!=expected: report.failed("inventory projection card count differs from schema")
    else: report.passed("inventory projection matches schema (rows "+str(p["startRow"])+"–"+str(p["endRow"])+")")
    return p

def check_build_registry(root,set_id,manifest,p_name,report,require_library):
    registry=read_json(root/"schema_v1_builds.json",report,"build registry")
    if not isinstance(registry,dict) or not isinstance(registry.get("sets"),list): report.failed("build registry has no sets array"); return
    entries=[v for v in registry["sets"] if isinstance(v,dict) and v.get("setId")==set_id]
    if len(entries)!=1: report.failed("build registry must contain set exactly once; found "+str(len(entries))); return
    e=entries[0]; expected=(manifest.get("catalogue") or {}).get("expectedRecords"); package="sets/"+p_name; output=package+"/card_library.pkl"; drift=[]
    if e.get("expectedRecords")!=expected: drift.append("expectedRecords")
    if e.get("package")!=package: drift.append("package")
    if e.get("output")!=output: drift.append("output")
    report.failed("build registry metadata drift: "+", ".join(drift)) if drift else report.passed("build registry matches schema")
    if not require_library: return
    path=root/output
    if not path.exists(): report.failed("recognition library required but missing: "+str(path)); return
    try:
        with path.open("rb") as h: lib=pickle.load(h)
    except Exception as ex: report.failed("recognition library unreadable: "+str(ex)); return
    count=lib.get("card_count") if isinstance(lib,dict) else None; cards=lib.get("cards") if isinstance(lib,dict) else None
    if count!=expected or not isinstance(cards,dict) or len(cards)!=expected: report.failed("recognition library count mismatch: expected "+str(expected))
    else: report.passed("recognition library contains "+str(expected)+" cards")

def _import_module(root,name):
    sys.path.insert(0,str(root)); importlib.invalidate_caches()
    try:
        sys.modules.pop(name,None); return importlib.import_module(name)
    finally:
        if sys.path and sys.path[0]==str(root): sys.path.pop(0)

def check_runtime(root,set_id,p_name,manifest,report):
    try: metadata=_import_module(root,"sets."+p_name+".runtime_metadata").load_runtime_metadata()
    except Exception as e: report.failed("runtime metadata load failed: "+str(e)); return
    external=manifest.get("externalIds") or {}; expected=(manifest.get("catalogue") or {}).get("expectedRecords"); drift=[]
    if metadata.set_id!=set_id: drift.append("set_id")
    if metadata.set_name!=manifest.get("displayName"): drift.append("displayName")
    if metadata.set_code!=external.get("pokemonTcgData"): drift.append("datasetId")
    if metadata.card_count!=expected: drift.append("cardCount")
    report.failed("runtime metadata drift: "+", ".join(drift)) if drift else report.passed("runtime metadata matches Schema v1")

def extract_prop(text,key):
    m=re.search(r"\b"+re.escape(key)+r"\s*:\s*\"([^\"]*)\"",text); return m.group(1) if m else None
def extract_int(text,key):
    m=re.search(r"\b"+re.escape(key)+r"\s*:\s*(\d+)",text); return int(m.group(1)) if m else None

def check_frontend(frontend_root,set_id,manifest,report):
    path=frontend_root/"js"/"sets"/(set_id+".js")
    try: text=path.read_text(encoding="utf-8")
    except OSError as e: report.failed("frontend set config missing/unreadable: "+str(e)); return
    report.passed("frontend config self-registers through SetRegistry") if "SetRegistry.register(" in text else report.failed("frontend config does not self-register through SetRegistry")
    external=manifest.get("externalIds") or {}; expected={"id":set_id,"name":manifest.get("displayName"),"setCode":external.get("displayCode"),"officialCode":external.get("officialCode"),"datasetId":external.get("pokemonTcgData")}; drift=[k for k,v in expected.items() if extract_prop(text,k)!=v]
    count=(manifest.get("catalogue") or {}).get("expectedRecords")
    if extract_int(text,"maxCard")!=count: drift.append("maxCard")
    ns=manifest.get("numberingNamespaces") or []; denom=int(ns[0]["denominator"]) if ns and isinstance(ns[0],dict) and str(ns[0].get("denominator","")).isdigit() else None
    if denom is not None and extract_int(text,"denominator")!=denom: drift.append("denominator")
    series=extract_prop(text,"series")
    report.passed("frontend series metadata present: "+series) if series else report.failed("frontend config missing required series metadata")
    if "/api/v1/sets/"+set_id+"/package" not in text: drift.append("schemaPackageUrl")
    report.failed("frontend/schema metadata drift: "+", ".join(dict.fromkeys(drift))) if drift else report.passed("frontend config matches Schema v1 metadata")
    try: index=(frontend_root/"index.html").read_text(encoding="utf-8")
    except OSError as e: report.failed("frontend index unreadable: "+str(e)); return
    include='<script src="./js/sets/'+set_id+'.js"></script>'; n=index.count(include)
    report.passed("frontend index includes set config exactly once") if n==1 else report.failed("frontend index must include set config exactly once; found "+str(n))

def check_router(root,set_id,p_name,manifest,report):
    try: text=(root/"main.py").read_text(encoding="utf-8")
    except OSError as e: report.failed("recognizer router unreadable: "+str(e)); return
    checks=["from sets."+p_name+" import recognizer as "+p_name,json.dumps(set_id)+": "+p_name,"from sets."+p_name+".public_package import (",'@app.get("/api/v1/sets/'+set_id+'/package")']
    report.failed("recognizer/router registration missing") if any(n not in text for n in checks) else report.passed("recognizer and public-package routing registered")
    aliases=[set_id]+list(manifest.get("aliases") or []); missing=[a for a in aliases if json.dumps(a)+": "+json.dumps(set_id) not in text]
    report.failed("recognizer/router aliases missing: "+", ".join(missing)) if missing else report.passed("recognizer aliases resolve to canonical set ID")

def check_public_package(root,set_id,p_name,manifest,report):
    try: package=_import_module(root,"sets."+p_name+".public_package").build_public_package()
    except Exception as e: report.failed("public-package projection failed: "+str(e)); return
    expected=(manifest.get("catalogue") or {}).get("expectedRecords")
    report.failed("public-package output does not match set ID/card count") if package.get("setId")!=set_id or len(package.get("cards",[]))!=expected else report.passed("public-package projection matches schema")

def check_apps(app_root,set_id,p_name,manifest,projection,report):
    path=app_root/(p_name+"_config.gs")
    try: text=path.read_text(encoding="utf-8")
    except OSError as e: report.failed("Apps Script config missing/unreadable: "+str(e)); return
    expected_count=(manifest.get("catalogue") or {}).get("expectedRecords"); cp,lp=expected_prefixes(manifest)
    strings={"setId":set_id,"sheetName":(manifest.get("inventory") or {}).get("sheetName"),"canonicalCardPrefix":cp,"legacyCardPrefix":lp}
    ints={"startRow":(manifest.get("inventory") or {}).get("startRow"),"cardCount":expected_count,"cardIdColumn":(manifest.get("inventory") or {}).get("cardIdColumn")}; drift=[]
    for k,v in strings.items():
        if extract_prop(text,k)!=v: drift.append(k)
    for k,v in ints.items():
        if extract_int(text,k)!=v: drift.append(k)
    if projection:
        for variant_id,column in projection["variantColumns"].items():
            if not re.search(re.escape(json.dumps(variant_id))+r"\s*:\s*"+str(column)+r"\b",text): drift.append("variantColumns."+variant_id)
    if drift: report.failed("Apps Script config/schema drift: "+", ".join(dict.fromkeys(drift)))
    elif not extract_prop(text,"spreadsheetId"): report.failed("Apps Script config spreadsheetId is missing")
    else: report.passed("Apps Script config matches schema/inventory projection")

def check_alias_collisions(root,set_id,manifest,report):
    own=set([set_id]+list(manifest.get("aliases") or [])); collisions=[]
    for path in sorted((root/"sets").glob("*/manifest.json")):
        try: other=json.loads(path.read_text(encoding="utf-8"))
        except Exception: continue
        oid=other.get("setId")
        if oid==set_id: continue
        overlap=sorted(v for v in own.intersection(set([oid]+list(other.get("aliases") or []))) if v)
        if overlap: collisions.append((oid,overlap))
    report.failed("alias/canonical-ID collision with another Schema v1 set: "+"; ".join(str(o)+": "+", ".join(v) for o,v in collisions)) if collisions else report.passed("no Schema v1 alias/canonical-ID collisions")

def validate(set_id,recognizer_root=ROOT,frontend_root=None,apps_script_root=None,require_library=False,integration=False):
    recognizer_root=Path(recognizer_root).resolve(); report=Report(set_id); p=python_name(set_id); package_dir=recognizer_root/"sets"/p
    manifest=read_json(package_dir/"manifest.json",report,"manifest"); catalogue=read_json(package_dir/"cards.json",report,"catalogue"); check_schema(recognizer_root,package_dir,manifest,catalogue,report)
    if integration:
        if frontend_root is None: report.failed("--integration requires --frontend-root")
        if apps_script_root is None: report.failed("--integration requires --apps-script-root")
    if isinstance(manifest,dict) and isinstance(catalogue,dict):
        check_manifest_and_cards(set_id,manifest,catalogue,report); check_inventory_metadata(package_dir,set_id,manifest,catalogue,report); projection=check_projection(recognizer_root,package_dir,manifest,report)
        check_build_registry(recognizer_root,set_id,manifest,p,report,require_library); check_runtime(recognizer_root,set_id,p,manifest,report); check_router(recognizer_root,set_id,p,manifest,report); check_public_package(recognizer_root,set_id,p,manifest,report); check_alias_collisions(recognizer_root,set_id,manifest,report)
        if frontend_root is not None: check_frontend(Path(frontend_root).resolve(),set_id,manifest,report)
        elif not integration: report.passed("frontend validation not requested in recognizer-side mode")
        if apps_script_root is not None: check_apps(Path(apps_script_root).resolve(),set_id,p,manifest,projection,report)
        elif not integration: report.passed("Apps Script validation not requested in recognizer-side mode")
    return report.render(manifest.get("displayName") if isinstance(manifest,dict) else None)

def parse_args(argv=None):
    p=argparse.ArgumentParser(description="Validate a Schema v1 set before staging or promotion.")
    p.add_argument("--set",dest="set_id",required=True); p.add_argument("--recognizer-root",type=Path,default=ROOT); p.add_argument("--frontend-root",type=Path); p.add_argument("--apps-script-root",type=Path); p.add_argument("--require-library",action="store_true"); p.add_argument("--integration",action="store_true"); return p.parse_args(argv)
def main(argv=None):
    a=parse_args(argv); return 0 if validate(a.set_id,a.recognizer_root,a.frontend_root,a.apps_script_root,a.require_library,a.integration) else 1
if __name__=="__main__": raise SystemExit(main())
