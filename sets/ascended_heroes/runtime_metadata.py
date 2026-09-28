"""Schema v1 runtime metadata for Ascended Heroes."""
from dataclasses import dataclass
from pathlib import Path
from schema_v1_loader import load_schema_v1_package
DEFAULT_PACKAGE_DIRECTORY=Path(__file__).resolve().parent
EXPECTED_SET_ID="ascended-heroes"; EXPECTED_DISPLAY_CODE="ASC"; EXPECTED_COUNT=295
@dataclass(frozen=True)
class RuntimeCardMetadata:
    number:int; display_number:str; reference_image:str; card_id:str; legacy_card_id:str; name:str
@dataclass(frozen=True)
class AscendedHeroesRuntimeMetadata:
    source:str; set_id:str; set_code:str; set_name:str; card_count:int; cards_by_number:dict
def load_runtime_metadata(package_directory=DEFAULT_PACKAGE_DIRECTORY):
    package=load_schema_v1_package(package_directory)
    if package.set_id!=EXPECTED_SET_ID: raise RuntimeError(f"Expected setId {EXPECTED_SET_ID!r}, found {package.set_id!r}.")
    manifest=package.manifest; code=(manifest.get("externalIds") or {}).get("displayCode")
    if code!=EXPECTED_DISPLAY_CODE: raise RuntimeError(f"Expected displayCode {EXPECTED_DISPLAY_CODE!r}, found {code!r}.")
    denoms={x["namespaceId"]:x.get("denominator") for x in manifest["numberingNamespaces"]}; by={}
    for card in package.cards:
        n=int(card["number"]["sortKey"]); canonical="asc-"+str(n).zfill(3); legacy="ASC-"+str(n).zfill(3)
        if card["cardId"]!=canonical: raise RuntimeError(f"Collector number {n} must use canonical cardId {canonical!r}.")
        actual=(card.get("externalIds") or {}).get("legacyInventoryCardId")
        if actual!=legacy: raise RuntimeError(f"{canonical} must use legacyInventoryCardId {legacy!r}.")
        d=denoms.get(card["number"]["namespaceId"])
        if not d: raise RuntimeError("Ascended Heroes numbering namespace requires a denominator.")
        if n in by: raise RuntimeError(f"Duplicate collector number {n}.")
        by[n]=RuntimeCardMetadata(n,f"{n}/{d}",card["referenceImage"],canonical,legacy,card["name"])
    if list(by)!=list(range(1,EXPECTED_COUNT+1)): raise RuntimeError("Ascended Heroes Schema v1 runtime metadata must remain ordered 1 through 295.")
    return AscendedHeroesRuntimeMetadata("schema-v1",package.set_id,code,manifest["displayName"],len(package.cards),by)
