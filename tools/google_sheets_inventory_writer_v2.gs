/**
 * Generic renderer for Inventory Sheet Plan v2.
 *
 * Renders the standardized bulk-inventory layout used by modern set sheets:
 * logo reserve, live summary boxes, row-12 header, 96px card rows,
 * 001 collector numbers, alternating row shading, and blank/grey unavailable variants.
 *
 * Safety: caller must explicitly provide a spreadsheet ID and a target tab name.
 * The renderer refuses to write to the production-named tab unless
 * allowProductionName=true is passed explicitly.
 */
function renderInventorySheetPlanV2(spreadsheetId, targetSheetName, planJson, options) {
  options = options || {};
  if (!spreadsheetId || !targetSheetName) throw new Error('spreadsheetId and targetSheetName are required.');
  const plan = typeof planJson === 'string' ? JSON.parse(planJson) : planJson;
  if (!plan || plan.inventorySheetPlanVersion !== 2) throw new Error('Inventory Sheet Plan v2 is required.');
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

  const fullRange = sheet.getRange(1, 1, sheet.getMaxRows(), Math.min(sheet.getMaxColumns(), neededCols));
  fullRange.breakApart();
  fullRange.clear({contentsOnly:false});

  // Exact modern dimensions.
  for (const col of plan.columns) sheet.setColumnWidth(col.index, col.widthPx);
  for (let row = plan.rowHeights.topRows.start; row <= plan.rowHeights.topRows.end; row++) {
    sheet.setRowHeight(row, plan.rowHeights.topRows.pixelSize);
  }
  sheet.setRowHeight(plan.rowHeights.header.row, plan.rowHeights.header.pixelSize);
  for (let row = plan.rowHeights.body.start; row <= plan.rowHeights.body.end; row++) {
    sheet.setRowHeight(row, plan.rowHeights.body.pixelSize);
  }

  // Top summary boxes. A1:E10 remains intentionally reserved for the set logo.
  for (const box of plan.summaryBoxes) {
    const labelRange = sheet.getRange(box.labelRange);
    const valueRange = sheet.getRange(box.valueRange);
    labelRange.merge().setValue(box.label);
    valueRange.merge().setFormula(box.formula).setNumberFormat(box.numberFormat);

    [labelRange, valueRange].forEach(range => {
      range
        .setBackgroundRGB(
          Math.round(plan.summaryStyle.backgroundColor.red * 255),
          Math.round(plan.summaryStyle.backgroundColor.green * 255),
          Math.round(plan.summaryStyle.backgroundColor.blue * 255)
        )
        .setFontFamily(plan.summaryStyle.fontFamily)
        .setHorizontalAlignment(plan.summaryStyle.horizontalAlignment.toLowerCase())
        .setVerticalAlignment(plan.summaryStyle.verticalAlignment.toLowerCase())
        .setBorder(true, true, true, true, true, true);
    });
    labelRange
      .setFontSize(plan.summaryStyle.labelFontSize)
      .setFontWeight('normal');
    valueRange
      .setFontSize(plan.summaryStyle.valueFontSize)
      .setFontWeight(plan.summaryStyle.valueBold ? 'bold' : 'normal');
  }

  // Header.
  const headerRange = sheet.getRange(plan.headerRow, 1, 1, neededCols);
  headerRange.setValues([plan.columns.map(c => c.header)]);
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

  // Body values.
  const body = [];
  const backgrounds = [];
  for (let index = 0; index < plan.rows.length; index++) {
    const row = plan.rows[index];
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

    const base = index % 2 === 0 ? plan.bodyStyle.oddRowColor : plan.bodyStyle.evenRowColor;
    const rowColors = Array(neededCols).fill(null).map(() => rgbHex_(base));
    const enabled = {};
    row.inventoryVariants.forEach(v => enabled[v] = true);
    const variantColumns = {
      'normal': 5,
      'reverse-holo': 6,
      'holo': 7,
      'other': 8
    };
    Object.keys(variantColumns).forEach(variant => {
      if (!enabled[variant]) rowColors[variantColumns[variant]] = rgbHex_(plan.bodyStyle.unavailableVariantColor);
    });
    backgrounds.push(rowColors);
  }

  const bodyRange = sheet.getRange(plan.startRow, 1, body.length, neededCols);
  bodyRange.setValues(body);
  bodyRange.setBackgrounds(backgrounds);
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
    rangeWritten: 'A1:Q' + plan.endRow,
    inventorySheetPlanVersion: plan.inventorySheetPlanVersion
  };
}

function rgbHex_(color) {
  const component = value => Math.max(0, Math.min(255, Math.round(value * 255))).toString(16).padStart(2, '0');
  return '#' + component(color.red) + component(color.green) + component(color.blue);
}
