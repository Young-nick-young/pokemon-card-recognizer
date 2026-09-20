#!/usr/bin/env python3
"""Generate a Schema v1 set candidate from one normalized JSON definition.

The generator never deploys production. Recognizer-owned candidate files are
written to an explicit recognizer root. Frontend and Apps Script artifacts are
written either to explicit staging roots or to an isolated generated/<set-id>/
candidate output tree.
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = Path(__file__).resolve().parent / "set_templates"
DEFAULT_VARIANTS = [
    {"variantId":"normal","label":"Normal","inventoryKey":"normal"},
    {"variantId":"reverse-holo","label":"Reverse Holo","inventoryKey":"reverse"},
    {"variantId":"holo","label":"Holo","inventoryKey":"holo"},
    {"variantId":"other","label":"Other","inventoryKey":"other"},
]
DEFAULT_VARIANT_COLUMNS = {"normal":6,"reverse":7,"holo":8,"other":9}
ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")

class ScaffoldError(RuntimeError): pass

def required_text(data, key):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip(): raise ScaffoldError(key + " is required and must be non-empty text.")
    return value.strip()

def required_int(data, key, minimum=1):
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum: raise ScaffoldError(key + " must be an integer >= " + str(minimum) + ".")
    return value

def python_name(set_id): return set_id.replace("-","_").replace(".","_")
def js_constant(name): return re.sub(r"[^A-Za-z0-9]+","_",name).strip("_").upper() or "SCANNER_SET"
def pascal_name(name): return "".join(p[:1].upper()+p[1:] for p in re.split(r"[^A-Za-z0-9]+",name) if p)
def render_template(name, values): return (TEMPLATES/name).read_text(encoding="utf-8").format_map(values)

def write_new(path, content):
    if path.exists(): raise ScaffoldError("Refusing to overwrite existing file: " + str(path))
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content, encoding="utf-8")

def replace_once(path, old, new):
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1: raise ScaffoldError(str(path) + ": expected exactly one registration anchor, found " + str(text.count(old)) + ".")
    path.write_text(text.replace(old,new,1), encoding="utf-8")

def resolve_inventory_variants(source, variant_ids, rarity_rules, number):
    rarity=source.get("rarity")
    if not isinstance(rarity,str) or not rarity.strip():
        raise ScaffoldError("Card "+str(number)+" is missing rarity required for inventory metadata.")
    rarity=rarity.strip()
    selected=source.get("inventory_variants",source.get("inventoryVariants"))
    if selected is None:
        selected=rarity_rules.get(rarity)
    if not isinstance(selected,list) or not selected:
        raise ScaffoldError("Card "+str(number)+" must provide inventory_variants or match an inventory_variant_rules rarity.")
    unknown=[v for v in selected if v not in variant_ids]
    if unknown:
        raise ScaffoldError("Card "+str(number)+" uses undeclared inventory variants: "+", ".join(unknown))
    if len(selected)!=len(set(selected)):
        raise ScaffoldError("Card "+str(number)+" inventory variants contain duplicates.")
    card_type=source.get("card_type",source.get("cardType"))
    if card_type is not None and not isinstance(card_type,str):
        raise ScaffoldError("Card "+str(number)+" card_type must be text or null.")
    return rarity, (card_type.strip() if isinstance(card_type,str) and card_type.strip() else None), list(selected)

def normalize_definition(raw, definition_path):
    name = required_text(raw,"name"); set_id = required_text(raw,"set_id").lower()
    if not ID_PATTERN.fullmatch(set_id): raise ScaffoldError("set_id must be a lowercase Schema v1 identifier.")
    series = required_text(raw,"series"); display_code = required_text(raw,"display_code").upper()
    official_code = required_text(raw,"official_code"); dataset_id = required_text(raw,"dataset_id").lower()
    expected_cards = required_int(raw,"expected_cards"); denominator = required_int(raw,"denominator")
    spreadsheet_id = required_text(raw,"spreadsheet_id"); script_url = required_text(raw,"script_url")
    aliases = raw.get("aliases",[])
    if not isinstance(aliases,list): raise ScaffoldError("aliases must be an array.")
    aliases = [str(v).strip().lower() for v in aliases if str(v).strip()]
    aliases = list(dict.fromkeys(aliases+[set_id.replace("-","_"),display_code.lower(),dataset_id]))
    for alias in aliases:
        if not ID_PATTERN.fullmatch(alias): raise ScaffoldError("Invalid alias: " + repr(alias))
    variants = raw.get("variants",DEFAULT_VARIANTS)
    if not isinstance(variants,list) or not variants: raise ScaffoldError("variants must be a non-empty array.")
    normalized=[]
    for i,v in enumerate(variants):
        if not isinstance(v,dict): raise ScaffoldError("variants["+str(i)+"] must be an object.")
        normalized.append({"variantId":required_text(v,"variantId"),"label":required_text(v,"label"),"inventoryKey":required_text(v,"inventoryKey")})
    if len({v["variantId"] for v in normalized}) != len(normalized): raise ScaffoldError("Variant IDs must be unique.")
    columns = raw.get("variant_columns",DEFAULT_VARIANT_COLUMNS)
    if not isinstance(columns,dict): raise ScaffoldError("variant_columns must be an object.")
    for v in normalized:
        col=columns.get(v["inventoryKey"])
        if isinstance(col,bool) or not isinstance(col,int) or col<1: raise ScaffoldError("Missing valid variant column for inventoryKey " + repr(v["inventoryKey"]) + ".")
    cards = raw.get("cards")
    if cards is None:
        cards_file=raw.get("cards_file")
        if not isinstance(cards_file,str) or not cards_file.strip(): raise ScaffoldError("Provide either cards or cards_file in the normalized definition.")
        cards=json.loads((definition_path.parent/cards_file).resolve().read_text(encoding="utf-8"))
    if isinstance(cards,dict) and "cards" in cards: cards=cards["cards"]
    if not isinstance(cards,list): raise ScaffoldError("Card source must be an array (or an object containing cards).")
    if len(cards)!=expected_cards: raise ScaffoldError("Card source contains "+str(len(cards))+" records; expected "+str(expected_cards)+".")
    rarity_rules=raw.get("inventory_variant_rules",{})
    if not isinstance(rarity_rules,dict): raise ScaffoldError("inventory_variant_rules must be an object when provided.")
    return {
        "display_name":name,"set_id":set_id,"series":series,"display_code":display_code,"official_code":official_code,
        "dataset_id":dataset_id,"expected_cards":expected_cards,"denominator":denominator,"aliases":aliases,
        "variants":normalized,"variant_columns":columns,"cards":cards,"spreadsheet_id":spreadsheet_id,"inventory_variant_rules":rarity_rules,
        "sheet_name":str(raw.get("sheet_name") or name).strip(),"script_url":script_url,
        "canonical_prefix":str(raw.get("canonical_card_prefix") or display_code.lower()+"-"),
        "legacy_prefix":str(raw.get("legacy_card_prefix") or display_code.upper()+"-"),
        "start_row":int(raw.get("start_row",13)),"number_column":int(raw.get("number_column",2)),
        "name_column":int(raw.get("name_column",3)),"card_id_column":int(raw.get("card_id_column",17)),
        "inventory_set_id_param":bool(raw.get("inventory_set_id_param",True)),
        "destination_key":str(raw.get("destination_key") or set_id+"-inventory"),
    }

def build_schema_files(c):
    denom=str(c["denominator"]).zfill(3)
    manifest={"schemaVersion":"1.0","manifestVersion":1,"setId":c["set_id"],"displayName":c["display_name"],"language":"en","market":"international","aliases":c["aliases"],
      "externalIds":{"displayCode":c["display_code"],"officialCode":c["official_code"],"pokemonTcgData":c["dataset_id"]},
      "collections":[{"collectionId":"main","label":"Main Set"}],"numberingNamespaces":[{"namespaceId":"main","label":"Main and Secret Cards","denominator":denom}],
      "variants":c["variants"],"catalogue":{"path":"cards.json","expectedRecords":c["expected_cards"]},
      "inventory":{"destinationKey":c["destination_key"],"sheetName":c["sheet_name"],"startRow":c["start_row"],"cardIdColumn":c["card_id_column"],"quantityColumns":c["variant_columns"]}}
    variant_ids=[v["variantId"] for v in c["variants"]]; cards=[]; inventory_cards=[]
    for expected, source in enumerate(c["cards"],start=1):
        if not isinstance(source,dict): raise ScaffoldError("Card record "+str(expected)+" must be an object.")
        number=source.get("number",expected)
        if number!=expected: raise ScaffoldError("Card source must be contiguous and ordered; expected number "+str(expected)+", found "+repr(number)+".")
        name=required_text(source,"name"); image=source.get("reference_image",source.get("referenceImage"))
        if not isinstance(image,str) or not image.strip(): raise ScaffoldError("Card "+str(number)+" is missing reference_image.")
        selected=source.get("variants",variant_ids)
        if not isinstance(selected,list) or not selected: raise ScaffoldError("Card "+str(number)+" variants must be a non-empty array.")
        unknown=[v for v in selected if v not in variant_ids]
        if unknown: raise ScaffoldError("Card "+str(number)+" uses undeclared variants: "+", ".join(unknown))
        card_id=c["canonical_prefix"]+str(number).zfill(3)
        cards.append({"cardId":card_id,"collectionId":"main","number":{"namespaceId":"main","display":str(number).zfill(3)+"/"+denom,"sortKey":number},"name":name,"referenceImage":image.strip(),"variants":selected,
          "externalIds":{"pokemonTcgData":str(source.get("external_id") or c["dataset_id"]+"-"+str(number)),"legacyInventoryCardId":c["legacy_prefix"]+str(number).zfill(3)}})
        rarity,card_type,inventory_variants=resolve_inventory_variants(source,variant_ids,c["inventory_variant_rules"],number)
        inventory_cards.append({"cardId":card_id,"rarity":rarity,"cardType":card_type,"inventoryVariants":inventory_variants})
    metadata={"inventoryMetadataVersion":1,"setId":c["set_id"],"source":{"kind":"generated","note":"Explicit physical inventory availability generated by Scaffold + Validator v1."},"cards":inventory_cards}
    return manifest,{"schemaVersion":"1.0","setId":c["set_id"],"cards":cards},metadata

def values(c):
    p=python_name(c["set_id"]); j=js_constant(c["display_name"])
    return {"display_name":c["display_name"],"display_name_repr":repr(c["display_name"]),"display_name_json":json.dumps(c["display_name"]),"set_id_repr":repr(c["set_id"]),"set_id_json":json.dumps(c["set_id"]),"display_code_repr":repr(c["display_code"]),"display_code_json":json.dumps(c["display_code"]),"official_code_json":json.dumps(c["official_code"]),"dataset_id_repr":repr(c["dataset_id"]),"dataset_id_json":json.dumps(c["dataset_id"]),"series_json":json.dumps(c["series"]),"expected_cards":c["expected_cards"],"denominator":c["denominator"],"canonical_prefix_repr":repr(c["canonical_prefix"]),"canonical_prefix_json":json.dumps(c["canonical_prefix"]),"legacy_prefix_repr":repr(c["legacy_prefix"]),"legacy_prefix_json":json.dumps(c["legacy_prefix"]),"python_name":p,"js_constant":j,"apps_constant":j+"_INVENTORY_CONFIG","pascal_name":pascal_name(c["display_name"]),"script_url_json":json.dumps(c["script_url"]),"inventory_set_id_param":"true" if c["inventory_set_id_param"] else "false","variant_labels_json":json.dumps([v["label"] for v in c["variants"]]),"variant_columns_json":json.dumps({v["variantId"]:c["variant_columns"][v["inventoryKey"]] for v in c["variants"]}),"spreadsheet_id_json":json.dumps(c["spreadsheet_id"]),"sheet_name_json":json.dumps(c["sheet_name"]),"start_row":c["start_row"],"number_column":c["number_column"],"name_column":c["name_column"],"card_id_column":c["card_id_column"],"package_route_json":json.dumps("/api/v1/sets/"+c["set_id"]+"/package")}

def register_build(root,c,p):
    path=root/"schema_v1_builds.json"; data=json.loads(path.read_text(encoding="utf-8")); entries=data.get("sets")
    if not isinstance(entries,list): raise ScaffoldError("schema_v1_builds.json has no sets array.")
    if any(isinstance(v,dict) and v.get("setId")==c["set_id"] for v in entries): raise ScaffoldError("Build registry already contains "+c["set_id"]+".")
    entries.append({"setId":c["set_id"],"package":"sets/"+p,"expectedRecords":c["expected_cards"],"output":"sets/"+p+"/card_library.pkl"}); path.write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")

def register_frontend(frontend_root,c):
    path=frontend_root/"index.html"; marker='<script src="./js/set-selector.js"></script>'; addition='<script src="./js/sets/'+c["set_id"]+'.js"></script>\n'; replace_once(path,marker,addition+marker)

def register_router(root,c,p):
    path=root/"main.py"; text=path.read_text(encoding="utf-8"); module=p; symbol="build_"+p+"_public_package"
    recognizer_import="from sets."+p+" import recognizer as "+module+"\n"; package_import="from sets."+p+".public_package import (\n    build_public_package as "+symbol+"\n)\n"
    anchor="\n\n# =========================================================\n# SCHEMA V1 SHADOW LOAD"
    if text.count(anchor)!=1: raise ScaffoldError("main.py import anchor changed; refusing router edit.")
    text=text.replace(anchor,"\n"+recognizer_import+package_import+anchor,1)
    anchor="\n}\n\n\nSET_ALIASES = {"
    if text.count(anchor)!=1: raise ScaffoldError("main.py RECOGNIZERS anchor changed; refusing router edit.")
    text=text.replace(anchor,',\n    '+json.dumps(c["set_id"])+': '+module+anchor,1)
    anchor="\n}\n\n\nactive_set_id = None"
    if text.count(anchor)!=1: raise ScaffoldError("main.py SET_ALIASES anchor changed; refusing router edit.")
    lines=["    "+json.dumps(a)+": "+json.dumps(c["set_id"]) for a in dict.fromkeys([c["set_id"]]+c["aliases"])]
    text=text.replace(anchor,",\n"+",\n".join(lines)+anchor,1)
    root_anchor="\n        }\n    }\n\n\n# =========================================================\n# PUBLIC SET PACKAGE"
    if text.count(root_anchor)!=1: raise ScaffoldError("main.py root-status anchor changed; refusing router edit.")
    text=text.replace(root_anchor,",\n\n            "+json.dumps(c["set_id"])+":\n                "+module+".get_status()"+root_anchor,1)
    route_anchor="\n\n# =========================================================\n# SET STATUS"
    if text.count(route_anchor)!=1: raise ScaffoldError("main.py package-route anchor changed; refusing router edit.")
    route="\n\n@app.get("+json.dumps("/api/v1/sets/"+c["set_id"]+"/package")+")\ndef "+p+"_public_package():\n    try:\n        return "+symbol+"()\n    except Exception as error:\n        print("+json.dumps(c["display_name"]+" public package unavailable:")+", error)\n        raise HTTPException(status_code=503, detail={\"error\": \"Public set package unavailable\", \"set\": "+json.dumps(c["set_id"])+"}) from error\n"
    path.write_text(text.replace(route_anchor,route+route_anchor,1),encoding="utf-8")

def generate(definition_path, recognizer_root=ROOT, frontend_root=None, apps_script_root=None, candidate_output_root=None):
    definition_path=Path(definition_path).resolve(); recognizer_root=Path(recognizer_root).resolve()
    raw=json.loads(definition_path.read_text(encoding="utf-8"))
    if not isinstance(raw,dict): raise ScaffoldError("Definition root must be an object.")
    c=normalize_definition(raw,definition_path); manifest,catalogue,inventory_metadata=build_schema_files(c); v=values(c); p=python_name(c["set_id"])
    output_root=Path(candidate_output_root).resolve() if candidate_output_root else recognizer_root/"generated"/c["set_id"]
    effective_frontend=Path(frontend_root).resolve() if frontend_root else output_root/"frontend"
    effective_apps=Path(apps_script_root).resolve() if apps_script_root else output_root/"apps_script"
    package=recognizer_root/"sets"/p
    write_new(package/"manifest.json",json.dumps(manifest,indent=2)+"\n"); write_new(package/"cards.json",json.dumps(catalogue,indent=2)+"\n"); write_new(package/"inventory_metadata.json",json.dumps(inventory_metadata,indent=2)+"\n")
    write_new(package/"runtime_metadata.py",render_template("runtime_metadata.py.tpl",v)); write_new(package/"recognizer.py",render_template("recognizer.py.tpl",v)); write_new(package/"public_package.py",render_template("public_package.py.tpl",v))
    write_new(effective_frontend/"js"/"sets"/(c["set_id"]+".js"),render_template("frontend_set.js.tpl",v))
    if frontend_root is not None: register_frontend(effective_frontend,c)
    write_new(effective_apps/(p+"_config.gs"),render_template("apps_script_config.gs.tpl",v))
    register_build(recognizer_root,c,p); register_router(recognizer_root,c,p)
    print("Generated Schema v1 candidate:",c["display_name"]); print("Set ID:",c["set_id"]); print("Cards:",c["expected_cards"]); print("Series:",c["series"])
    print("Frontend candidate:",effective_frontend); print("Apps Script candidate:",effective_apps); return c

def parse_args(argv=None):
    parser=argparse.ArgumentParser(description="Generate a new Schema v1 scanner set candidate.")
    parser.add_argument("definition",type=Path); parser.add_argument("--recognizer-root",type=Path,default=ROOT)
    parser.add_argument("--frontend-root",type=Path); parser.add_argument("--apps-script-root",type=Path); parser.add_argument("--candidate-output-root",type=Path)
    return parser.parse_args(argv)

def main(argv=None):
    args=parse_args(argv)
    try: generate(args.definition,args.recognizer_root,args.frontend_root,args.apps_script_root,args.candidate_output_root)
    except (OSError,ValueError,json.JSONDecodeError,ScaffoldError) as error: print("FAIL:",error,file=sys.stderr); return 1
    return 0
if __name__=="__main__": raise SystemExit(main())
