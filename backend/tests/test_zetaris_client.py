"""Paging logic against a fake HTTP layer (no network, no httpx needed)."""
import pytest

from app.integrations.zetaris_client import ZetarisClient, ZetarisNotConfigured


class Resp:
    def __init__(self, data=None):
        self._d = data or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


class FakeHttp:
    def __init__(self, total=250, per=100):
        self.rows = [{"i": i} for i in range(total)]
        self.per, self.calls = per, []

    def post(self, url, headers, json):
        self.calls.append(("POST", url, json))
        assert headers["Authorization"] == "Bearer KEY" and headers["X-Org-ID"] == "7"
        return Resp({"records": self.rows[: self.per], "pageNumber": 1, "pageLimit": self.per,
                     "totalCount": len(self.rows), "totalPages": -(-len(self.rows) // self.per), "queryToken": "tok"})

    def get(self, url, headers, params):
        self.calls.append(("GET", url, params))
        p = params["pageNumber"]
        return Resp({"records": self.rows[(p - 1) * self.per : p * self.per], "pageNumber": p})

    def delete(self, url, headers):
        self.calls.append(("DELETE", url, None))
        return Resp()


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("ZETARIS_BASE_URL", "https://z.example")
    monkeypatch.setenv("ZETARIS_ORG_ID", "7")
    monkeypatch.setenv("ZETARIS_API_KEY", "KEY")


def test_collects_all_pages_and_closes():
    http = FakeHttp(total=250)
    rows = ZetarisClient(http).query("SELECT * FROM finops_data.usage_history")
    assert len(rows) == 250 and rows[-1] == {"i": 249}
    assert http.calls[-1][0] == "DELETE" and http.calls[-1][1].endswith("/close/tok")


def test_single_page_makes_no_page_calls():
    http = FakeHttp(total=5)
    assert len(ZetarisClient(http).query("SELECT 1")) == 5
    assert [c[0] for c in http.calls] == ["POST", "DELETE"]


def test_empty_result():
    assert ZetarisClient(FakeHttp(total=0)).query("SELECT 1") == []


def test_missing_api_key(monkeypatch):
    monkeypatch.setenv("ZETARIS_API_KEY", "")
    with pytest.raises(ZetarisNotConfigured):
        ZetarisClient(FakeHttp()).query("SELECT 1")