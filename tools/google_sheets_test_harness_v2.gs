/**
 * Safe test harness for Inventory Sheet Plan v2.
 *
 * Creates/refreshes only a TEST_-prefixed tab, renders the plan with the
 * existing writer, reads the result back independently, and compares the
 * important values to the plan. It never writes to the production-named tab.
 */
function runInventorySheetPlanV2Test(spreadsheetId, planJson, options) {
  options = options || {};
  const plan = typeof planJson === 'string' ? JSON.parse(planJson) : planJson;
  if (!plan || plan.inventorySheetPlanVersion !== 2) {
    throw new Error('Inventory Sheet Plan v2 is required.');
  }

  const safeSetId = String(plan.setId || plan.sheetName || 'set')
    .replace(/[^A-Za-z0-9_-]+/g, '_');
  const testSheetName = options.testSheetName || ('TEST_' + safeSetId);

  if (testSheetName.indexOf('TEST_') !== 0) {
    throw new Error('Test sheet name must begin with TEST_.');
  }
  if (testSheetName === plan.sheetName) {
    throw new Error('Test sheet must not use the production sheet name.');
  }

  const renderResult = renderInventorySheetPlanV2(
    spreadsheetId,
    testSheetName,
    plan,
    {allowProductionName: false}
  );

  const snapshot = snapshotInventorySheetPlanV2_(
    spreadsheetId,
    testSheetName,
    plan
  );

  const errors = compareInventorySheetPlanV2Snapshot_(plan, snapshot);

  return {
    status: errors.length === 0 ? 'PASS' : 'FAIL',
    productionTouched: false,
    spreadsheetId: spreadsheetId,
    testSheetName: testSheetName,
    rowsWritten: renderResult.rowsWritten,
    snapshot: snapshot,
    errors: errors
  };
}

function snapshotInventorySheetPlanV2_(spreadsheetId, sheetName, plan) {
  if (sheetName.indexOf('TEST_') !== 0) {
    throw new Error('Snapshot is restricted to TEST_-prefixed sheets.');
  }

  const ss = SpreadsheetApp.openById(spreadsheetId);
  const sheet = ss.getSheetByName(sheetName);
  if (!sheet) throw new Error('Test sheet not found: ' + sheetName);

  const headers = sheet
    .getRange(plan.headerRow, 1, 1, plan.columns.length)
    .getValues()[0];

  const columnWidths = plan.columns.map(c => sheet.getColumnWidth(c.index));

  const rowHeights = {
    topRows: {
      start: plan.rowHeights.topRows.start,
      end: plan.rowHeights.topRows.end,
      pixelSize: sheet.getRowHeight(plan.rowHeights.topRows.start)
    },
    header: {
      row: plan.rowHeights.header.row,
      pixelSize: sheet.getRowHeight(plan.rowHeights.header.row)
    },
    body: {
      start: plan.rowHeights.body.start,
      end: plan.rowHeights.body.end,
      pixelSize: sheet.getRowHeight(plan.rowHeights.body.start)
    }
  };

  const summaryBoxes = plan.summaryBoxes.map(box => ({
    label: sheet.getRange(box.labelRange).getDisplayValue(),
    labelRange: box.labelRange,
    valueRange: box.valueRange,
    formula: sheet.getRange(box.valueRange).getFormula(),
    numberFormat: sheet.getRange(box.valueRange).getNumberFormat()
  }));

  const rows = [];
  for (let i = 0; i < plan.rows.length; i++) {
    const expected = plan.rows[i];
    const rowNumber = expected.row;
    const values = sheet.getRange(rowNumber, 1, 1, plan.columns.length).getValues()[0];

    const inventoryVariants = [];
    if (values[5] !== '') inventoryVariants.push('normal');
    if (values[6] !== '') inventoryVariants.push('reverse-holo');
    if (values[7] !== '') inventoryVariants.push('holo');
    if (values[8] !== '') inventoryVariants.push('other');

    rows.push({
      row: rowNumber,
      inventoryVariants: inventoryVariants,
      values: {
        collectorNumber: values[1],
        name: values[2],
        rarity: values[3],
        cardType: values[4] === '' ? null : values[4],
        normalQty: values[5] === '' ? null : values[5],
        reverseHoloQty: values[6] === '' ? null : values[6],
        holoQty: values[7] === '' ? null : values[7],
        otherQty: values[8] === '' ? null : values[8],
        compatibilityCardId: values[16]
      }
    });
  }

  return {
    sheetName: sheetName,
    freezeRows: sheet.getFrozenRows(),
    logoRange: plan.logoRange,
    headers: headers,
    columnWidths: columnWidths,
    rowHeights: rowHeights,
    summaryBoxes: summaryBoxes,
    rows: rows
  };
}

function compareInventorySheetPlanV2Snapshot_(plan, snapshot) {
  const errors = [];

  if (snapshot.freezeRows !== plan.freezeRows) {
    errors.push('Frozen row count mismatch.');
  }
  if (JSON.stringify(snapshot.headers) !==
      JSON.stringify(plan.columns.map(c => c.header))) {
    errors.push('Header values mismatch.');
  }
  if (JSON.stringify(snapshot.columnWidths) !==
      JSON.stringify(plan.columns.map(c => c.widthPx))) {
    errors.push('Column widths mismatch.');
  }
  if (JSON.stringify(snapshot.rowHeights) !== JSON.stringify(plan.rowHeights)) {
    errors.push('Row heights mismatch.');
  }
  if (snapshot.rows.length !== plan.rows.length) {
    errors.push('Read-back row count mismatch.');
    return errors;
  }

  for (let i = 0; i < plan.rows.length; i++) {
    const expected = plan.rows[i];
    const actual = snapshot.rows[i];

    if (actual.row !== expected.row) {
      errors.push('Row ' + expected.row + ': row coordinate mismatch.');
      continue;
    }
    if (JSON.stringify(actual.inventoryVariants) !==
        JSON.stringify(expected.inventoryVariants)) {
      errors.push('Row ' + expected.row + ': variant availability mismatch.');
    }

    const keys = [
      'collectorNumber', 'name', 'rarity', 'cardType',
      'normalQty', 'reverseHoloQty', 'holoQty', 'otherQty',
      'compatibilityCardId'
    ];
    keys.forEach(key => {
      if (actual.values[key] !== expected.values[key]) {
        errors.push('Row ' + expected.row + ': ' + key + ' mismatch.');
      }
    });
  }

  for (let i = 0; i < plan.summaryBoxes.length; i++) {
    const expected = plan.summaryBoxes[i];
    const actual = snapshot.summaryBoxes[i];
    if (!actual ||
        actual.label !== expected.label ||
        actual.labelRange !== expected.labelRange ||
        actual.valueRange !== expected.valueRange ||
        actual.formula !== expected.formula ||
        actual.numberFormat !== expected.numberFormat) {
      errors.push('Summary box mismatch: ' + expected.label);
    }
  }

  return errors;
}
