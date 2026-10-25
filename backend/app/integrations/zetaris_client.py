"""
Zetaris access (Developer 1), written from the Zetaris OpenAPI spec (docs.yaml, v1).

Auth
  * Login:        GET  /api/v1.0/auth/login      Basic auth (username/password)  -> {idToken, refreshToken}
  * Everything else uses  Authorization: Bearer <API token>  (create it under "API Tokens" in the UI)
  * Every call needs headers  X-Request-ID (uuid)  and  X-Org-ID (integer)

SQL query flow (paged, max 100 records/page)
  1. POST   /api/v1.0/query/sql/start             {"select": "...", "pageLimit": N} -> first page + queryToken
  2. GET    /api/v1.0/query/sql/page?queryToken=&pageLimit=&pageNumber=             -> later pages
  3. DELETE /api/v1.0/query/sql/close/{queryToken}

Nothing runs unless ZETARIS_* env vars are set; the app falls back to local files.
"""
from __future__ import annotations

import os
import uuid
from typing import Any

MAX_PAGE = 100  # documented maximum for pageLimit
DEFAULT_DATABASE = "finops_data"
TABLES = ("deployments", "usage_history", "business_events", "incident_history")


class ZetarisNotConfigured(RuntimeError):
    pass


class ZetarisClient:
    def __init__(self, http: Any | None = None) -> None:
        self.base_url = os.getenv("ZETARIS_BASE_URL", "").rstrip("/")
        self.org_id = os.getenv("ZETARIS_ORG_ID", "")
        self.username = os.getenv("ZETARIS_USERNAME", "")
        self.password = os.getenv("ZETARIS_PASSWORD", "")
        self.api_key = os.getenv("ZETARIS_API_KEY", "")
        if not (self.base_url and self.org_id):
            raise ZetarisNotConfigured("Set ZETARIS_BASE_URL and ZETARIS_ORG_ID in .env (see .env.example)")
        if http is None:
            import httpx  # imported lazily so tests can inject a fake

            http = httpx.Client(timeout=30)
        self._http = http

    # ------------------------------------------------------------------ helpers
    def _headers(self, bearer: str | None = None) -> dict[str, str]:
        h = {"X-Request-ID": str(uuid.uuid4()), "X-Org-ID": str(self.org_id)}
        if bearer:
            h["Authorization"] = f"Bearer {bearer}"
        return h

    def _api_headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ZetarisNotConfigured("ZETARIS_API_KEY is empty (create one under 'API Tokens' in the Zetaris UI)")
        return self._headers(self.api_key)

    # ------------------------------------------------------------------ auth
    def login(self) -> dict:
        """Returns {"idToken": ..., "refreshToken": ...}. Run scripts/check_zetaris.py."""
        if not (self.username and self.password):
            raise ZetarisNotConfigured("ZETARIS_USERNAME / ZETARIS_PASSWORD are empty")
        r = self._http.get(
            f"{self.base_url}/api/v1.0/auth/login",
            headers=self._headers(),
            auth=(self.username, self.password),
        )
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------ SQL
    def query(self, sql: str, page_limit: int = MAX_PAGE) -> list[Any]:
        """Run a SQL query and return ALL records (paged internally), closing the query afterwards.

        Records are returned exactly as Zetaris sends them ('records' is an untyped JSON list in the spec),
        so check the shape with scripts/check_zetaris_query.py before relying on field names.
        """
        page_limit = max(1, min(page_limit, MAX_PAGE))
        r = self._http.post(
            f"{self.base_url}/api/v1.0/query/sql/start",
            headers=self._api_headers(),
            json={"select": sql, "pageLimit": page_limit},
        )
        r.raise_for_status()
        first = r.json()
        token = first["queryToken"]
        records = _response_records(first)
        total_count = _optional_int(first.get("totalCount", first.get("total_count")))
        total_pages = _optional_int(first.get("totalPages", first.get("total_pages")))
        page = int(first.get("pageNumber", 1))
        try:
            while True:
                has_more = _has_more(first)
                if has_more is False:
                    break
                if total_count is not None and len(records) >= total_count:
                    break
                if total_pages is not None and page >= total_pages:
                    break
                if not records:
                    break
                if (total_count is None and total_pages is None and has_more is None
                        and len(records) < page_limit):
                    break

                page += 1
                pr = self._http.get(
                    f"{self.base_url}/api/v1.0/query/sql/page",
                    headers=self._api_headers(),
                    params={"queryToken": token, "pageLimit": page_limit, "pageNumber": page},
                )
                pr.raise_for_status()
                page_response = pr.json()
                recs = _response_records(page_response)
                if not recs:
                    break
                records.extend(recs)
                first = page_response
                page = int(page_response.get("pageNumber", page))
                total_count = _optional_int(
                    page_response.get("totalCount", page_response.get("total_count"))
                ) or total_count
                total_pages = _optional_int(
                    page_response.get("totalPages", page_response.get("total_pages"))
                ) or total_pages
                if (total_count is None and total_pages is None and _has_more(page_response) is None
                        and len(recs) < page_limit):
                    break
        finally:
            try:
                self._http.delete(
                    f"{self.base_url}/api/v1.0/query/sql/close/{token}", headers=self._api_headers()
                )
            except Exception:
                pass  # closing is best-effort
        return records

    def fetch_raw_tables(self, database: str = DEFAULT_DATABASE) -> dict[str, list[Any]]:
        """SELECT * from each project table. Returns {table_name: [records]}."""
        return {t: self.query(f"SELECT * FROM {database}.{t}") for t in TABLES}


def _response_records(response: dict[str, Any]) -> list[Any]:
    """Extract rows from common Zetaris response field names."""
    for key in ("records", "data", "results"):
        rows = response.get(key)
        if isinstance(rows, list):
            return rows
    return []


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _has_more(response: dict[str, Any]) -> bool | None:
    for key in ("hasMore", "has_more", "hasNext", "has_next"):
        if key in response:
            value = response[key]
            if isinstance(value, str):
                return value.strip().lower() in {"true", "1", "yes"}
            return bool(value)
    for key in ("next_page", "nextPage"):
        if key in response:
            return response[key] not in (None, False, "", 0)
    return None
