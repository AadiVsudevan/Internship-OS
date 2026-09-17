"""Google Sheets REST persistence with bounded retries and human-owned columns.

All values use explicit string/number cells: source text can never become a formula.
Updates target deterministic rows; retrying a timed-out batch cannot append duplicates.
"""
from __future__ import annotations

import json
import os
import random
import time
from typing import Any
from urllib.parse import quote

from src.personal_engine import SCHEMAS, AUTO_COLUMNS, PACK_COLUMNS


class SheetsClient:
    def __init__(self, spreadsheet_id: str, session: Any = None):
        if not spreadsheet_id or not all(c.isalnum() or c in "_-" for c in spreadsheet_id):
            raise ValueError("Set GOOGLE_SHEET_ID to the destination spreadsheet ID")
        self.base = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
        if session is None:
            from google.oauth2 import service_account
            from google.auth.transport.requests import AuthorizedSession
            raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
            if not raw:
                raise ValueError("Set GOOGLE_SERVICE_ACCOUNT_JSON in GitHub Secrets; never commit it")
            info = json.loads(raw)
            credentials = service_account.Credentials.from_service_account_info(
                info, scopes=["https://www.googleapis.com/auth/spreadsheets"])
            session = AuthorizedSession(credentials)
        self.session = session

    def request(self, method: str, path: str = "", **kwargs: Any) -> dict:
        """Retry transient HTTP/transport errors; permanent auth/schema errors fail fast."""
        import requests
        for attempt in range(5):
            retry_after = 0.0
            try:
                response = self.session.request(method, self.base + path, timeout=30, **kwargs)
                if response.status_code not in {429, 500, 502, 503, 504}:
                    response.raise_for_status()
                    return response.json()
                try:
                    retry_after = min(30, float(response.headers.get("Retry-After", 0)))
                except ValueError:
                    pass
                if attempt == 4:
                    response.raise_for_status()
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 4:
                    raise
            time.sleep(max(retry_after, min(16, 2 ** attempt) + random.random()))
        raise RuntimeError("Sheets request exhausted retries")

    def metadata(self) -> dict:
        data = self.request("GET", params={"fields": "sheets.properties,spreadsheetUrl"})
        return {s["properties"]["title"]: s["properties"] for s in data["sheets"]}

    def read(self, title: str) -> list[list]:
        end = column_letter(len(SCHEMAS[title]))
        return self.request("GET", "/values/" + quote(f"'{title}'!A:{end}", safe=""),
                            params={"valueRenderOption": "UNFORMATTED_VALUE", "dateTimeRenderOption": "FORMATTED_STRING"}).get("values", [])

    def batch(self, requests: list[dict]) -> None:
        chunk, size = [], 0
        for request in requests:
            item_size = len(json.dumps(request).encode())
            if chunk and size + item_size > 1_500_000:
                self.request("POST", ":batchUpdate", json={"requests": chunk})
                chunk, size = [], 0
            chunk.append(request)
            size += item_size
        if chunk:
            self.request("POST", ":batchUpdate", json={"requests": chunk})


def column_letter(number: int) -> str:
    out = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        out = chr(65 + remainder) + out
    return out


def cells(values: list) -> dict:
    return {"values": [{"userEnteredValue": {"numberValue": value} if isinstance(value, (int, float))
                        else {"stringValue": str(value or "")}} for value in values]}


def update_cells(sheet_id: int, row: int, rows: list[list]) -> dict:
    return {"updateCells": {"start": {"sheetId": sheet_id, "rowIndex": row, "columnIndex": 0},
                            "rows": [cells(r) for r in rows], "fields": "userEnteredValue"}}


def parse_rows(title: str, values: list[list]) -> list[dict]:
    if not values or values[0] != SCHEMAS[title]:
        raise ValueError(f"Unexpected headers in {title}; refusing to overwrite")
    records = []
    keys = set()
    for i, row in enumerate(values[1:], 2):
        if not row:
            continue
        if not row[0]:
            if any(row):
                raise ValueError(f"Missing stable ID in {title} row {i}")
            continue
        if row[0] in keys:
            raise ValueError(f"Duplicate ID in {title} row {i}")
        keys.add(row[0])
        records.append({**dict(zip(SCHEMAS[title], row)), "_row": i - 1})
    return records


class SheetsStore:
    def __init__(self, client: SheetsClient):
        self.client = client

    def setup(self) -> None:
        """Idempotently add missing tabs; refuse schema conflicts on existing tabs."""
        meta = self.client.metadata()
        missing = [title for title in SCHEMAS if title not in meta]
        if missing:
            # A lost addSheet response may already have succeeded: reconcile metadata,
            # then let the next setup retry initialize any blank tabs.
            try:
                self.client.batch([{"addSheet": {"properties": {"title": title,
                    "gridProperties": {"rowCount": 1000, "columnCount": len(SCHEMAS[title])}}}} for title in missing])
            except Exception:
                if any(title not in self.client.metadata() for title in missing):
                    raise
            meta = self.client.metadata()
        requests = []
        for title, headers in SCHEMAS.items():
            values = self.client.read(title)
            if values:
                parse_rows(title, values)
                continue
            sid = meta[title]["sheetId"]
            requests += [update_cells(sid, 0, [headers]),
                {"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}},
                {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1}, "cell": {"userEnteredFormat": {
                    "backgroundColor": {"red": 0.93, "green": 0.94, "blue": 0.95},
                    "textFormat": {"bold": True, "foregroundColor": {"red": 0, "green": 0, "blue": 0}}}}, "fields": "userEnteredFormat"}},
                {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 1}, "cell": {"userEnteredFormat": {"wrapStrategy": "CLIP", "verticalAlignment": "TOP"}}, "fields": "userEnteredFormat"}},
                {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": len(headers)}, "properties": {"pixelSize": 180}, "fields": "pixelSize"}},
                {"setBasicFilter": {"filter": {"range": {"sheetId": sid, "startRowIndex": 0, "startColumnIndex": 0, "endColumnIndex": len(headers)}}}}]
            if title == "Personal Review":
                requests.append({"setDataValidation": {"range": {"sheetId": sid, "startRowIndex": 1,
                    "startColumnIndex": 11, "endColumnIndex": 12}, "rule": {"condition": {"type": "ONE_OF_LIST",
                    "values": [{"userEnteredValue": v} for v in ["Unreviewed", "Approve", "Hold", "Reject"]]},
                    "strict": True, "showCustomUi": True}}})
            if title == "Application Packs":
                requests.append({"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 4}, "properties": {"pixelSize": 500}, "fields": "pixelSize"}})
            for col, options in ({18: ["New", "To Apply", "Drafting", "Applied", "Interview", "Offer", "Rejected", "Withdrawn", "Skip", "Closed"],
                                  19: ["Unknown", "Eligible", "Ineligible"]} if title == "Opportunities" else {}).items():
                requests.append({"setDataValidation": {"range": {"sheetId": sid, "startRowIndex": 1, "startColumnIndex": col, "endColumnIndex": col + 1},
                    "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": o} for o in options]}, "strict": True, "showCustomUi": True}}})
            if title in {"Opportunities", "Application Packs"}:
                end = len(AUTO_COLUMNS) if title == "Opportunities" else len(PACK_COLUMNS)
                requests.append({"addProtectedRange": {"protectedRange": {"range": {"sheetId": sid, "endColumnIndex": end},
                    "description": "Refreshed by Opportunity OS. Edit the columns to the right; use filter views instead of sorting during a run.", "warningOnly": True}}})
                requests.append({"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 1, "startColumnIndex": end},
                    "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.93, "green": 0.97, "blue": 1}}}, "fields": "userEnteredFormat.backgroundColor"}})
        self.client.batch(requests)

    def load(self, title: str) -> list[dict]:
        return parse_rows(title, self.client.read(title))

    def upsert(self, title: str, records: list[dict], machine_columns: list[str]) -> None:
        """Read row positions immediately before writing machine columns only."""
        existing = self.load(title)
        meta = self.client.metadata()[title]
        by_id = {r["ID"]: r for r in existing}
        next_row = max((r["_row"] for r in existing), default=0) + 1
        requests = []
        for record in records:
            key = record["ID"]
            old = by_id.get(key)
            row = old["_row"] if old else next_row
            if not old:
                next_row += 1
            requests.append(update_cells(meta["sheetId"], row, [[record.get(c, "") for c in machine_columns]]))
        self._grow(meta, next_row, requests)
        self.client.batch(requests)

    def replace(self, title: str, records: list[dict]) -> None:
        """Replace a machine-owned snapshot and clear leftover rows in one batch."""
        old = self.load(title)
        meta = self.client.metadata()[title]
        headers = SCHEMAS[title]
        count = max(len(records), max((r["_row"] for r in old), default=0))
        rows = [[r.get(c, "") for c in headers] for r in records]
        rows += [[""] * len(headers) for _ in range(count - len(rows))]
        requests = [update_cells(meta["sheetId"], 1, rows)] if rows else []
        self._grow(meta, count + 1, requests)
        self.client.batch(requests)

    def audit(self, record: dict) -> None:
        title = "Run History"
        old = self.load(title)
        meta = self.client.metadata()[title]
        matching = next((r for r in old if r["Run ID"] == record["Run ID"]), None)
        row = matching["_row"] if matching else max((r["_row"] for r in old), default=0) + 1
        requests = [update_cells(meta["sheetId"], row, [[record.get(c, "") for c in SCHEMAS[title]]])]
        self._grow(meta, row + 1, requests)
        self.client.batch(requests)

    @staticmethod
    def _grow(meta: dict, required: int, requests: list[dict]) -> None:
        if required > meta["gridProperties"]["rowCount"]:
            requests.insert(0, {"updateSheetProperties": {"properties": {"sheetId": meta["sheetId"],
                "gridProperties": {"rowCount": required + 100}}, "fields": "gridProperties.rowCount"}})
