const SET_30TH_CELEBRATION = Object.freeze({
  id: "30th-celebration",
  name: "30th Celebration",
  setCode: "30C",
  series: "Mega Evolution",
  officialCode: "30C",
  datasetId: "me55",
  denominator: 128,
  maxCard: 161,
  imageSet: null,
  scriptUrl: "https://script.google.com/a/macros/ikns.edu.bh/s/AKfycbxzaDPrnUX_a8P7UXxAQ-lWCCbJ9RG_kiXzvUfERWk41cCDhdY5yIr8S1PK9CAD10vv/exec",
  inventorySetIdParam: true,
  variants: ["Normal", "Reverse Holo", "Holo", "Other"],
  dynamicVariants: false,
  schemaPackageUrl:
    RECOGNIZER_URL +
    "/api/v1/sets/30th-celebration/package"
});

SetRegistry.register(
  SET_30TH_CELEBRATION
);
