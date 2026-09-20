/**
 * Generic renderer for Inventory Sheet Plan v1.
 * Contains no Pokémon/set business rules. It renders an already validated plan.
 *
 * Safety: caller must explicitly provide a spreadsheet ID and a target tab name.
 * This helper refuses to write when targetSheetName equals plan.sheetName unless
 * allowProductionName is explicitly true.
 */
function renderInventorySheetPlan(spreadsheetId, targetSheetName, planJson, options) {
  options = options || {};
  if (!spreadsheetId || !targetSheetName) throw new Error('spreadsheetId and targetSheetName are required.');
  const plan = typeof planJson === 'string' ? JSON.parse(planJson) : planJson;
  if (!plan || plan.inventorySheetPlanVersion !== 1) throw new Error('Inventory Sheet Plan v1 is required.');
  if (targetSheetName === plan.sheetName && options.allowProductionName !== true) {
    throw new Error('Refusing to write to the production-named tab without allowProductionName=true.');
  }

  const ss = SpreadsheetApp.openById(spreadsheetId);
  let sheet = ss.getSheetByName(targetSheetName);
  if (!sheet) sheet = ss.insertSheet(targetSheetName);

  const neededRows = Math.max(plan.endRow, 20);
  const neededCols = plan.columns.length;
  if (sheet.getMaxRows() < neededRows) sheet.insertRowsAfter(sheet.getMaxRows(), neededRows - sheet.getMaxRows());
  if (sheet.getMaxColumns() < neededCols) sheet.insertColumnsAfter(sheet.getMaxColumns(), neededCols - sheet.getMaxColumns());

  sheet.getRange(1, 1, sheet.getMaxRows(), Math.min(sheet.getMaxColumns(), neededCols)).clear({contentsOnly:false});

  const headerValues = [plan.columns.map(c => c.header)];
  const headerRange = sheet.getRange(plan.headerRow, 1, 1, neededCols);
  headerRange.setValues(headerValues);
  headerRange
    .setFontFamily(plan.headerStyle.fontFamily)
    .setFontSize(plan.headerStyle.fontSize)
    .setFontWeight(plan.headerStyle.bold ? 'bold' : 'normal')
    .setHorizontalAlignment(plan.headerStyle.horizontalAlignment.toLowerCase())
    .setVerticalAlignment(plan.headerStyle.verticalAlignment.toLowerCase())
    .setWrap(true)
    .setBackgroundRGB(
      Math.round(plan.headerStyle.backgroundColor.red * 255),
      Math.round(plan.headerStyle.backgroundColor.green * 255),
      Math.round(plan.headerStyle.backgroundColor.blue * 255)
    )
    .setFontColorRGB(
      Math.round(plan.headerStyle.foregroundColor.red * 255),
      Math.round(plan.headerStyle.foregroundColor.green * 255),
      Math.round(plan.headerStyle.foregroundColor.blue * 255)
    );

  const body = [];
  for (const row of plan.rows) {
    const v = row.values;
    body.push([
      v.imageFormula,
      v.collectorNumber,
      v.name,
      v.rarity,
      v.cardType,
      v.normalQty,
      v.reverseHoloQty,
      v.holoQty,
      v.otherQty,
      v.totalFormula,
      v.normalPriceBhd,
      v.reversePriceBhd,
      v.holoPriceBhd,
      v.otherPriceBhd,
      v.collectionValueFormula,
      v.storageLocation,
      v.compatibilityCardId
    ]);
  }
  const bodyRange = sheet.getRange(plan.startRow, 1, body.length, neededCols);
  bodyRange.setValues(body);
  bodyRange
    .setFontFamily(plan.bodyStyle.fontFamily)
    .setFontSize(plan.bodyStyle.fontSize)
    .setVerticalAlignment(plan.bodyStyle.verticalAlignment.toLowerCase())
    .setFontColorRGB(
      Math.round(plan.bodyStyle.foregroundColor.red * 255),
      Math.round(plan.bodyStyle.foregroundColor.green * 255),
      Math.round(plan.bodyStyle.foregroundColor.blue * 255)
    );

  for (const col of plan.columns) {
    sheet.setColumnWidth(col.index, col.widthPx);
    const range = sheet.getRange(plan.startRow, col.index, body.length, 1);
    if (col.alignment) range.setHorizontalAlignment(col.alignment.toLowerCase());
    if (col.numberFormat) range.setNumberFormat(col.numberFormat);
  }
  sheet.setFrozenRows(plan.freezeRows);

  SpreadsheetApp.flush();
  return {
    spreadsheetId: spreadsheetId,
    sheetName: targetSheetName,
    rowsWritten: body.length,
    rangeWritten: 'A' + plan.headerRow + ':Q' + plan.endRow
  };
}
