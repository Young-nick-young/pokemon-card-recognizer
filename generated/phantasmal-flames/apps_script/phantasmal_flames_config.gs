const PHANTASMAL_FLAMES_INVENTORY_CONFIG = Object.freeze({
  spreadsheetId: "1EsYzX-JqWqzksqaOBrvn6xu6RnIzWhqNJhcW2UQAKsE",
  sheetName: "Phantasmal Flames",
  setId: "phantasmal-flames",
  canonicalCardPrefix: "pfl-",
  legacyCardPrefix: "PFL-",
  startRow: 13,
  cardCount: 130,
  numberColumn: 2,
  nameColumn: 3,
  cardIdColumn: 17,
  variantColumns: Object.freeze({
    "normal": 6,
    "reverse-holo": 7,
    "holo": 8,
    "other": 9
  })
});

function getPhantasmalFlamesInventoryConfig_() {
  return PHANTASMAL_FLAMES_INVENTORY_CONFIG;
}
