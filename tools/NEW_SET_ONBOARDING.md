# New Set Onboarding v1

This is the single entrypoint for adding or regression-checking a modern Schema v1 set.

## Design rule

The existing normalized set definition is the authoring source for a new set. The scaffold generates the Schema v1 package, explicit inventory metadata, Inventory Sheet Plan v2, recognizer registration, frontend candidate, and Apps Script candidate. The orchestrator then runs the existing validation gates around those outputs.

Inventory availability remains explicit. Recognition `cards[].variants` is not inventory authority.

Production deployment is deliberately outside this tool.

## New-set candidate

Run from the recognizer repository:

```bash
python tools/onboard_set.py \
  --definition path/to/set_definition.json
```

This scaffolds the recognizer-owned candidate and validates it. Frontend and Apps Script artifacts remain in the isolated generated candidate tree unless staging roots are supplied.

## Full integration candidate

```bash
python tools/onboard_set.py \
  --definition path/to/set_definition.json \
  --frontend-root /path/to/frontend-candidate \
  --apps-script-root /path/to/apps-script-candidate \
  --build-library \
  --sheet-snapshot /path/to/google-sheet-readback.json
```

The promotion gate can pass only when all of these are present and valid:

1. Schema v1 package and identity metadata.
2. Explicit inventory metadata and deterministic Inventory Sheet Plan v2.
3. Recognition library build and serialized library validation.
4. Frontend candidate integration validation.
5. Apps Script candidate integration validation.
6. Google Sheet read-back matching the Sheet Plan.

If any required promotion evidence is absent, the tool reports `PROMOTION GATE: BLOCKED`.

The tool never deploys Render, Apps Script, the production Sheet, or the frontend.

## Existing-set regression check

```bash
python tools/onboard_set.py --set perfect-order
```

This does not scaffold or overwrite the existing set. It runs the current package validation and reports which promotion evidence was not requested.

## Exit codes

- `0` — all requested validation passed and the full promotion gate is satisfied.
- `1` — blocking validation or runtime failure.
- `2` — invalid command configuration.
- `3` — staging validation passed, but promotion is blocked because required evidence was not supplied.

## Production promotion

Production promotion remains a separate, explicit approval step after this tool reports `PROMOTION GATE: PASS`. Preserve component rollback points and run post-promotion smoke tests exactly as before.
