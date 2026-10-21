"""Export tickets from ServiceNow with the REST Table API and OAuth."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import requests

from .config import Settings

# Fields used for analysis. Fields a table does not have are simply not returned.
TICKET_FIELDS = [
    "sys_id",
    "number",
    "sys_class_name",
    "short_description",
    "description",
    "category",
    "subcategory",
    "priority",
    "state",
    "assignment_group",
    "cmdb_ci",
    "cat_item",
    "sys_created_on",
    "resolved_at",
    "closed_at",
    "close_code",
    "made_sla",
]

# Fetched only so their names can be removed from free text; never kept or sent anywhere.
PERSON_FIELDS = ["caller_id", "opened_by", "assigned_to", "requested_for"]

SLA_FIELDS = [
    "task.number",
    "task.sys_class_name",
    "sla",
    "stage",
    "has_breached",
    "business_percentage",
    "start_time",
]

PAGE_SIZE = 1000


class ServiceNowError(RuntimeError):
    pass


class ServiceNowClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self.session = requests.Session()
        self.session.verify = settings.verify_ssl
        self.session.headers["Accept"] = "application/json"
        self._token: str | None = None

    # ---- auth -------------------------------------------------------------
    def _get_token(self) -> str:
        data = {
            "grant_type": self.s.grant_type,
            "client_id": self.s.client_id,
            "client_secret": self.s.client_secret,
        }
        if self.s.grant_type == "password":
            data["username"] = self.s.username
            data["password"] = self.s.password
        resp = self.session.post(f"{self.s.instance_url}/oauth_token.do", data=data, timeout=60)
        if resp.status_code != 200:
            raise ServiceNowError(
                f"OAuth token request failed ({resp.status_code}). "
                "Check SN_CLIENT_ID, SN_CLIENT_SECRET, SN_USERNAME and SN_PASSWORD."
            )
        token = resp.json().get("access_token")
        if not token:
            raise ServiceNowError("OAuth response did not contain an access_token.")
        return token

    def _auth_header(self) -> dict[str, str]:
        if self._token is None:
            self._token = self._get_token()
        return {"Authorization": f"Bearer {self._token}"}

    # ---- low level --------------------------------------------------------
    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.s.instance_url}{path}"
        for attempt in range(5):
            resp = self.session.get(url, params=params, headers=self._auth_header(), timeout=120)
            if resp.status_code == 401 and attempt == 0:
                self._token = None  # token expired, get a new one
                continue
            if resp.status_code in (429, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            if resp.status_code != 200:
                raise ServiceNowError(f"GET {path} failed ({resp.status_code}): {resp.text[:300]}")
            return resp.json()
        raise ServiceNowError(f"GET {path} kept failing after retries.")

    def query_table(self, table: str, query: str, fields: list[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            params = {
                "sysparm_query": query,
                "sysparm_fields": ",".join(fields),
                "sysparm_display_value": "all",
                "sysparm_exclude_reference_link": "true",
                "sysparm_limit": PAGE_SIZE,
                "sysparm_offset": offset,
            }
            batch = self._get(f"/api/now/table/{table}", params).get("result", [])
            rows.extend(batch)
            if len(batch) < PAGE_SIZE:
                return rows
            offset += PAGE_SIZE

    # ---- high level -------------------------------------------------------
    def fetch_tickets(self, days: int) -> list[dict[str, Any]]:
        fields = TICKET_FIELDS + PERSON_FIELDS + self.s.barcode_fields
        query = f"sys_created_on>=javascript:gs.daysAgoStart({days})^ORDERBYsys_created_on"
        tickets: list[dict[str, Any]] = []
        for table in self.s.tables:
            raw = self.query_table(table, query, fields)
            tickets.extend(normalize(r, table) for r in raw)
        return tickets

    def fetch_breached_slas(self, days: int) -> list[dict[str, Any]]:
        query = f"task.sys_created_on>=javascript:gs.daysAgoStart({days})^has_breached=true"
        raw = self.query_table("task_sla", query, SLA_FIELDS)
        out = []
        for r in raw:
            out.append(
                {
                    "number": _display(r.get("task.number")),
                    "type": _display(r.get("task.sys_class_name")),
                    "sla": _display(r.get("sla")),
                    "stage": _display(r.get("stage")),
                    "business_percentage": _value(r.get("business_percentage")),
                }
            )
        return out


# ---- helpers ---------------------------------------------------------------
DATE_FIELDS = {"sys_created_on", "resolved_at", "closed_at"}


def _display(v: Any) -> str:
    if isinstance(v, dict):
        return str(v.get("display_value") or v.get("value") or "")
    return "" if v is None else str(v)


def _value(v: Any) -> str:
    if isinstance(v, dict):
        return str(v.get("value") or "")
    return "" if v is None else str(v)


def parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    return None


def normalize(raw: dict[str, Any], table: str) -> dict[str, Any]:
    """Flatten a ServiceNow row: display values for labels, raw UTC values for dates."""
    t: dict[str, Any] = {"table": table}
    for k, v in raw.items():
        t[k] = _value(v) if k in DATE_FIELDS else _display(v)
    t["category"] = t.get("category") or t.get("cat_item") or ""
    return t
