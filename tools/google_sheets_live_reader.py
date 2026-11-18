#!/usr/bin/env python3
"""Read-only Google Sheets transport for Stage 2C.

Only Google Sheets metadata/value GET operations are exposed. Credentials are
supplied outside the repository through GOOGLE_SHEETS_READONLY_CREDENTIALS_JSON.
"""
from __future__ import annotations

import json
import os
from typing import Any, Sequence
from urllib.parse import quote

from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

from google_sheets_readonly import AuthenticationUnavailable, ReadEvidenceUnavailable

READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
CREDENTIALS_ENV = "GOOGLE_SHEETS_READONLY_CREDENTIALS_JSON"


class LiveGoogleSheetsReader:
    def __init__(self, session: AuthorizedSession):
        self._session = session

    @classmethod
    def from_environment(cls) -> "LiveGoogleSheetsReader":
        raw = os.environ.get(CREDENTIALS_ENV)
        if not raw:
            raise AuthenticationUnavailable("read-only Google Sheets credentials are unavailable")
        try:
            info = json.loads(raw)
            credentials = service_account.Credentials.from_service_account_info(
                info, scopes=[READONLY_SCOPE]
            )
        except Exception as error:
            raise AuthenticationUnavailable("read-only Google Sheets credentials are invalid") from error
        return cls(AuthorizedSession(credentials))

    def _get_json(self, url: str) -> dict[str, Any]:
        try:
            response = self._session.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()
        except Exception as error:
            raise ReadEvidenceUnavailable("Google Sheets read request failed") from error
        if not isinstance(data, dict):
            raise ReadEvidenceUnavailable("Google Sheets returned malformed JSON evidence")
        return data

    def get_spreadsheet_metadata(self, spreadsheet_id: str, sheet_name: str) -> dict[str, Any]:
        fields = "spreadsheetId,properties.title,sheets.properties(sheetId,title)"
        url = (
            "https://sheets.googleapis.com/v4/spreadsheets/"
            + quote(spreadsheet_id, safe="")
            + "?includeGridData=false&fields="
            + quote(fields, safe=",().")
        )
        data = self._get_json(url)
        selected = None
        for sheet in data.get("sheets", []):
            props = sheet.get("properties") or {}
            if props.get("title") == sheet_name:
                selected = {"title": props.get("title"), "sheetId": props.get("sheetId")}
                break
        if selected is None:
            raise ReadEvidenceUnavailable("Expected production Sheet tab is unavailable")
        return {
            "spreadsheetId": data.get("spreadsheetId"),
            "title": (data.get("properties") or {}).get("title"),
            "sheet": selected,
        }

    def batch_get_values(
        self, spreadsheet_id: str, ranges: Sequence[str]
    ) -> dict[str, list[list[Any]]]:
        params = "&".join("ranges=" + quote(rng, safe="'!:") for rng in ranges)
        url = (
            "https://sheets.googleapis.com/v4/spreadsheets/"
            + quote(spreadsheet_id, safe="")
            + "/values:batchGet?majorDimension=ROWS&valueRenderOption=FORMATTED_VALUE&"
            + params
        )
        data = self._get_json(url)
        returned: dict[str, list[list[Any]]] = {}
        for entry in data.get("valueRanges", []):
            if not isinstance(entry, dict):
                continue
            rng = entry.get("range")
            values = entry.get("values", [])
            if isinstance(rng, str) and isinstance(values, list):
                returned[rng] = values

        # Google may normalize quoting in returned A1 ranges. Preserve the exact
        # requested keys expected by the comparison layer by matching suffixes.
        normalized: dict[str, list[list[Any]]] = {}
        for requested in ranges:
            if requested in returned:
                normalized[requested] = returned[requested]
                continue
            requested_tail = requested.replace("'", "")
            for actual, values in returned.items():
                if actual.replace("'", "") == requested_tail:
                    normalized[requested] = values
                    break
        return normalized
