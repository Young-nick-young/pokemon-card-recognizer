#!/usr/bin/env python3
"""Offline/read-only production baseline validator for the Pokémon Inventory Scanner.

Stage 1B only:
- reads local recognizer/frontend repository files;
- compares them with tools/production_baseline_v1.json;
- never accesses Google Sheets, Render, Apps Script, or recognizer HTTP endpoints;
- never writes, repairs, deploys, or mutates production.

A successful offline result is not a full production PASS. Live external systems
remain explicitly NOT VERIFIED until later approved stages.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
DEFAULT_RECOGNIZER_ROOT = HERE.parent
DEFAULT_BASELINE = HERE / "production_baseline_v1.json"

PASS = "PASS"
WARNING = "WARNING"
FAIL = "FAIL"
NOT_VERIFIED = "NOT VERIFIED"


@dataclass(frozen=True)
class Finding:
    status: str
    check: str
    component: str
    message: str
    expected: Any = None
    actual: Any = None
    impact: str = "maintenance"
    blocks_production: bool = False
    set_id: str | None = None
    scope: str = "offline"

    def detail_lines(self) -> list[str]:
        lines = [
            f"  {self.status}: {self.check}",
            f"    Component: {self.component}",
            f"    Reason: {self.message}",
        ]
        if self.expected is not None:
            lines.append(f"    Expected: {format_value(self.expected)}")
        if self.actual is not None:
            lines.append(f"    Actual: {format_value(self.actual)}")
        lines.extend(
            [
                f"    Impact: {self.impact}",
                "    Blocks production: " + ("YES" if self.blocks_production else "NO"),
            ]
        )
        return lines


def format_value(value: Any) -> str:
    if isinstance(value, (dict, list, tuple, set)):
        if isinstance(value, set):
            value = sorted(value)
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def add(
    findings: list[Finding],
    status: str,
    check: str,
    component: str,
    message: str,
    *,
    expected: Any = None,
    actual: Any = None,
    impact: str = "maintenance",
    blocks: bool = False,
    set_id: str | None = None,
    scope: str = "offline",
) -> None:
    findings.append(
        Finding(
            status=status,
            check=check,
            component=component,
            message=message,
            expected=expected,
            actual=actual,
            impact=impact,
            blocks_production=blocks,
            set_id=set_id,
            scope=scope,
        )
    )


def compare(
    findings: list[Finding],
    *,
    check: str,
    component: str,
    expected: Any,
    actual: Any,
    set_id: str | None = None,
    impact: str = "maintenance",
    fail_message: str | None = None,
) -> bool:
    if actual == expected:
        add(
            findings,
            PASS,
            check,
            component,
            "Matches locked baseline.",
            expected=expected,
            actual=actual,
            set_id=set_id,
        )
        return True
    add(
        findings,
        FAIL,
        check,
        component,
        fail_message or "Observed repository state differs from the locked baseline.",
        expected=expected,
        actual=actual,
        impact=impact,
        blocks=True,
        set_id=set_id,
    )
    return False


def extract_js_string(text: str, key: str) -> str | None:
    match = re.search(r"\b" + re.escape(key) + r'\s*:\s*"([^"]*)"', text)
    return match.group(1) if match else None


def extract_js_int(text: str, key: str) -> int | None:
    match = re.search(r"\b" + re.escape(key) + r"\s*:\s*(\d+)\b", text)
    return int(match.group(1)) if match else None


def extract_js_bool(text: str, key: str) -> bool | None:
    match = re.search(r"\b" + re.escape(key) + r"\s*:\s*(true|false)\b", text)
    if not match:
        return None
    return match.group(1) == "true"


def extract_js_script_url(text: str) -> str | None:
    match = re.search(
        r'\bscriptUrl\s*:\s*(?:\n\s*)?"([^"]+)"',
        text,
        flags=re.MULTILINE,
    )
    return match.group(1) if match else None


def js_has_property(text: str, key: str) -> bool:
    return re.search(r"\b" + re.escape(key) + r"\s*:", text) is not None


def discover_manifest_set_ids(recognizer_root: Path) -> tuple[set[str], list[str]]:
    discovered: set[str] = set()
    errors: list[str] = []
    sets_root = recognizer_root / "sets"
    if not sets_root.is_dir():
        return discovered, [f"Missing sets directory: {sets_root}"]
    for path in sorted(sets_root.glob("*/manifest.json")):
        try:
            data = load_json(path)
            set_id = data.get("setId") if isinstance(data, dict) else None
            if isinstance(set_id, str) and set_id:
                discovered.add(set_id)
            else:
                errors.append(f"{path}: missing setId")
        except Exception as error:
            errors.append(f"{path}: {error}")
    return discovered, errors


def ast_literal_dict_assignment(tree: ast.AST, name: str) -> dict[Any, Any] | None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            continue
        if not isinstance(node.value, ast.Dict):
            return None
        result: dict[Any, Any] = {}
        for key, value in zip(node.value.keys, node.value.values):
            try:
                k = ast.literal_eval(key)
            except Exception:
                continue
            if isinstance(value, ast.Name):
                result[k] = value.id
            else:
                try:
                    result[k] = ast.literal_eval(value)
                except Exception:
                    result[k] = None
        return result
    return None


def extract_fastapi_get_routes(tree: ast.AST) -> set[str]:
    routes: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            if not isinstance(deco, ast.Call) or not deco.args:
                continue
            func = deco.func
            if not (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and isinstance(func.value, ast.Name)
                and func.value.id == "app"
            ):
                continue
            try:
                route = ast.literal_eval(deco.args[0])
            except Exception:
                continue
            if isinstance(route, str):
                routes.add(route)
    return routes


def parse_router(recognizer_root: Path, findings: list[Finding]) -> tuple[set[str], dict[str, str], set[str]]:
    path = recognizer_root / "main.py"
    try:
        text = read_text(path)
        tree = ast.parse(text, filename=str(path))
    except Exception as error:
        add(
            findings,
            FAIL,
            "recognizer router parse",
            "recognizer/main.py",
            f"Could not parse recognizer router: {error}",
            impact="scanning now",
            blocks=True,
        )
        return set(), {}, set()

    recognizers_raw = ast_literal_dict_assignment(tree, "RECOGNIZERS") or {}
    aliases_raw = ast_literal_dict_assignment(tree, "SET_ALIASES") or {}
    recognizers = {str(key) for key in recognizers_raw if isinstance(key, str)}
    aliases = {
        str(key): str(value)
        for key, value in aliases_raw.items()
        if isinstance(key, str) and isinstance(value, str)
    }
    routes = extract_fastapi_get_routes(tree)
    return recognizers, aliases, routes


def load_builder_registry(recognizer_root: Path, findings: list[Finding]) -> list[dict[str, Any]]:
    path = recognizer_root / "schema_v1_builds.json"
    try:
        data = load_json(path)
    except Exception as error:
        add(
            findings,
            FAIL,
            "shared builder registry",
            "recognizer/schema_v1_builds.json",
            f"Could not read registry: {error}",
            impact="scaling / scanning now",
            blocks=True,
        )
        return []
    sets = data.get("sets") if isinstance(data, dict) else None
    if not isinstance(sets, list):
        add(
            findings,
            FAIL,
            "shared builder registry",
            "recognizer/schema_v1_builds.json",
            "Registry does not contain a sets array.",
            expected="sets array",
            actual=type(sets).__name__,
            impact="scaling / scanning now",
            blocks=True,
        )
        return []
    return [entry for entry in sets if isinstance(entry, dict)]


def check_manifest_and_cards(
    recognizer_root: Path,
    baseline_set: dict[str, Any],
    set_id: str,
    findings: list[Finding],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    schema = baseline_set["schema"]
    manifest_path = recognizer_root / schema["manifestPath"]
    cards_path = recognizer_root / schema["cardsPath"]

    try:
        manifest = load_json(manifest_path)
    except Exception as error:
        add(
            findings,
            FAIL,
            "Schema v1 manifest readable",
            str(manifest_path),
            f"Manifest unavailable or malformed: {error}",
            impact="scanning now / scaling",
            blocks=True,
            set_id=set_id,
        )
        return None, None

    try:
        catalogue = load_json(cards_path)
    except Exception as error:
        add(
            findings,
            FAIL,
            "Schema v1 cards readable",
            str(cards_path),
            f"Cards catalogue unavailable or malformed: {error}",
            impact="scanning now / data safety",
            blocks=True,
            set_id=set_id,
        )
        return manifest, None

    try:
        sys.path.insert(0, str(recognizer_root))
        from schema_v1_loader import load_schema_v1_package
        load_schema_v1_package(recognizer_root / schema["packagePath"])
    except Exception as error:
        add(
            findings,
            FAIL,
            "existing Schema v1 loader validation",
            "recognizer/schema_v1_loader.py",
            f"Existing strict Schema v1 loader rejected the package: {error}",
            impact="scanning now / scaling",
            blocks=True,
            set_id=set_id,
        )
    else:
        add(
            findings,
            PASS,
            "existing Schema v1 loader validation",
            "recognizer/schema_v1_loader.py",
            "Existing strict Schema v1 loader accepted the local package.",
            set_id=set_id,
        )
    finally:
        if sys.path and sys.path[0] == str(recognizer_root):
            sys.path.pop(0)

    compare(
        findings,
        check="manifest schemaVersion",
        component="Schema v1 manifest",
        expected=schema["expectedSchemaVersion"],
        actual=manifest.get("schemaVersion"),
        set_id=set_id,
        impact="maintenance / scaling",
    )
    compare(
        findings,
        check="manifest setId",
        component="Schema v1 manifest",
        expected=set_id,
        actual=manifest.get("setId"),
        set_id=set_id,
        impact="scanning now / scaling",
    )
    compare(
        findings,
        check="manifest displayName",
        component="Schema v1 manifest",
        expected=baseline_set["displayName"],
        actual=manifest.get("displayName"),
        set_id=set_id,
    )

    external = manifest.get("externalIds") or {}
    compare(
        findings,
        check="manifest display code",
        component="Schema v1 manifest",
        expected=baseline_set["setCode"],
        actual=external.get("displayCode"),
        set_id=set_id,
    )
    compare(
        findings,
        check="manifest aliases",
        component="Schema v1 manifest",
        expected=schema.get("expectedAliases", []),
        actual=manifest.get("aliases", []),
        set_id=set_id,
        impact="scanning now / maintenance",
    )
    if "expectedOfficialCode" in schema:
        compare(
            findings,
            check="manifest officialCode",
            component="Schema v1 manifest",
            expected=schema["expectedOfficialCode"],
            actual=external.get("officialCode"),
            set_id=set_id,
        )
    if "expectedDatasetId" in schema:
        compare(
            findings,
            check="manifest datasetId",
            component="Schema v1 manifest",
            expected=schema["expectedDatasetId"],
            actual=external.get("pokemonTcgData"),
            set_id=set_id,
        )

    namespaces = manifest.get("numberingNamespaces") or []
    actual_denominator = None
    if namespaces and isinstance(namespaces[0], dict):
        raw = namespaces[0].get("denominator")
        try:
            actual_denominator = int(raw)
        except (TypeError, ValueError):
            actual_denominator = None
    compare(
        findings,
        check="manifest display denominator",
        component="Schema v1 manifest",
        expected=schema["expectedDisplayDenominator"],
        actual=actual_denominator,
        set_id=set_id,
    )

    expected_count = baseline_set["expectedCardCount"]
    compare(
        findings,
        check="manifest expected card count",
        component="Schema v1 manifest",
        expected=expected_count,
        actual=(manifest.get("catalogue") or {}).get("expectedRecords"),
        set_id=set_id,
        impact="scanning now / scaling",
    )

    compare(
        findings,
        check="cards schemaVersion",
        component="Schema v1 cards",
        expected=schema["expectedSchemaVersion"],
        actual=catalogue.get("schemaVersion") if isinstance(catalogue, dict) else None,
        set_id=set_id,
        impact="maintenance / scaling",
    )
    compare(
        findings,
        check="cards setId",
        component="Schema v1 cards",
        expected=set_id,
        actual=catalogue.get("setId") if isinstance(catalogue, dict) else None,
        set_id=set_id,
        impact="scanning now / data safety",
    )

    cards = catalogue.get("cards") if isinstance(catalogue, dict) else None
    if not isinstance(cards, list):
        add(
            findings,
            FAIL,
            "cards array",
            "Schema v1 cards",
            "cards.json does not contain a cards array.",
            expected="array",
            actual=type(cards).__name__,
            impact="scanning now / data safety",
            blocks=True,
            set_id=set_id,
        )
        return manifest, catalogue

    compare(
        findings,
        check="catalogue card count",
        component="Schema v1 cards",
        expected=expected_count,
        actual=len(cards),
        set_id=set_id,
        impact="scanning now / data safety",
    )

    canonical = [card.get("cardId") for card in cards if isinstance(card, dict)]
    expected_canonical = [
        f"{baseline_set['canonicalIds']['prefix']}{number:03d}"
        for number in range(1, expected_count + 1)
    ]
    compare(
        findings,
        check="canonical ID sequence",
        component="Schema v1 cards",
        expected=expected_canonical,
        actual=canonical,
        set_id=set_id,
        impact="scanning now / data safety",
        fail_message="Canonical IDs are missing, duplicated, out of order, or differ from the locked sequence.",
    )

    legacy = [
        (card.get("externalIds") or {}).get("legacyInventoryCardId")
        for card in cards
        if isinstance(card, dict)
    ]
    expected_legacy = [
        f"{baseline_set['legacyInventoryIdsExpectedOffline']['prefix']}{number:03d}"
        for number in range(1, expected_count + 1)
    ]
    compare(
        findings,
        check="expected legacy inventory ID sequence (offline)",
        component="Schema v1 cards",
        expected=expected_legacy,
        actual=legacy,
        set_id=set_id,
        impact="data safety",
        fail_message=(
            "Repository/schema legacy IDs differ from the locked expected sequence. "
            "This is an offline expectation check only; live Sheet IDs are Stage 2."
        ),
    )
    add(
        findings,
        NOT_VERIFIED,
        "actual live Sheet rows / collector numbers / legacy IDs",
        "Google Sheet",
        "Stage 1B does not read the live inventory Sheet.",
        expected={
            "sheetName": baseline_set["inventoryExpectedOffline"]["sheetName"],
            "startRow": baseline_set["inventoryExpectedOffline"]["startRow"],
            "endRow": baseline_set["inventoryExpectedOffline"]["endRow"],
            "legacyFirst": baseline_set["legacyInventoryIdsExpectedOffline"]["first"],
            "legacyLast": baseline_set["legacyInventoryIdsExpectedOffline"]["last"],
        },
        actual="Not accessed in Stage 1B",
        impact="data safety / scanning now",
        blocks=False,
        set_id=set_id,
        scope="external",
    )

    sort_keys = [
        (card.get("number") or {}).get("sortKey")
        for card in cards
        if isinstance(card, dict)
    ]
    compare(
        findings,
        check="collector sortKey sequence",
        component="Schema v1 cards",
        expected=list(range(1, expected_count + 1)),
        actual=sort_keys,
        set_id=set_id,
        impact="scanning now / data safety",
    )

    if cards:
        for boundary_name, index in (("first", 0), ("last", -1)):
            expected_boundary = baseline_set["identityBoundaries"][boundary_name]
            card = cards[index]
            actual_boundary = {
                "sortKey": (card.get("number") or {}).get("sortKey"),
                "collectorNumber": str((card.get("number") or {}).get("display", "")).split("/")[0],
                "canonicalId": card.get("cardId"),
                "legacyInventoryIdExpectedOffline": (card.get("externalIds") or {}).get(
                    "legacyInventoryCardId"
                ),
                "name": card.get("name"),
            }
            compare(
                findings,
                check=f"{boundary_name} card identity",
                component="Schema v1 cards",
                expected=expected_boundary,
                actual=actual_boundary,
                set_id=set_id,
                impact="scanning now / data safety",
            )

    check_inventory_expected_offline(manifest, baseline_set, set_id, findings)
    check_variant_rules_expected_offline(manifest, baseline_set, set_id, findings)
    return manifest, catalogue


def check_inventory_expected_offline(
    manifest: dict[str, Any],
    baseline_set: dict[str, Any],
    set_id: str,
    findings: list[Finding],
) -> None:
    expected = baseline_set["inventoryExpectedOffline"]
    actual = manifest.get("inventory") or {}

    compare(
        findings,
        check="expected inventory sheet name (offline)",
        component="Schema v1 manifest inventory config",
        expected=expected["sheetName"],
        actual=actual.get("sheetName"),
        set_id=set_id,
        impact="data safety / maintenance",
    )
    compare(
        findings,
        check="expected inventory start row (offline)",
        component="Schema v1 manifest inventory config",
        expected=expected["startRow"],
        actual=actual.get("startRow"),
        set_id=set_id,
        impact="data safety",
    )
    compare(
        findings,
        check="expected inventory Card ID column (offline)",
        component="Schema v1 manifest inventory config",
        expected=expected["cardIdColumn"],
        actual=actual.get("cardIdColumn"),
        set_id=set_id,
        impact="data safety",
    )

    variant_defs = manifest.get("variants") or []
    inventory_key_by_variant = {
        item.get("variantId"): item.get("inventoryKey")
        for item in variant_defs
        if isinstance(item, dict)
    }
    quantity_columns = actual.get("quantityColumns") or {}
    normalized_columns = {
        variant_id: quantity_columns.get(inventory_key_by_variant.get(variant_id))
        for variant_id in expected["variantColumns"]
    }
    compare(
        findings,
        check="expected variant column mapping (offline)",
        component="Schema v1 manifest inventory config",
        expected=expected["variantColumns"],
        actual=normalized_columns,
        set_id=set_id,
        impact="data safety",
    )


def check_variant_rules_expected_offline(
    manifest: dict[str, Any],
    baseline_set: dict[str, Any],
    set_id: str,
    findings: list[Finding],
) -> None:
    expected = baseline_set["variantRulesExpectedOffline"]
    actual_variants = [
        item.get("variantId")
        for item in (manifest.get("variants") or [])
        if isinstance(item, dict)
    ]
    compare(
        findings,
        check="expected variant model (offline)",
        component="Schema v1 manifest",
        expected=expected["variants"],
        actual=actual_variants,
        set_id=set_id,
        impact="data safety / maintenance",
    )
    add(
        findings,
        NOT_VERIFIED,
        "live unavailable-variant safety",
        "Google Sheet / deployed Apps Script",
        (
            "Stage 1B validates only the expected offline variant model. "
            "Actual live blank-cell/unavailable-variant safety is deferred to Stage 2 or later."
        ),
        expected="Independent live verification",
        actual="Not accessed in Stage 1B",
        impact="data safety",
        blocks=False,
        set_id=set_id,
        scope="external",
    )


def check_builder(
    entries: list[dict[str, Any]],
    baseline_set: dict[str, Any],
    set_id: str,
    findings: list[Finding],
) -> None:
    matches = [entry for entry in entries if entry.get("setId") == set_id]
    if len(matches) != 1:
        add(
            findings,
            FAIL,
            "shared builder registration",
            "recognizer/schema_v1_builds.json",
            "Set must appear exactly once in the shared builder registry.",
            expected=1,
            actual=len(matches),
            impact="scanning now / scaling",
            blocks=True,
            set_id=set_id,
        )
        return
    actual = matches[0]
    expected = baseline_set["builder"]
    actual_subset = {
        "registrySetId": actual.get("setId"),
        "package": actual.get("package"),
        "expectedRecords": actual.get("expectedRecords"),
        "output": actual.get("output"),
    }
    compare(
        findings,
        check="shared builder registration",
        component="recognizer/schema_v1_builds.json",
        expected=expected,
        actual=actual_subset,
        set_id=set_id,
        impact="scanning now / scaling",
    )


def check_router_for_set(
    recognizer_set_ids: set[str],
    aliases: dict[str, str],
    routes: set[str],
    baseline_set: dict[str, Any],
    set_id: str,
    findings: list[Finding],
) -> None:
    compare(
        findings,
        check="recognizer router registration",
        component="recognizer/main.py",
        expected=True,
        actual=set_id in recognizer_set_ids,
        set_id=set_id,
        impact="scanning now",
    )
    manifest_aliases = baseline_set["schema"].get("expectedAliases", [])
    expected_alias_map = {alias: set_id for alias in [set_id, *manifest_aliases]}
    actual_alias_map = {alias: aliases.get(alias) for alias in expected_alias_map}
    compare(
        findings,
        check="recognizer aliases",
        component="recognizer/main.py",
        expected=expected_alias_map,
        actual=actual_alias_map,
        set_id=set_id,
        impact="scanning now / maintenance",
    )
    expected_public_route = baseline_set["recognizer"]["publicPackageRoute"]
    compare(
        findings,
        check="public package route",
        component="recognizer/main.py",
        expected=True,
        actual=expected_public_route in routes,
        set_id=set_id,
        impact="scanning now",
    )
    compare(
        findings,
        check="generic status route",
        component="recognizer/main.py",
        expected=True,
        actual="/status/{set_id}" in routes,
        set_id=set_id,
        impact="maintenance",
    )


def check_frontend_set(
    frontend_root: Path | None,
    baseline: dict[str, Any],
    baseline_set: dict[str, Any],
    set_id: str,
    findings: list[Finding],
) -> bool:
    if frontend_root is None or not frontend_root.is_dir():
        add(
            findings,
            NOT_VERIFIED,
            "frontend repository",
            "frontend",
            "Frontend repository path was not supplied or is unavailable.",
            expected=baseline["repositories"]["frontend"]["repository"],
            actual=str(frontend_root) if frontend_root else "not supplied",
            impact="scanning now / maintenance",
            blocks=False,
            set_id=set_id,
        )
        return False

    config_path = frontend_root / baseline_set["frontend"]["configPath"]
    index_path = frontend_root / "index.html"
    try:
        config = read_text(config_path)
    except Exception as error:
        add(
            findings,
            FAIL,
            "frontend set config",
            str(config_path),
            f"Frontend set config missing/unreadable: {error}",
            impact="scanning now",
            blocks=True,
            set_id=set_id,
        )
        return False

    expected_frontend = baseline_set["frontend"]
    compare(
        findings,
        check="frontend self-registration",
        component=str(config_path),
        expected=True,
        actual="SetRegistry.register(" in config,
        set_id=set_id,
        impact="scanning now",
    )

    fields = [
        ("expectedId", "id", extract_js_string),
        ("expectedSetCode", "setCode", extract_js_string),
        ("expectedSeries", "series", extract_js_string),
        ("expectedMaxCard", "maxCard", extract_js_int),
        ("expectedDenominator", "denominator", extract_js_int),
        ("expectedDynamicVariants", "dynamicVariants", extract_js_bool),
        ("expectedOfficialCode", "officialCode", extract_js_string),
        ("expectedDatasetId", "datasetId", extract_js_string),
        ("expectedImageSet", "imageSet", extract_js_string),
        ("expectedInventorySetIdParam", "inventorySetIdParam", extract_js_bool),
    ]
    for baseline_key, js_key, extractor in fields:
        if baseline_key not in expected_frontend:
            continue
        compare(
            findings,
            check=f"frontend {js_key}",
            component=str(config_path),
            expected=expected_frontend[baseline_key],
            actual=extractor(config, js_key),
            set_id=set_id,
            impact="scanning now / maintenance",
        )

    schema_required = bool(expected_frontend.get("expectedSchemaPackageUrlRequired"))
    has_schema_url = js_has_property(config, "schemaPackageUrl")
    compare(
        findings,
        check="frontend Schema package mode",
        component=str(config_path),
        expected=schema_required,
        actual=has_schema_url,
        set_id=set_id,
        impact="scanning now / data safety",
    )
    if schema_required:
        expected_route = baseline_set["recognizer"]["publicPackageRoute"]
        compare(
            findings,
            check="frontend Schema package route",
            component=str(config_path),
            expected=True,
            actual=expected_route in config,
            set_id=set_id,
            impact="scanning now",
        )

    deployment_key = expected_frontend.get("expectedAppsScriptDeploymentKey")
    deployment = baseline.get("appsScriptDeployments", {}).get(deployment_key, {})
    expected_script_url = deployment.get("expectedDeploymentUrl")
    if expected_script_url:
        compare(
            findings,
            check="frontend Apps Script target identifier (offline)",
            component=str(config_path),
            expected=expected_script_url,
            actual=extract_js_script_url(config),
            set_id=set_id,
            impact="scanning now / data safety",
        )

    try:
        index = read_text(index_path)
    except Exception as error:
        add(
            findings,
            FAIL,
            "frontend index",
            str(index_path),
            f"Frontend index missing/unreadable: {error}",
            impact="scanning now",
            blocks=True,
            set_id=set_id,
        )
        return True

    include = f'<script src="./{expected_frontend["configPath"]}"></script>'
    compare(
        findings,
        check="frontend index includes set exactly once",
        component=str(index_path),
        expected=1,
        actual=index.count(include),
        set_id=set_id,
        impact="scanning now",
    )

    return True


def check_accepted_exceptions(
    frontend_root: Path | None,
    baseline: dict[str, Any],
    baseline_set: dict[str, Any],
    manifest: dict[str, Any] | None,
    set_id: str,
    findings: list[Finding],
) -> None:
    exception_ids = {
        item.get("id")
        for item in baseline_set.get("acceptedExceptions", [])
        if isinstance(item, dict)
    }
    frontend_text = None
    inventory_request_text = None
    if frontend_root and frontend_root.is_dir():
        try:
            frontend_text = read_text(frontend_root / baseline_set["frontend"]["configPath"])
        except Exception:
            frontend_text = None
        try:
            inventory_request_text = read_text(frontend_root / "js" / "inventory-request.js")
        except Exception:
            inventory_request_text = None

    def exception_result(exception_id: str, matches: bool | None, evidence: str) -> None:
        if exception_id not in exception_ids:
            return
        if matches is True:
            add(
                findings,
                PASS,
                f"accepted exception {exception_id}",
                "locked baseline exception",
                evidence,
                set_id=set_id,
            )
        elif matches is None:
            add(
                findings,
                NOT_VERIFIED,
                f"accepted exception {exception_id}",
                "locked baseline exception",
                "Required local evidence is unavailable.",
                expected="Accepted exception matches locked baseline",
                actual="Not verified",
                impact="maintenance",
                set_id=set_id,
            )
        else:
            add(
                findings,
                FAIL,
                f"accepted exception {exception_id}",
                "locked baseline exception",
                "Current repository state no longer matches the accepted exception.",
                expected="Accepted exception matches locked baseline",
                actual=evidence,
                impact="data safety / maintenance",
                blocks=True,
                set_id=set_id,
            )

    if set_id == "ascended-heroes":
        inv = (manifest or {}).get("inventory") or {}
        variants = [
            item.get("variantId")
            for item in ((manifest or {}).get("variants") or [])
            if isinstance(item, dict)
        ]
        exception_result(
            "ASC_CUSTOM_FIVE_VARIANT_LAYOUT",
            variants == baseline_set["variantRulesExpectedOffline"]["variants"],
            "Five accepted ASC finish buckets match the locked baseline.",
        )
        exception_result(
            "ASC_DYNAMIC_VARIANTS",
            None if frontend_text is None else extract_js_bool(frontend_text, "dynamicVariants") is True,
            "ASC frontend remains dynamicVariants=true.",
        )
        exception_result(
            "ASC_CARD_ID_COLUMN_T",
            inv.get("cardIdColumn") == 20,
            f"ASC manifest cardIdColumn={inv.get('cardIdColumn')}.",
        )
        external = (manifest or {}).get("externalIds") or {}
        exception_result(
            "ASC_LEGACY_EXTERNAL_ID_METADATA",
            "officialCode" not in external and "pokemonTcgData" not in external,
            "ASC retains the accepted legacy external-ID metadata shape.",
        )
        exception_result(
            "ASC_SHEET_BACKED_FRONTEND_CATALOGUE",
            None if frontend_text is None else not js_has_property(frontend_text, "schemaPackageUrl"),
            "ASC frontend remains on the accepted non-Schema-package catalogue path.",
        )
        if frontend_text is None or inventory_request_text is None:
            legacy_contract_match = None
        else:
            legacy_contract_match = (
                not js_has_property(frontend_text, "schemaPackageUrl")
                and all(
                    token in inventory_request_text
                    for token in (
                        "parameters.row",
                        "parameters.variant",
                        "parameters.change",
                        "transactionId",
                        'mode: "legacy"',
                    )
                )
            )
        exception_result(
            "ASC_LEGACY_INVENTORY_REQUEST_CONTRACT",
            legacy_contract_match,
            (
                "ASC still resolves to the accepted legacy request contract: "
                "row + variant + change + transactionId."
            ),
        )

    if set_id == "destined-rivals":
        deployment_key = baseline_set["frontend"]["expectedAppsScriptDeploymentKey"]
        expected_dri_url = (
            baseline.get("appsScriptDeployments", {})
            .get(deployment_key, {})
            .get("expectedDeploymentUrl")
        )
        if frontend_text is None:
            separate_target_match = None
        else:
            separate_target_match = (
                baseline_set["inventoryExpectedOffline"]["workbookKey"] == "destined-rivals"
                and deployment_key == "destined-rivals"
                and extract_js_script_url(frontend_text) == expected_dri_url
                and ((manifest or {}).get("inventory") or {}).get("sheetName") == "Destined Rivals"
            )
        exception_result(
            "DRI_SEPARATE_WORKBOOK_AND_APPS_SCRIPT",
            separate_target_match,
            (
                "DRI local configuration points to the accepted separate deployment "
                "identifier and Destined Rivals sheet name. Live workbook state remains Stage 2."
            ),
        )
        external = (manifest or {}).get("externalIds") or {}
        exception_result(
            "DRI_LEGACY_EXTERNAL_ID_METADATA",
            (
                external.get("pokemonTcgIo") == "sv10"
                and "officialCode" not in external
                and "pokemonTcgData" not in external
            ),
            "DRI retains accepted pokemonTcgIo legacy metadata rather than the newer pair.",
        )
        exception_result(
            "DRI_LEGACY_IMAGE_SET",
            None if frontend_text is None else extract_js_string(frontend_text, "imageSet") == "sv10",
            "DRI frontend imageSet remains sv10.",
        )


def add_known_warnings(
    baseline: dict[str, Any],
    set_id: str,
    findings: list[Finding],
) -> None:
    for warning in baseline.get("knownWarnings", {}).get(set_id, []):
        add(
            findings,
            WARNING,
            warning.get("id", "known warning"),
            warning.get("area", "known baseline warning"),
            warning.get("meaning", "Known warning from locked baseline."),
            expected="Known non-blocking warning remains visible",
            actual=warning.get("cleanupStatus", "future-cleanup"),
            impact=warning.get("area", "maintenance"),
            blocks=bool(warning.get("blocksProduction", False)),
            set_id=set_id,
        )


def frontend_universe(frontend_root: Path | None, baseline: dict[str, Any]) -> tuple[set[str] | None, str | None]:
    if frontend_root is None or not frontend_root.is_dir():
        return None, "Frontend repository path unavailable."
    try:
        index = read_text(frontend_root / "index.html")
    except Exception as error:
        return None, f"Could not read frontend index: {error}"

    result: set[str] = set()
    pattern = re.compile(r'<script\s+src="\./js/sets/([^"]+)\.js"></script>')
    included_files = set(pattern.findall(index))
    for set_id, set_data in baseline["sets"].items():
        expected_file = Path(set_data["frontend"]["configPath"]).stem
        if expected_file in included_files:
            result.add(set_id)

    # Also identify registered configs not represented in the baseline.
    sets_dir = frontend_root / "js" / "sets"
    if sets_dir.is_dir():
        for path in sets_dir.glob("*.js"):
            try:
                text = read_text(path)
            except Exception:
                continue
            actual_id = extract_js_string(text, "id")
            if actual_id and "SetRegistry.register(" in text:
                result.add(actual_id)
    return result, None


def cross_system_universe(
    baseline: dict[str, Any],
    recognizer_root: Path,
    frontend_root: Path | None,
    builder_entries: list[dict[str, Any]],
    router_set_ids: set[str],
    findings: list[Finding],
) -> None:
    expected = set(baseline["productionSetOrder"])
    manifest_ids, manifest_errors = discover_manifest_set_ids(recognizer_root)
    if manifest_errors:
        add(
            findings,
            FAIL,
            "Schema package discovery",
            "recognizer/sets/*/manifest.json",
            "One or more manifests could not be interpreted: " + " | ".join(manifest_errors),
            impact="scaling / maintenance",
            blocks=True,
        )
    compare(
        findings,
        check="set universe: Schema packages",
        component="recognizer/sets",
        expected=sorted(expected),
        actual=sorted(manifest_ids),
        impact="scanning now / scaling",
    )

    builder_ids = {
        entry.get("setId")
        for entry in builder_entries
        if isinstance(entry.get("setId"), str)
    }
    compare(
        findings,
        check="set universe: shared builder",
        component="recognizer/schema_v1_builds.json",
        expected=sorted(expected),
        actual=sorted(builder_ids),
        impact="scanning now / scaling",
    )
    compare(
        findings,
        check="set universe: recognizer router",
        component="recognizer/main.py",
        expected=sorted(expected),
        actual=sorted(router_set_ids),
        impact="scanning now / scaling",
    )

    front_ids, error = frontend_universe(frontend_root, baseline)
    if front_ids is None:
        add(
            findings,
            NOT_VERIFIED,
            "set universe: frontend",
            "frontend/index.html + js/sets",
            error or "Frontend set universe unavailable.",
            expected=sorted(expected),
            actual="NOT VERIFIED",
            impact="scanning now / scaling",
            blocks=False,
        )
    else:
        compare(
            findings,
            check="set universe: frontend",
            component="frontend/index.html + js/sets",
            expected=sorted(expected),
            actual=sorted(front_ids),
            impact="scanning now / scaling",
        )


def add_external_not_verified(findings: list[Finding]) -> None:
    entries = [
        (
            "live Google Sheets",
            "Google Sheets",
            "Stage 2 only. Stage 1B did not access any spreadsheet.",
            "data safety",
        ),
        (
            "deployed Apps Script",
            "Apps Script",
            "Live deployed Apps Script source/configuration is outside Stage 1B.",
            "data safety / maintenance",
        ),
        (
            "live Render configuration/runtime",
            "Render",
            "Stage 3 only. Stage 1B did not access Render or recognizer HTTP endpoints.",
            "scanning now / maintenance",
        ),
    ]
    for check, component, message, impact in entries:
        add(
            findings,
            NOT_VERIFIED,
            check,
            component,
            message,
            expected="Independent live verification in a later approved stage",
            actual="Not accessed",
            impact=impact,
            blocks=False,
            scope="external",
        )


def offline_status(findings: Iterable[Finding], set_id: str | None = None) -> str:
    selected = [
        f
        for f in findings
        if f.scope == "offline" and (set_id is None or f.set_id == set_id)
    ]
    if any(f.status == FAIL for f in selected):
        return FAIL
    if any(f.status == NOT_VERIFIED for f in selected):
        return NOT_VERIFIED
    if any(f.status == WARNING for f in selected):
        return WARNING
    return PASS


def overall_offline_label(findings: list[Finding]) -> str:
    status = offline_status(findings)
    if status == FAIL:
        return FAIL
    if status == NOT_VERIFIED:
        return NOT_VERIFIED
    if status == WARNING:
        return "PASS WITH WARNINGS"
    return PASS


def render_report(baseline: dict[str, Any], findings: list[Finding]) -> None:
    print("Pokémon Inventory Scanner — Production Validator")
    print("Stage 1B: OFFLINE / READ-ONLY")
    print("Baseline:", baseline.get("baselineName"), "[" + str(baseline.get("status")) + "]")
    print()

    print("PER-SET OFFLINE RESULTS")
    for set_id in baseline["productionSetOrder"]:
        display = baseline["sets"][set_id]["displayName"]
        print(f"{baseline['sets'][set_id]['setCode']} — {offline_status(findings, set_id)} — {display}")
    print()

    print("CROSS-SYSTEM SET UNIVERSE")
    universe = [
        f
        for f in findings
        if f.check.startswith("set universe:") or f.check == "Schema package discovery"
    ]
    for finding in universe:
        print(f"{finding.status}: {finding.check}")
        if finding.status != PASS:
            for line in finding.detail_lines()[1:]:
                print(line)
    print()

    important = [
        f
        for f in findings
        if f.status in (FAIL, WARNING, NOT_VERIFIED)
        and not f.check.startswith("set universe:")
        and f.scope == "offline"
    ]
    if important:
        print("OFFLINE FINDINGS")
        for finding in important:
            prefix = baseline["sets"].get(finding.set_id, {}).get("setCode")
            print((prefix + " — " if prefix else "") + finding.status)
            for line in finding.detail_lines()[1:]:
                print(line)
        print()

    print("LIVE / EXTERNAL SYSTEMS")
    external = [f for f in findings if f.scope == "external"]
    for finding in external:
        prefix = baseline["sets"].get(finding.set_id, {}).get("setCode")
        label = (prefix + " / " if prefix else "") + finding.component
        print(f"{label} — {finding.status}: {finding.message}")
    print()

    offline_label = overall_offline_label(findings)
    print("OVERALL OFFLINE RESULT:", offline_label)
    print("FULL PRODUCTION VERIFICATION: NOT VERIFIED")
    print(
        "Reason: Stage 1B intentionally does not verify live Google Sheets, "
        "deployed Apps Script, or Render."
    )


def validate(
    recognizer_root: Path,
    frontend_root: Path | None,
    baseline_path: Path,
) -> tuple[dict[str, Any], list[Finding]]:
    baseline = load_json(baseline_path)
    findings: list[Finding] = []

    if baseline.get("diagnosticOnly") is not True:
        add(
            findings,
            FAIL,
            "baseline diagnostic-only safety flag",
            str(baseline_path),
            "Baseline must explicitly declare diagnosticOnly=true.",
            expected=True,
            actual=baseline.get("diagnosticOnly"),
            impact="maintenance / data safety",
            blocks=True,
        )

    mutation_policy = baseline.get("mutationPolicy") or {}
    unsafe_flags = [key for key, value in mutation_policy.items() if value is not False]
    if unsafe_flags:
        add(
            findings,
            FAIL,
            "baseline mutation policy",
            str(baseline_path),
            "One or more mutation permissions are not false.",
            expected="all mutation permissions false",
            actual=unsafe_flags,
            impact="data safety",
            blocks=True,
        )
    else:
        add(
            findings,
            PASS,
            "baseline mutation policy",
            str(baseline_path),
            "All mutation permissions are false.",
        )

    builder_entries = load_builder_registry(recognizer_root, findings)
    router_ids, aliases, routes = parse_router(recognizer_root, findings)

    for set_id in baseline["productionSetOrder"]:
        baseline_set = baseline["sets"][set_id]
        manifest, _catalogue = check_manifest_and_cards(
            recognizer_root, baseline_set, set_id, findings
        )
        check_builder(builder_entries, baseline_set, set_id, findings)
        check_router_for_set(router_ids, aliases, routes, baseline_set, set_id, findings)
        check_frontend_set(frontend_root, baseline, baseline_set, set_id, findings)
        check_accepted_exceptions(
            frontend_root, baseline, baseline_set, manifest, set_id, findings
        )
        add_known_warnings(baseline, set_id, findings)

    cross_system_universe(
        baseline,
        recognizer_root,
        frontend_root,
        builder_entries,
        router_ids,
        findings,
    )
    add_external_not_verified(findings)
    return baseline, findings


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate local Pokémon Inventory Scanner repositories against "
            "the locked Master Baseline v1. Stage 1B is offline/read-only."
        )
    )
    parser.add_argument(
        "--recognizer-root",
        type=Path,
        default=DEFAULT_RECOGNIZER_ROOT,
        help="Local pokemon-card-recognizer repository root.",
    )
    parser.add_argument(
        "--frontend-root",
        type=Path,
        default=None,
        help=(
            "Local pokemon-card-scanner repository root. If omitted, frontend "
            "checks are NOT VERIFIED."
        ),
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE,
        help="Locked production baseline JSON.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    recognizer_root = args.recognizer_root.resolve()
    frontend_root = args.frontend_root.resolve() if args.frontend_root else None
    baseline_path = args.baseline.resolve()

    try:
        baseline, findings = validate(recognizer_root, frontend_root, baseline_path)
    except Exception as error:
        print("Pokémon Inventory Scanner — Production Validator")
        print("Stage 1B: OFFLINE / READ-ONLY")
        print()
        print("OVERALL OFFLINE RESULT: FAIL")
        print("Validator could not complete:", error)
        return 2

    render_report(baseline, findings)
    status = offline_status(findings)
    return 1 if status in (FAIL, NOT_VERIFIED) else 0


if __name__ == "__main__":
    raise SystemExit(main())
