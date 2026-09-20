const CHAOS_RISING = Object.freeze({
  id: "chaos-rising",
  name: "Chaos Rising",
  setCode: "CRI",
  series: "Mega Evolution",
  officialCode: "ME04",
  datasetId: "me4",
  denominator: 86,
  maxCard: 122,
  imageSet: null,
  scriptUrl: "https://script.google.com/a/macros/ikns.edu.bh/s/AKfycbxzaDPrnUX_a8P7UXxAQ-lWCCbJ9RG_kiXzvUfERWk41cCDhdY5yIr8S1PK9CAD10vv/exec",
  inventorySetIdParam: true,
  variants: ["Normal","Reverse Holo","Holo","Other"],
  dynamicVariants: false,
  schemaPackageUrl:
    RECOGNIZER_URL +
    "/api/v1/sets/chaos-rising/package"
});

SetRegistry.register(
  CHAOS_RISING
);
