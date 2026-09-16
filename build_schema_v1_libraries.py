"""Build all registered Schema v1 recognition libraries.

Render and local candidate environments can run this single command. New
Schema v1 sets are added declaratively in schema_v1_builds.json rather than by
creating another set-specific builder or expanding the deployment command.
"""

import json
from pathlib import Path

from schema_v1_library_builder import build_library


ROOT = Path(__file__).resolve().parent
REGISTRY_PATH = ROOT / "schema_v1_builds.json"


def load_registry(path=REGISTRY_PATH):
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    sets = data.get("sets")
    if not isinstance(sets, list):
        raise RuntimeError("schema_v1_builds.json must contain a sets array.")

    return sets


def build_registered_libraries():
    builds = load_registry()

    for entry in builds:
        if not isinstance(entry, dict):
            raise RuntimeError("Each Schema v1 build entry must be an object.")

        set_id = entry.get("setId")
        package = entry.get("package")
        output = entry.get("output")
        expected_records = entry.get("expectedRecords")

        if not isinstance(set_id, str) or not set_id.strip():
            raise RuntimeError("Schema v1 build entry is missing setId.")
        if not isinstance(package, str) or not package.strip():
            raise RuntimeError(set_id + " build entry is missing package.")
        if not isinstance(output, str) or not output.strip():
            raise RuntimeError(set_id + " build entry is missing output.")
        if (
            expected_records is not None
            and (
                isinstance(expected_records, bool)
                or not isinstance(expected_records, int)
                or expected_records < 1
            )
        ):
            raise RuntimeError(set_id + " expectedRecords must be a positive integer.")

        build_library(
            set_id=set_id,
            package_directory=ROOT / package,
            expected_records=expected_records,
            output_path=ROOT / output,
        )


if __name__ == "__main__":
    build_registered_libraries()
