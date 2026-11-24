const SET_30TH_CLASSIC_COLLECTION = Object.freeze({
  id: "30th-c",
  name: "30th Classic Collection",
  setCode: "30CC",
  series: "Mega Evolution",
  officialCode: "30C",
  datasetId: "me55c",
  denominator: 30,
  maxCard: 30,
  imageSet: null,
  scriptUrl: "https://script.google.com/a/macros/ikns.edu.bh/s/AKfycbxzaDPrnUX_a8P7UXxAQ-lWCCbJ9RG_kiXzvUfERWk41cCDhdY5yIr8S1PK9CAD10vv/exec",
  inventorySetIdParam: true,
  variants: ["Normal", "Reverse Holo", "Holo", "Other"],
  dynamicVariants: false,
  schemaPackageUrl:
    RECOGNIZER_URL +
    "/api/v1/sets/30th-c/package"
});

SetRegistry.register(
  SET_30TH_CLASSIC_COLLECTION
);
