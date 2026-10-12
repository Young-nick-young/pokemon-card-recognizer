#!/usr/bin/env python3
"""Stage 2 Google Sheets read-only validation primitives.

This module contains only:
- construction of bounded read plans from the locked baseline;
- loading per-card inventory availability from accepted inventory metadata /
  Sheet Plan artifacts;
- normalization/comparison of read-only Sheet observations.

Stage 2A intentionally contains no Google client, OAuth flow, HTTP client, or
live Sheet access. A later Stage 2B transport may implement only the
ReadOnlySheetsReader protocol with read-only Google scopes.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

PASS = "PASS"
FAIL = "FAIL"
NOT_VERIFIED = "NOT VERIFIED"

_SECRET_PATTERNS = (
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)(access[_-]?token|refresh[_-]?token|id[_-]?token|token|credential|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r'(?i)"(access_token|refresh_token|id_token|token|credential|secret)"\s*:\s*"[^"]*"'),
)


class Stage2AError(RuntimeError):
    """Base Stage 2A error."""


class AuthorityUnavailable(Stage2AError):
    """No accepted inventory authority artifact is available."""


class ConfigurationError(Stage2AError):
    """Locked baseline or authority structure is inconsistent."""


class ReadEvidenceUnavailable(Stage2AError):
    """Mock/live read evidence could not be obtained."""


class AuthenticationUnavailable(ReadEvidenceUnavailable):
    """Read-only authentication is unavailable."""


class ReadOnlySheetsReader(Protocol):
    """Minimal future-facing read-only transport contract."""

    def get_spreadsheet_metadata(self, spreadsheet_id: str, sheet_name: str) -> dict[str, Any]:
        ...

    def batch_get_values(self, spreadsheet_id: str, ranges: Sequence[str]) -> dict[str, list[list[Any]]]:
        ...


@dataclass(frozen=True)
class SheetReadPlan:
    set_id: str
    workbook_key: str
    spreadsheet_id: str
    expected_title: str
    sheet_name: str
    sheet_id: int
    start_row: int
    end_row: int
    expected_count: int
    collector_column: int
    name_column: int
    card_id_column: int
    variant_columns: dict[str, int]
    identity_range: str
    card_id_range: str
    variant_range: str

    @property
    def ranges(self) -> tuple[str, str, str]:
        return (self.identity_range, self.card_id_range, self.variant_range)


@dataclass(frozen=True)
class InventoryAuthority:
    set_id: str
    source_path: str
    source_kind: str
    variants_by_index: tuple[frozenset[str], ...]


@dataclass(frozen=True)
class ExpectedIdentity:
    collector_number: str
    name: str
    canonical_id: str
    legacy_id: str


@dataclass(frozen=True)
class SheetFinding:
    status: str
    check: str
    component: str
    reason: str
    expected: Any = None
    actual: Any = None
    impact: str = "data safety"
    blocks_production: bool = False

    def report_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "check": self.check,
            "component": self.component,
            "reason": sanitize_for_report(self.reason),
            "expected": sanitize_for_report(self.expected),
            "actual": sanitize_for_report(self.actual),
            "impact": self.impact,
            "blocksProduction": self.blocks_production,
        }


def sanitize_for_report(value: Any) -> Any:
    """Redact token/credential-shaped text recursively before reporting."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            key_text = str(key)
            if re.search(r"(?i)(token|credential|secret|authorization)", key_text):
                result[key_text] = "[REDACTED]"
            else:
                result[key_text] = sanitize_for_report(item)
        return result
    if isinstance(value, (list, tuple)):
        return [sanitize_for_report(item) for item in value]
    if not isinstance(value, str):
        return value
    text = value
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def column_letter(index: int) -> str:
    if isinstance(index, bool) or not isinstance(index, int) or index < 1:
        raise ConfigurationError(f"Invalid 1-based Sheet column index: {index!r}")
    result = ""
    value = index
    while value:
        value, rem = divmod(value - 1, 26)
        result = chr(65 + rem) + result
    return result


def quote_sheet_name(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def bounded_range(sheet_name: str, start_col: int, start_row: int, end_col: int, end_row: int) -> str:
    if start_row < 1 or end_row < start_row or end_col < start_col:
        raise ConfigurationError("Invalid bounded Sheet range coordinates.")
    return (
        f"{quote_sheet_name(sheet_name)}!"
        f"{column_letter(start_col)}{start_row}:{column_letter(end_col)}{end_row}"
    )


def _expected_layout_model(set_id: str) -> tuple[int, tuple[int, ...]]:
    if set_id == "ascended-heroes":
        return 20, (7, 8, 9, 10, 11)  # T and G:K
    return 17, (6, 7, 8, 9)  # Q and F:I


def build_read_plan(baseline: dict[str, Any], set_id: str) -> SheetReadPlan:
    sets = baseline.get("sets") or {}
    if set_id not in sets:
        raise ConfigurationError(f"Set {set_id!r} is absent from the locked baseline.")
    set_data = sets[set_id]
    inv = set_data.get("inventoryExpectedOffline") or {}
    workbook_key = inv.get("workbookKey")
    workbook = (baseline.get("workbooks") or {}).get(workbook_key)
    if not isinstance(workbook, dict):
        raise ConfigurationError(f"{set_id}: workbook key {workbook_key!r} is not defined.")

    start_row = inv.get("startRow")
    end_row = inv.get("endRow")
    expected_count = set_data.get("expectedCardCount")
    if end_row - start_row + 1 != expected_count:
        raise ConfigurationError(
            f"{set_id}: bounded production row count does not equal expectedCardCount."
        )

    collector_col = inv.get("collectorNumberColumn")
    name_col = inv.get("nameColumn")
    card_id_col = inv.get("cardIdColumn")
    variants = inv.get("variantColumns")
    if not isinstance(variants, dict) or not variants:
        raise ConfigurationError(f"{set_id}: variantColumns are missing.")

    expected_card_id_col, expected_variant_cols = _expected_layout_model(set_id)
    actual_variant_cols = tuple(variants.values())
    if card_id_col != expected_card_id_col or actual_variant_cols != expected_variant_cols:
        model = "ASC A:T / G:K / T" if set_id == "ascended-heroes" else "standard F:I / Q"
        raise ConfigurationError(
            f"{set_id}: locked inventory layout no longer matches accepted {model} structure."
        )
    if collector_col != 2 or name_col != 3:
        raise ConfigurationError(f"{set_id}: identity columns must remain B:C.")

    sheet_name = inv.get("sheetName")
    variant_min = min(actual_variant_cols)
    variant_max = max(actual_variant_cols)
    return SheetReadPlan(
        set_id=set_id,
        workbook_key=workbook_key,
        spreadsheet_id=workbook["expectedSpreadsheetId"],
        expected_title=workbook["expectedTitle"],
        sheet_name=sheet_name,
        sheet_id=int(inv["sheetId"]),
        start_row=int(start_row),
        end_row=int(end_row),
        expected_count=int(expected_count),
        collector_column=int(collector_col),
        name_column=int(name_col),
        card_id_column=int(card_id_col),
        variant_columns={str(key): int(value) for key, value in variants.items()},
        identity_range=bounded_range(sheet_name, collector_col, start_row, name_col, end_row),
        card_id_range=bounded_range(sheet_name, card_id_col, start_row, card_id_col, end_row),
        variant_range=bounded_range(sheet_name, variant_min, start_row, variant_max, end_row),
    )


def _normalize_authority_variant(value: str) -> str:
    # Accepted ASC metadata/Sheet Plan uses energy/reverse-holo while the
    # locked validator baseline uses energy-reverse-holo. This is nomenclature
    # normalization only; it does not infer availability.
    return str(value).strip().lower().replace("/", "-")


def load_inventory_authority(
    recognizer_root: Path,
    baseline: dict[str, Any],
    set_id: str,
) -> InventoryAuthority:
    set_data = baseline["sets"][set_id]
    package = recognizer_root / set_data["schema"]["packagePath"]
    expected_count = int(set_data["expectedCardCount"])
    declared = set(set_data["variantRulesExpectedOffline"]["variants"])

    plan_path = package / "inventory_sheet_plan.json"
    metadata_path = package / "inventory_metadata.json"

    source_path: Path
    source_kind: str
    rows: list[Any]

    if plan_path.is_file():
        data = _load_json(plan_path)
        if data.get("setId") != set_id:
            raise ConfigurationError(f"{set_id}: Sheet Plan setId mismatch.")
        rows = data.get("rows")
        source_path = plan_path
        source_kind = "inventory_sheet_plan"
    elif metadata_path.is_file():
        data = _load_json(metadata_path)
        if data.get("setId") != set_id:
            raise ConfigurationError(f"{set_id}: inventory metadata setId mismatch.")
        rows = data.get("cards")
        source_path = metadata_path
        source_kind = "inventory_metadata"
    else:
        raise AuthorityUnavailable(
            f"{set_id}: no inventory_sheet_plan.json or inventory_metadata.json authority artifact."
        )

    if not isinstance(rows, list) or len(rows) != expected_count:
        raise ConfigurationError(
            f"{set_id}: inventory authority must contain exactly {expected_count} card records."
        )

    result: list[frozenset[str]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ConfigurationError(f"{set_id}: authority record {index} is not an object.")
        values = row.get("inventoryVariants")
        if not isinstance(values, list):
            raise ConfigurationError(
                f"{set_id}: authority record {index} lacks explicit inventoryVariants."
            )
        normalized = frozenset(_normalize_authority_variant(v) for v in values)
        unknown = sorted(normalized - declared)
        if unknown:
            raise ConfigurationError(
                f"{set_id}: authority record {index} has undeclared inventory variants {unknown}."
            )
        result.append(normalized)

    return InventoryAuthority(
        set_id=set_id,
        source_path=str(source_path),
        source_kind=source_kind,
        variants_by_index=tuple(result),
    )


def load_expected_identities(
    recognizer_root: Path,
    baseline: dict[str, Any],
    set_id: str,
) -> tuple[ExpectedIdentity, ...]:
    set_data = baseline["sets"][set_id]
    cards_path = recognizer_root / set_data["schema"]["cardsPath"]
    data = _load_json(cards_path)
    cards = data.get("cards") if isinstance(data, dict) else None
    if not isinstance(cards, list) or len(cards) != set_data["expectedCardCount"]:
        raise ConfigurationError(f"{set_id}: cards catalogue count mismatch.")

    identities: list[ExpectedIdentity] = []
    for card in cards:
        number = card.get("number") or {}
        display = str(number.get("display") or "")
        collector = display.split("/", 1)[0]
        external = card.get("externalIds") or {}
        identities.append(
            ExpectedIdentity(
                collector_number=normalize_collector(collector),
                name=str(card.get("name") or ""),
                canonical_id=str(card.get("cardId") or ""),
                legacy_id=str(external.get("legacyInventoryCardId") or ""),
            )
        )
    return tuple(identities)


def normalize_collector(value: Any) -> str:
    if isinstance(value, bool):
        raise ValueError("boolean is not a collector number")
    if isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    else:
        text = str(value).strip()
        if not re.fullmatch(r"\d+", text):
            raise ValueError(f"invalid collector number {value!r}")
        number = int(text)
    if number < 0:
        raise ValueError("collector number cannot be negative")
    return f"{number:03d}"


def normalize_quantity(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("boolean is not a quantity")
    if isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    elif isinstance(value, str) and re.fullmatch(r"\d+", value.strip()):
        number = int(value.strip())
    else:
        raise ValueError(f"quantity must be a non-negative integer, got {value!r}")
    if number < 0:
        raise ValueError("quantity cannot be negative")
    return number


def _pad_rows(rows: list[list[Any]], width: int, count: int) -> list[list[Any]]:
    normalized: list[list[Any]] = []
    for row in rows:
        values = list(row) if isinstance(row, list) else []
        normalized.append((values + [None] * width)[:width])
    while len(normalized) < count:
        normalized.append([None] * width)
    return normalized


def _finding(
    status: str,
    check: str,
    component: str,
    reason: str,
    *,
    expected: Any = None,
    actual: Any = None,
    impact: str = "data safety",
    blocks: bool = False,
) -> SheetFinding:
    return SheetFinding(
        status=status,
        check=check,
        component=component,
        reason=reason,
        expected=expected,
        actual=actual,
        impact=impact,
        blocks_production=blocks,
    )


def read_snapshot(
    reader: ReadOnlySheetsReader,
    plan: SheetReadPlan,
) -> tuple[dict[str, Any], dict[str, list[list[Any]]]]:
    metadata = reader.get_spreadsheet_metadata(plan.spreadsheet_id, plan.sheet_name)
    values = reader.batch_get_values(plan.spreadsheet_id, plan.ranges)
    if not isinstance(metadata, dict) or not isinstance(values, dict):
        raise ReadEvidenceUnavailable("Sheet reader returned malformed read evidence.")
    return metadata, values


def compare_snapshot(
    plan: SheetReadPlan,
    authority: InventoryAuthority,
    identities: Sequence[ExpectedIdentity],
    metadata: dict[str, Any],
    values_by_range: dict[str, list[list[Any]]],
) -> list[SheetFinding]:
    findings: list[SheetFinding] = []

    def compare(check: str, component: str, expected: Any, actual: Any, impact: str = "data safety") -> None:
        if actual == expected:
            findings.append(_finding(PASS, check, component, "Matches expected live Sheet contract.", expected=expected, actual=actual, impact=impact))
        else:
            findings.append(_finding(FAIL, check, component, "Live Sheet evidence differs from the accepted contract.", expected=expected, actual=actual, impact=impact, blocks=True))

    compare("workbook identifier", "Google Sheet metadata", plan.spreadsheet_id, metadata.get("spreadsheetId"), "maintenance / data safety")
    compare("workbook title", "Google Sheet metadata", plan.expected_title, metadata.get("title"), "maintenance")
    sheet = metadata.get("sheet") or {}
    compare("sheet/tab name", "Google Sheet metadata", plan.sheet_name, sheet.get("title"))
    compare("sheet/tab ID", "Google Sheet metadata", plan.sheet_id, sheet.get("sheetId"), "maintenance / data safety")

    missing_ranges = [rng for rng in plan.ranges if rng not in values_by_range]
    if missing_ranges:
        findings.append(_finding(
            NOT_VERIFIED,
            "bounded Sheet evidence",
            "Google Sheet values",
            "One or more required bounded read ranges were not returned.",
            expected=list(plan.ranges),
            actual={"missingRanges": missing_ranges},
            impact="data safety",
            blocks=False,
        ))
        return findings

    identity_rows_raw = values_by_range[plan.identity_range]
    card_id_rows_raw = values_by_range[plan.card_id_range]
    variant_rows_raw = values_by_range[plan.variant_range]

    compare("identity row count", "Google Sheet values", plan.expected_count, len(identity_rows_raw))
    compare("Card ID row count", "Google Sheet values", plan.expected_count, len(card_id_rows_raw))
    compare("variant row count", "Google Sheet values", plan.expected_count, len(variant_rows_raw))

    identity_rows = _pad_rows(identity_rows_raw, 2, plan.expected_count)
    card_id_rows = _pad_rows(card_id_rows_raw, 1, plan.expected_count)
    variant_width = max(plan.variant_columns.values()) - min(plan.variant_columns.values()) + 1
    variant_rows = _pad_rows(variant_rows_raw, variant_width, plan.expected_count)

    actual_ids: list[str] = []
    actual_collectors: list[str | None] = []

    variant_min = min(plan.variant_columns.values())
    variant_offsets = {variant: col - variant_min for variant, col in plan.variant_columns.items()}

    for index in range(plan.expected_count):
        expected_identity = identities[index]
        sheet_row = plan.start_row + index
        identity = identity_rows[index]
        card_id = card_id_rows[index][0]

        try:
            collector = normalize_collector(identity[0])
        except Exception:
            collector = None
        actual_collectors.append(collector)
        actual_id = "" if card_id is None else str(card_id).strip()
        actual_ids.append(actual_id)

        if collector != expected_identity.collector_number:
            findings.append(_finding(
                FAIL,
                f"row {sheet_row} collector number",
                plan.identity_range,
                "Collector number is missing, malformed, duplicated, shifted, or out of order.",
                expected=expected_identity.collector_number,
                actual=identity[0],
                blocks=True,
            ))
        if str(identity[1] or "") != expected_identity.name:
            findings.append(_finding(
                FAIL,
                f"row {sheet_row} card name",
                plan.identity_range,
                "Card name does not match the accepted identity at this row.",
                expected=expected_identity.name,
                actual=identity[1],
                blocks=True,
            ))
        if actual_id != expected_identity.legacy_id:
            findings.append(_finding(
                FAIL,
                f"row {sheet_row} legacy Card ID",
                plan.card_id_range,
                "Legacy inventory Card ID does not match the accepted identity at this row.",
                expected=expected_identity.legacy_id,
                actual=actual_id,
                blocks=True,
            ))

        available = authority.variants_by_index[index]
        row_values = variant_rows[index]
        for variant, offset in variant_offsets.items():
            raw = row_values[offset]
            is_available = variant in available
            try:
                quantity = normalize_quantity(raw)
            except ValueError as error:
                findings.append(_finding(
                    FAIL,
                    f"row {sheet_row} variant {variant}",
                    plan.variant_range,
                    "Variant quantity is malformed.",
                    expected="blank if unavailable; non-negative integer if available",
                    actual=str(error),
                    blocks=True,
                ))
                continue

            if is_available and quantity is None:
                findings.append(_finding(
                    FAIL,
                    f"row {sheet_row} variant {variant}",
                    plan.variant_range,
                    "Available inventory variant is blank; blank means unavailable.",
                    expected="0 or positive integer",
                    actual="blank",
                    blocks=True,
                ))
            elif not is_available and quantity is not None:
                findings.append(_finding(
                    FAIL,
                    f"row {sheet_row} variant {variant}",
                    plan.variant_range,
                    "Unavailable inventory variant must remain blank.",
                    expected="blank",
                    actual=quantity,
                    blocks=True,
                ))

    if len(set(actual_ids)) != len(actual_ids):
        findings.append(_finding(
            FAIL,
            "duplicate legacy Card IDs",
            plan.card_id_range,
            "Duplicate legacy inventory Card IDs were found.",
            expected="all unique",
            actual=actual_ids,
            blocks=True,
        ))
    if "" in actual_ids:
        findings.append(_finding(
            FAIL,
            "missing legacy Card IDs",
            plan.card_id_range,
            "One or more legacy inventory Card IDs are blank.",
            expected="no blanks",
            actual=actual_ids,
            blocks=True,
        ))
    if None in actual_collectors or len(set(actual_collectors)) != len(actual_collectors):
        findings.append(_finding(
            FAIL,
            "collector-number sequence uniqueness",
            plan.identity_range,
            "Collector numbers contain blanks/malformed values or duplicates.",
            expected=[f"{i:03d}" for i in range(1, plan.expected_count + 1)],
            actual=actual_collectors,
            blocks=True,
        ))

    if identities:
        compare(
            "first live identity",
            "Google Sheet values",
            {
                "collectorNumber": identities[0].collector_number,
                "name": identities[0].name,
                "legacyCardId": identities[0].legacy_id,
            },
            {
                "collectorNumber": actual_collectors[0],
                "name": identity_rows[0][1],
                "legacyCardId": actual_ids[0],
            },
        )
        compare(
            "last live identity",
            "Google Sheet values",
            {
                "collectorNumber": identities[-1].collector_number,
                "name": identities[-1].name,
                "legacyCardId": identities[-1].legacy_id,
            },
            {
                "collectorNumber": actual_collectors[-1],
                "name": identity_rows[-1][1],
                "legacyCardId": actual_ids[-1],
            },
        )

    if not any(f.status == FAIL for f in findings):
        findings.append(_finding(
            PASS,
            "variant availability representation",
            plan.variant_range,
            "Every live variant cell matches the explicit per-card inventory authority: blank=unavailable; zero/positive=available.",
            expected=authority.source_kind,
            actual=authority.source_path,
            impact="data safety",
        ))

    return findings


def validate_with_reader(
    reader: ReadOnlySheetsReader,
    recognizer_root: Path,
    baseline: dict[str, Any],
    set_id: str,
) -> list[SheetFinding]:
    """Read and compare one set. Read/auth absence becomes NOT VERIFIED."""
    try:
        plan = build_read_plan(baseline, set_id)
        authority = load_inventory_authority(recognizer_root, baseline, set_id)
        identities = load_expected_identities(recognizer_root, baseline, set_id)
        metadata, values = read_snapshot(reader, plan)
        return compare_snapshot(plan, authority, identities, metadata, values)
    except AuthorityUnavailable as error:
        return [_finding(
            NOT_VERIFIED,
            "inventory availability authority",
            "inventory metadata / Sheet Plan",
            "Accepted per-card inventory availability evidence is unavailable.",
            expected="inventory_sheet_plan.json or inventory_metadata.json",
            actual=sanitize_for_report(str(error)),
            impact="data safety",
            blocks=False,
        )]
    except AuthenticationUnavailable:
        return [_finding(
            NOT_VERIFIED,
            "Google Sheets authentication",
            "read-only Sheet adapter",
            "Read-only authentication evidence is unavailable.",
            expected="read-only credential supplied outside repository",
            actual="authentication unavailable",
            impact="verification",
            blocks=False,
        )]
    except ReadEvidenceUnavailable:
        return [_finding(
            NOT_VERIFIED,
            "Google Sheets read evidence",
            "read-only Sheet adapter",
            "Google Sheets read evidence is unavailable.",
            expected="bounded read response",
            actual="read unavailable",
            impact="verification",
            blocks=False,
        )]


def overall_status(findings: Sequence[SheetFinding]) -> str:
    if any(f.status == FAIL for f in findings):
        return FAIL
    if any(f.status == NOT_VERIFIED for f in findings):
        return NOT_VERIFIED
    return PASS
