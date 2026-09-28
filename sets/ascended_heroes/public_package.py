"""Read-only public projection of the Ascended Heroes Schema v1 package."""
from pathlib import Path
from schema_v1_loader import SchemaV1ValidationError, load_schema_v1_package
PACKAGE_DIRECTORY=Path(__file__).parent; EXPECTED_SET_ID="ascended-heroes"
def build_public_package(package_directory=PACKAGE_DIRECTORY):
    package=load_schema_v1_package(package_directory)
    if package.set_id!=EXPECTED_SET_ID: raise SchemaV1ValidationError(package_directory,["manifest.setId: expected "+repr(EXPECTED_SET_ID)+", found "+repr(package.set_id)])
    m=package.manifest; ordered=sorted(package.cards,key=lambda c:(c["number"]["sortKey"],c["cardId"]))
    return {"schemaVersion":m["schemaVersion"],"setId":m["setId"],"displayName":m["displayName"],"language":m["language"],
      "variants":[{"variantId":v["variantId"],"label":v["label"]} for v in m["variants"]],
      "cards":[{"cardId":c["cardId"],"legacyInventoryCardId":c["externalIds"]["legacyInventoryCardId"],"number":c["number"]["display"],"name":c["name"],"referenceImage":c["referenceImage"],"variants":list(c["variants"])} for c in ordered]}
