/* Generated Schema v1 inventory configuration for {display_name}. */

var {apps_constant} =
  Object.freeze({{
    spreadsheetId: {spreadsheet_id_json},
    sheetName: {sheet_name_json},
    setId: {set_id_json},
    canonicalCardPrefix: {canonical_prefix_json},
    legacyCardPrefix: {legacy_prefix_json},
    startRow: {start_row},
    cardCount: {expected_cards},
    numberColumn: {number_column},
    nameColumn: {name_column},
    cardIdColumn: {card_id_column},
    variantColumns: Object.freeze({variant_columns_json})
  }});

function get{pascal_name}InventoryConfig_() {{
  return {apps_constant};
}}
