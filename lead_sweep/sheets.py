"""Reading and writing the Lead Tracker through the Google Sheets API."""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from urllib.parse import quote

from .config import GOOGLE_SA_ENV, SHEET_ID
from .rules import DATE_FMT, phone_digits

SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetsClient:
    """Thin wrapper over the values endpoints, authenticated as a service account."""

    def __init__(self, sheet_id: str = SHEET_ID, session=None):
        self.sheet_id = sheet_id
        self.session = session or self._session_from_env()

    @staticmethod
    def _session_from_env():
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account

        raw = os.environ.get(GOOGLE_SA_ENV, "").strip()
        if not raw:
            raise RuntimeError(f"{GOOGLE_SA_ENV} is not set; the sheet can't be read or written.")
        info = json.loads(raw) if raw.startswith("{") else json.load(open(raw))
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        return AuthorizedSession(creds)

    def get_values(self, tab: str) -> list[list[str]]:
        rng = quote(f"'{tab}'", safe="")
        r = self.session.get(f"{SHEETS_API}/{self.sheet_id}/values/{rng}")
        r.raise_for_status()
        return r.json().get("values", [])

    def batch_update(self, data: list[tuple[str, list[list[str]]]]) -> None:
        """Write several ranges in one call. USER_ENTERED so dates stay real dates."""
        if not data:
            return
        body = {
            "valueInputOption": "USER_ENTERED",
            "data": [{"range": rng, "values": values} for rng, values in data],
        }
        r = self.session.post(f"{SHEETS_API}/{self.sheet_id}/values:batchUpdate", json=body)
        r.raise_for_status()


def col_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    s = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        s = chr(65 + rem) + s
    return s


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _parse_date(text: str) -> date | None:
    try:
        return datetime.strptime((text or "").strip(), DATE_FMT).date()
    except ValueError:
        return None


class TabState:
    """One tab's rows, with lookups for duplicates and the next free ID."""

    def __init__(self, name: str, prefix: str, values: list[list[str]]):
        self.name = name
        self.prefix = prefix
        self.header = values[0] if values else []
        self.rows = [r + [""] * (len(self.header) - len(r)) for r in values[1:]]
        self.col = {h: i for i, h in enumerate(self.header)}
        nums = [
            int(m.group(1))
            for r in self.rows
            if r and (m := re.fullmatch(rf"{prefix}-(\d+)", r[0].strip()))
        ]
        self._next = max(nums, default=0) + 1

    def cell(self, row: list[str], column: str) -> str:
        i = self.col.get(column)
        return row[i] if i is not None and i < len(row) else ""

    def next_id(self) -> str:
        new_id = f"{self.prefix}-{self._next:04d}"
        self._next += 1
        return new_id

    @property
    def next_row_number(self) -> int:
        """1-based sheet row for the next appended row (header is row 1)."""
        return len(self.rows) + 2

    def find(self, name: str = "", phone: str = "", email: str = "", meta_lead_id: str = "") -> int | None:
        """Index of an existing row for this person, or None.

        Matches by email, phone digits, or Meta lead ID. An exact name match counts only
        when the name has two or more words, so a one-word name like "Robert" doesn't
        collide with a different Robert.
        """
        email = (email or "").strip().lower()
        digits = phone_digits(phone)
        name_n = _norm_name(name)
        for i, r in enumerate(self.rows):
            if email and self.cell(r, "Email").strip().lower() == email:
                return i
            if len(digits) == 10 and phone_digits(self.cell(r, "Phone")) == digits:
                return i
            if meta_lead_id and f"Meta lead ID: {meta_lead_id}" in self.cell(r, "Message / Notes"):
                return i
            if name_n and len(name_n.split()) >= 2 and _norm_name(self.cell(r, "Name")) == name_n:
                return i
        return None

    def append(self, row: list[str]) -> int:
        self.rows.append(row + [""] * (len(self.header) - len(row)))
        return len(self.rows) - 1

    def latest_date(self, *columns: str) -> date | None:
        dates = [
            d for r in self.rows for c in columns if (d := _parse_date(self.cell(r, c)))
        ]
        return max(dates, default=None)
