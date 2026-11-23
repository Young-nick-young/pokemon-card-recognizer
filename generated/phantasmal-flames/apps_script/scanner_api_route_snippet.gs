/*
 * Candidate routing block for the existing shared ScannerAPI.gs project.
 * Insert alongside the existing Schema v1 set routes.
 */
if (requestedSetId === "phantasmal-flames") {
  const config = getPhantasmalFlamesInventoryConfig_();

  if (api === "cards") {
    return getSchemaV1InventoryCards_(config);
  }

  if (api === "changeQuantity") {
    return changeSchemaV1InventoryQuantity_(config, params);
  }
}
