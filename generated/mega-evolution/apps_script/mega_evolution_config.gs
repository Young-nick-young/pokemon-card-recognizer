const MEGA_EVOLUTION_INVENTORY_CONFIG = Object.freeze({
  spreadsheetId: "1EsYzX-JqWqzksqaOBrvn6xu6RnIzWhqNJhcW2UQAKsE",
  sheetName: "Mega Evolution",
  setId: "mega-evolution",
  canonicalCardPrefix: "meg-",
  legacyCardPrefix: "MEG-",
  startRow: 13,
  cardCount: 188,
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

function getMegaEvolutionInventoryConfig_() {
  return MEGA_EVOLUTION_INVENTORY_CONFIG;
}
