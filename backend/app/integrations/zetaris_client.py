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
        total = int(first.get("totalCount", 0))
        records: list[Any] = list(first.get("records") or [])
        try:
            page = int(first.get("pageNumber", 0))
            # Stop on: all rows received, an empty page, or a safety cap (guards against a paging bug).
            for _ in range(int(first.get("totalPages", 1)) + 2):
                if len(records) >= total:
                    break
                page += 1
                pr = self._http.get(
                    f"{self.base_url}/api/v1.0/query/sql/page",
                    headers=self._api_headers(),
                    params={"queryToken": token, "pageLimit": page_limit, "pageNumber": page},
                )
                pr.raise_for_status()
                recs = pr.json().get("records") or []
                if not recs:
                    break
                records.extend(recs)
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