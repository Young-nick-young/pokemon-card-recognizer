"""Strict loader for frozen Pokemon scanner Set Manifest Schema v1 packages."""

from dataclasses import dataclass
import json
from pathlib import Path
import re


SCHEMA_VERSION = "1.0"

ID_PATTERN = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$"
)


class SchemaV1Error(Exception):
    """Base error for Schema v1 discovery and loading failures."""


class SchemaV1DiscoveryError(SchemaV1Error):
    """Raised when the package root cannot be discovered."""


class SchemaV1ValidationError(SchemaV1Error):
    """Raised when a package does not conform to frozen Schema v1."""

    def __init__(self, package_directory, issues):

        self.package_directory = Path(
            package_directory
        )

        self.issues = tuple(issues)

        details = "\n".join(
            "- " + issue
            for issue in self.issues
        )

        super().__init__(
            "Invalid Schema v1 package at "
            + str(self.package_directory)
            + ":\n"
            + details
        )


@dataclass(frozen=True)
class SchemaV1Package:
    """A fully loaded and validated Schema v1 set package."""

    directory: Path
    manifest: dict
    catalogue: dict

    @property
    def set_id(self):

        return self.manifest["setId"]

    @property
    def cards(self):

        return self.catalogue["cards"]


@dataclass(frozen=True)
class SchemaV1ShadowReport:
    """Diagnostic shadow-load results; never used for recognition routing."""

    packages: dict
    errors: dict


def _add_required_and_extra_issues(
    value,
    path,
    required,
    allowed,
    issues
):

    if not isinstance(value, dict):

        issues.append(
            path + ": expected an object"
        )

        return False

    for field in required:

        if field not in value:

            issues.append(
                path
                + "."
                + field
                + ": required field is missing"
            )

    for field in sorted(
        set(value) - set(allowed)
    ):

        issues.append(
            path
            + "."
            + field
            + ": field is not allowed by Schema v1"
        )

    return True


def _validate_string(
    value,
    path,
    issues,
    minimum_length=1
):

    if (
        not isinstance(value, str)
        or
        len(value) < minimum_length
    ):

        issues.append(
            path
            + ": expected a string with length at least "
            + str(minimum_length)
        )

        return False

    return True


def _validate_id(
    value,
    path,
    issues
):

    if not _validate_string(
        value,
        path,
        issues
    ):

        return False

    if not ID_PATTERN.fullmatch(value):

        issues.append(
            path
            + ": must match "
            + ID_PATTERN.pattern
        )

        return False

    return True


def _validate_integer(
    value,
    path,
    issues,
    minimum
):

    if (
        isinstance(value, bool)
        or
        not isinstance(value, int)
        or
        value < minimum
    ):

        issues.append(
            path
            + ": expected an integer greater than or equal to "
            + str(minimum)
        )

        return False

    return True


def _validate_external_ids(
    value,
    path,
    issues
):

    if not isinstance(value, dict):

        issues.append(
            path + ": expected an object"
        )

        return

    if not value:

        issues.append(
            path + ": expected at least one external ID"
        )

    for key, external_id in value.items():

        _validate_string(
            external_id,
            path + "." + str(key),
            issues
        )


def _validate_unique_ids(
    objects,
    field,
    path,
    issues
):

    seen = set()

    for index, item in enumerate(objects):

        if not isinstance(item, dict):

            continue

        value = item.get(field)

        if not isinstance(value, str):

            continue

        if value in seen:

            issues.append(
                path
                + "["
                + str(index)
                + "]."
                + field
                + ": duplicate value "
                + repr(value)
            )

        seen.add(value)


def _validate_manifest(
    manifest,
    issues
):

    required = (
        "schemaVersion",
        "manifestVersion",
        "setId",
        "displayName",
        "language",
        "market",
        "collections",
        "numberingNamespaces",
        "variants",
        "catalogue",
        "inventory"
    )

    allowed = required + (
        "aliases",
        "externalIds"
    )

    if not _add_required_and_extra_issues(
        manifest,
        "manifest",
        required,
        allowed,
        issues
    ):

        return

    if (
        "schemaVersion" in manifest
        and
        manifest["schemaVersion"]
        != SCHEMA_VERSION
    ):

        issues.append(
            "manifest.schemaVersion: expected '"
            + SCHEMA_VERSION
            + "'"
        )

    if "manifestVersion" in manifest:

        _validate_integer(
            manifest["manifestVersion"],
            "manifest.manifestVersion",
            issues,
            1
        )

    if "setId" in manifest:

        _validate_id(
            manifest["setId"],
            "manifest.setId",
            issues
        )

    for field in (
        "displayName",
        "language",
        "market"
    ):

        if field in manifest:

            _validate_string(
                manifest[field],
                "manifest." + field,
                issues,
                2 if field in ("language", "market") else 1
            )

    if "aliases" in manifest:

        aliases = manifest["aliases"]

        if not isinstance(aliases, list):

            issues.append(
                "manifest.aliases: expected an array"
            )

        else:

            for index, alias in enumerate(aliases):

                _validate_id(
                    alias,
                    "manifest.aliases["
                    + str(index)
                    + "]",
                    issues
                )

            string_aliases = [
                alias
                for alias in aliases
                if isinstance(alias, str)
            ]

            if (
                len(string_aliases)
                !=
                len(set(string_aliases))
            ):

                issues.append(
                    "manifest.aliases: duplicate values are not allowed"
                )

    if "externalIds" in manifest:

        _validate_external_ids(
            manifest["externalIds"],
            "manifest.externalIds",
            issues
        )

    collection_required = (
        "collectionId",
        "label"
    )

    collections = manifest.get(
        "collections"
    )

    if not isinstance(collections, list):

        if "collections" in manifest:

            issues.append(
                "manifest.collections: expected an array"
            )

    else:

        if not collections:

            issues.append(
                "manifest.collections: expected at least one item"
            )

        for index, collection in enumerate(collections):

            path = (
                "manifest.collections["
                + str(index)
                + "]"
            )

            if not _add_required_and_extra_issues(
                collection,
                path,
                collection_required,
                collection_required,
                issues
            ):

                continue

            if "collectionId" in collection:

                _validate_id(
                    collection["collectionId"],
                    path + ".collectionId",
                    issues
                )

            if "label" in collection:

                _validate_string(
                    collection["label"],
                    path + ".label",
                    issues
                )

        _validate_unique_ids(
            collections,
            "collectionId",
            "manifest.collections",
            issues
        )

    namespace_required = (
        "namespaceId",
        "label"
    )

    namespace_allowed = (
        "namespaceId",
        "label",
        "denominator"
    )

    namespaces = manifest.get(
        "numberingNamespaces"
    )

    if not isinstance(namespaces, list):

        if "numberingNamespaces" in manifest:

            issues.append(
                "manifest.numberingNamespaces: expected an array"
            )

    else:

        if not namespaces:

            issues.append(
                "manifest.numberingNamespaces: expected at least one item"
            )

        for index, namespace in enumerate(namespaces):

            path = (
                "manifest.numberingNamespaces["
                + str(index)
                + "]"
            )

            if not _add_required_and_extra_issues(
                namespace,
                path,
                namespace_required,
                namespace_allowed,
                issues
            ):

                continue

            if "namespaceId" in namespace:

                _validate_id(
                    namespace["namespaceId"],
                    path + ".namespaceId",
                    issues
                )

            if "label" in namespace:

                _validate_string(
                    namespace["label"],
                    path + ".label",
                    issues
                )

            if "denominator" in namespace:

                _validate_string(
                    namespace["denominator"],
                    path + ".denominator",
                    issues
                )

        _validate_unique_ids(
            namespaces,
            "namespaceId",
            "manifest.numberingNamespaces",
            issues
        )

    variant_required = (
        "variantId",
        "label",
        "inventoryKey"
    )

    variants = manifest.get(
        "variants"
    )

    if not isinstance(variants, list):

        if "variants" in manifest:

            issues.append(
                "manifest.variants: expected an array"
            )

    else:

        if not variants:

            issues.append(
                "manifest.variants: expected at least one item"
            )

        for index, variant in enumerate(variants):

            path = (
                "manifest.variants["
                + str(index)
                + "]"
            )

            if not _add_required_and_extra_issues(
                variant,
                path,
                variant_required,
                variant_required,
                issues
            ):

                continue

            for field in (
                "variantId",
                "inventoryKey"
            ):

                if field in variant:

                    _validate_id(
                        variant[field],
                        path + "." + field,
                        issues
                    )

            if "label" in variant:

                _validate_string(
                    variant["label"],
                    path + ".label",
                    issues
                )

        _validate_unique_ids(
            variants,
            "variantId",
            "manifest.variants",
            issues
        )

    catalogue = manifest.get(
        "catalogue"
    )

    catalogue_fields = (
        "path",
        "expectedRecords"
    )

    if catalogue is not None:

        if _add_required_and_extra_issues(
            catalogue,
            "manifest.catalogue",
            catalogue_fields,
            catalogue_fields,
            issues
        ):

            if "path" in catalogue:

                _validate_string(
                    catalogue["path"],
                    "manifest.catalogue.path",
                    issues
                )

            if "expectedRecords" in catalogue:

                _validate_integer(
                    catalogue["expectedRecords"],
                    "manifest.catalogue.expectedRecords",
                    issues,
                    1
                )

    inventory = manifest.get(
        "inventory"
    )

    inventory_required = (
        "destinationKey",
        "sheetName",
        "startRow",
        "cardIdColumn",
        "quantityColumns"
    )

    if inventory is not None:

        if _add_required_and_extra_issues(
            inventory,
            "manifest.inventory",
            inventory_required,
            inventory_required,
            issues
        ):

            if "destinationKey" in inventory:

                _validate_id(
                    inventory["destinationKey"],
                    "manifest.inventory.destinationKey",
                    issues
                )

            if "sheetName" in inventory:

                _validate_string(
                    inventory["sheetName"],
                    "manifest.inventory.sheetName",
                    issues
                )

            for field in (
                "startRow",
                "cardIdColumn"
            ):

                if field in inventory:

                    _validate_integer(
                        inventory[field],
                        "manifest.inventory." + field,
                        issues,
                        1
                    )

            quantity_columns = inventory.get(
                "quantityColumns"
            )

            if not isinstance(quantity_columns, dict):

                if "quantityColumns" in inventory:

                    issues.append(
                        "manifest.inventory.quantityColumns: expected an object"
                    )

            else:

                if not quantity_columns:

                    issues.append(
                        "manifest.inventory.quantityColumns: expected at least one item"
                    )

                for key, column in quantity_columns.items():

                    _validate_integer(
                        column,
                        "manifest.inventory.quantityColumns."
                        + str(key),
                        issues,
                        1
                    )


def _validate_catalogue(
    catalogue,
    issues
):

    required = (
        "schemaVersion",
        "setId",
        "cards"
    )

    if not _add_required_and_extra_issues(
        catalogue,
        "catalogue",
        required,
        required,
        issues
    ):

        return

    if (
        "schemaVersion" in catalogue
        and
        catalogue["schemaVersion"]
        != SCHEMA_VERSION
    ):

        issues.append(
            "catalogue.schemaVersion: expected '"
            + SCHEMA_VERSION
            + "'"
        )

    if "setId" in catalogue:

        _validate_id(
            catalogue["setId"],
            "catalogue.setId",
            issues
        )

    cards = catalogue.get("cards")

    if not isinstance(cards, list):

        if "cards" in catalogue:

            issues.append(
                "catalogue.cards: expected an array"
            )

        return

    if not cards:

        issues.append(
            "catalogue.cards: expected at least one item"
        )

    card_required = (
        "cardId",
        "collectionId",
        "number",
        "name",
        "referenceImage",
        "variants"
    )

    card_allowed = card_required + (
        "externalIds",
    )

    for index, card in enumerate(cards):

        path = (
            "catalogue.cards["
            + str(index)
            + "]"
        )

        if not _add_required_and_extra_issues(
            card,
            path,
            card_required,
            card_allowed,
            issues
        ):

            continue

        for field in (
            "cardId",
            "collectionId"
        ):

            if field in card:

                _validate_id(
                    card[field],
                    path + "." + field,
                    issues
                )

        for field in (
            "name",
            "referenceImage"
        ):

            if field in card:

                _validate_string(
                    card[field],
                    path + "." + field,
                    issues
                )

        number = card.get("number")

        number_required = (
            "namespaceId",
            "display",
            "sortKey"
        )

        if number is not None:

            if _add_required_and_extra_issues(
                number,
                path + ".number",
                number_required,
                number_required,
                issues
            ):

                if "namespaceId" in number:

                    _validate_id(
                        number["namespaceId"],
                        path + ".number.namespaceId",
                        issues
                    )

                if "display" in number:

                    _validate_string(
                        number["display"],
                        path + ".number.display",
                        issues
                    )

                if "sortKey" in number:

                    _validate_integer(
                        number["sortKey"],
                        path + ".number.sortKey",
                        issues,
                        0
                    )

        variants = card.get("variants")

        if not isinstance(variants, list):

            if "variants" in card:

                issues.append(
                    path + ".variants: expected an array"
                )

        else:

            if not variants:

                issues.append(
                    path + ".variants: expected at least one item"
                )

            for variant_index, variant_id in enumerate(variants):

                _validate_id(
                    variant_id,
                    path
                    + ".variants["
                    + str(variant_index)
                    + "]",
                    issues
                )

            string_variants = [
                variant_id
                for variant_id in variants
                if isinstance(variant_id, str)
            ]

            if (
                len(string_variants)
                !=
                len(set(string_variants))
            ):

                issues.append(
                    path + ".variants: duplicate values are not allowed"
                )

        if "externalIds" in card:

            _validate_external_ids(
                card["externalIds"],
                path + ".externalIds",
                issues
            )

    _validate_unique_ids(
        cards,
        "cardId",
        "catalogue.cards",
        issues
    )


def _validate_cross_references(
    manifest,
    catalogue,
    issues
):

    if not isinstance(manifest, dict):

        return

    if not isinstance(catalogue, dict):

        return

    manifest_set_id = manifest.get("setId")
    catalogue_set_id = catalogue.get("setId")

    if (
        isinstance(manifest_set_id, str)
        and
        isinstance(catalogue_set_id, str)
        and
        manifest_set_id != catalogue_set_id
    ):

        issues.append(
            "catalogue.setId: does not match manifest.setId "
            + repr(manifest_set_id)
        )

    cards = catalogue.get("cards")
    expected_records = (
        manifest.get("catalogue", {})
        .get("expectedRecords")
        if isinstance(
            manifest.get("catalogue"),
            dict
        )
        else None
    )

    if (
        isinstance(cards, list)
        and
        isinstance(expected_records, int)
        and
        not isinstance(expected_records, bool)
        and
        len(cards) != expected_records
    ):

        issues.append(
            "catalogue.cards: expected "
            + str(expected_records)
            + " records, found "
            + str(len(cards))
        )

    collections = {
        item.get("collectionId")
        for item in manifest.get(
            "collections",
            []
        )
        if isinstance(item, dict)
        and isinstance(
            item.get("collectionId"),
            str
        )
    }

    namespaces = {
        item.get("namespaceId")
        for item in manifest.get(
            "numberingNamespaces",
            []
        )
        if isinstance(item, dict)
        and isinstance(
            item.get("namespaceId"),
            str
        )
    }

    variants = {
        item.get("variantId")
        for item in manifest.get(
            "variants",
            []
        )
        if isinstance(item, dict)
        and isinstance(
            item.get("variantId"),
            str
        )
    }

    inventory_keys = {
        item.get("inventoryKey")
        for item in manifest.get(
            "variants",
            []
        )
        if isinstance(item, dict)
        and isinstance(
            item.get("inventoryKey"),
            str
        )
    }

    inventory = manifest.get("inventory")

    if isinstance(inventory, dict):

        quantity_columns = inventory.get(
            "quantityColumns"
        )

        if isinstance(quantity_columns, dict):

            quantity_keys = set(
                quantity_columns
            )

            missing = sorted(
                inventory_keys - quantity_keys
            )

            extra = sorted(
                quantity_keys - inventory_keys
            )

            if missing:

                issues.append(
                    "manifest.inventory.quantityColumns: missing inventory keys "
                    + repr(missing)
                )

            if extra:

                issues.append(
                    "manifest.inventory.quantityColumns: unknown inventory keys "
                    + repr(extra)
                )

    if not isinstance(cards, list):

        return

    for index, card in enumerate(cards):

        if not isinstance(card, dict):

            continue

        path = (
            "catalogue.cards["
            + str(index)
            + "]"
        )

        collection_id = card.get(
            "collectionId"
        )

        if (
            isinstance(collection_id, str)
            and
            collection_id not in collections
        ):

            issues.append(
                path
                + ".collectionId: unknown collection "
                + repr(collection_id)
            )

        number = card.get("number")

        if isinstance(number, dict):

            namespace_id = number.get(
                "namespaceId"
            )

            if (
                isinstance(namespace_id, str)
                and
                namespace_id not in namespaces
            ):

                issues.append(
                    path
                    + ".number.namespaceId: unknown namespace "
                    + repr(namespace_id)
                )

        card_variants = card.get(
            "variants"
        )

        if isinstance(card_variants, list):

            for variant_id in card_variants:

                if (
                    isinstance(variant_id, str)
                    and
                    variant_id not in variants
                ):

                    issues.append(
                        path
                        + ".variants: unknown variant "
                        + repr(variant_id)
                    )


def _read_json(
    path,
    package_directory,
    label
):

    try:

        text = path.read_text(
            encoding="utf-8"
        )

    except FileNotFoundError as error:

        raise SchemaV1ValidationError(
            package_directory,
            [
                label
                + ": file not found: "
                + str(path)
            ]
        ) from error

    except OSError as error:

        raise SchemaV1ValidationError(
            package_directory,
            [
                label
                + ": could not read file: "
                + str(error)
            ]
        ) from error

    try:

        return json.loads(text)

    except json.JSONDecodeError as error:

        raise SchemaV1ValidationError(
            package_directory,
            [
                label
                + ": malformed JSON at line "
                + str(error.lineno)
                + ", column "
                + str(error.colno)
                + ": "
                + error.msg
            ]
        ) from error


def load_schema_v1_package(
    package_directory
):
    """Load one package or raise a detailed SchemaV1ValidationError."""

    package_directory = Path(
        package_directory
    ).resolve()

    manifest_path = (
        package_directory
        /
        "manifest.json"
    )

    manifest = _read_json(
        manifest_path,
        package_directory,
        "manifest.json"
    )

    issues = []

    _validate_manifest(
        manifest,
        issues
    )

    catalogue_path_value = (
        manifest.get("catalogue", {})
        .get("path")
        if isinstance(manifest, dict)
        and isinstance(
            manifest.get("catalogue"),
            dict
        )
        else None
    )

    if not isinstance(catalogue_path_value, str):

        if issues:

            raise SchemaV1ValidationError(
                package_directory,
                issues
            )

        raise SchemaV1ValidationError(
            package_directory,
            [
                "manifest.catalogue.path: expected a string"
            ]
        )

    catalogue_path = (
        package_directory
        /
        catalogue_path_value
    ).resolve()

    try:

        catalogue_path.relative_to(
            package_directory
        )

    except ValueError:

        issues.append(
            "manifest.catalogue.path: must name a file inside the package directory"
        )

    if issues:

        raise SchemaV1ValidationError(
            package_directory,
            issues
        )

    catalogue = _read_json(
        catalogue_path,
        package_directory,
        catalogue_path.name
    )

    _validate_catalogue(
        catalogue,
        issues
    )

    _validate_cross_references(
        manifest,
        catalogue,
        issues
    )

    if issues:

        raise SchemaV1ValidationError(
            package_directory,
            issues
        )

    return SchemaV1Package(
        directory=package_directory,
        manifest=manifest,
        catalogue=catalogue
    )


def discover_schema_v1_package_directories(
    sets_directory
):
    """Find immediate set directories containing a manifest.json file."""

    sets_directory = Path(
        sets_directory
    ).resolve()

    if not sets_directory.is_dir():

        raise SchemaV1DiscoveryError(
            "Schema v1 sets directory not found: "
            + str(sets_directory)
        )

    return tuple(
        sorted(
            manifest_path.parent
            for manifest_path
            in sets_directory.glob(
                "*/manifest.json"
            )
        )
    )


def load_schema_v1_packages_in_shadow(
    sets_directory,
    logger=print
):
    """Discover and validate packages without changing recognition authority."""

    packages = {}
    errors = {}

    try:

        package_directories = (
            discover_schema_v1_package_directories(
                sets_directory
            )
        )

    except Exception as error:

        message = str(error)

        errors["discovery"] = message

        logger(
            "Schema v1 shadow discovery failed: "
            + message
        )

        return SchemaV1ShadowReport(
            packages=packages,
            errors=errors
        )

    for package_directory in package_directories:

        package_key = package_directory.name

        try:

            package = load_schema_v1_package(
                package_directory
            )

            if package.set_id in packages:

                raise SchemaV1ValidationError(
                    package_directory,
                    [
                        "manifest.setId: duplicate discovered set ID "
                        + repr(package.set_id)
                    ]
                )

            packages[package.set_id] = package

            logger(
                "Schema v1 shadow package validated: "
                + package.set_id
                + " ("
                + str(len(package.cards))
                + " cards)"
            )

        except Exception as error:

            message = str(error)

            errors[package_key] = message

            logger(
                "Schema v1 shadow package rejected: "
                + package_key
                + ": "
                + message
            )

    return SchemaV1ShadowReport(
        packages=packages,
        errors=errors
    )
