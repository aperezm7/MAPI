import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from app.config import get_settings


def _client(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def test_auth_bootstraps_one_team_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.delenv("MAPI_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("MAPI_SECRET_KEY", raising=False)
    get_settings.cache_clear()
    from app.accounts import ANONYMOUS_ID, list_clients
    from app.bootstrap import bootstrap_team_client, prepare_runtime
    from app.db import reset_db_for_tests

    reset_db_for_tests()
    prepare_runtime()
    settings = get_settings()
    assert settings.auth_required is True
    assert settings.mapi_admin_token
    assert settings.mapi_secret_key
    admin = settings.mapi_admin_token
    bootstrap_team_client()
    key = (tmp_path / "team-api-key.txt").read_text().strip()
    assert key.startswith("mapi_")
    bootstrap_team_client()
    prepare_runtime()
    assert (tmp_path / "team-api-key.txt").read_text().strip() == key
    assert get_settings().mapi_admin_token == admin
    named = [item for item in list_clients() if item.id != ANONYMOUS_ID]
    assert [item.name for item in named] == ["team"]
    assert not (tmp_path / "secrets.env").read_text().startswith("GBIF")


def test_open_access_does_not_bootstrap(tmp_path):
    get_settings.cache_clear()
    from app.bootstrap import bootstrap_team_client, prepare_runtime

    prepare_runtime()
    bootstrap_team_client()
    assert not (tmp_path / "secrets.env").exists()
    assert not (tmp_path / "team-api-key.txt").exists()


def test_open_access_logs_a_resolve(client: TestClient):
    status = client.get("/v1/account/status")
    assert status.status_code == 200
    assert status.json()["authRequired"] is False
    assert status.json()["prices"]["map"] == 1

    response = client.post("/v1/query/resolve", json={})
    assert response.status_code == 200
    account = client.get("/v1/account").json()
    assert account["unlimited"] is True
    listed = client.get("/v1/account/queries").json()["queries"]
    assert listed[0]["kind"] == "resolve"
    assert listed[0]["cost"] == 0


def test_admin_key_is_required_for_maps_and_records_cost(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    _client(monkeypatch, AUTH_REQUIRED="true", MAPI_ADMIN_TOKEN="admin-secret", MAPI_SECRET_KEY="test-secret")
    assert client.post("/v1/query/resolve", json={}).status_code == 401
    assert client.post("/v1/clients", json={"name": "lab"}).status_code == 401

    created = client.post(
        "/v1/clients",
        headers={"X-Admin-Token": "admin-secret"},
        json={"name": "lab", "budget": 1, "mapsPerDay": 2, "requestsPerMinute": 5},
    )
    assert created.status_code == 200
    body = created.json()
    api_key = body["apiKey"]
    assert api_key.startswith("mapi_")
    assert "apiKey" not in client.get("/v1/clients", headers={"X-Admin-Token": "admin-secret"}).text

    headers = {"Authorization": f"Bearer {api_key}"}
    resolved = client.post("/v1/query/resolve", headers=headers, json={})
    assert resolved.status_code == 200
    account = client.get("/v1/account", headers=headers).json()
    assert account["name"] == "lab"
    assert account["spent"] == pytest.approx(0.1)
    assert account["gbif"]["connected"] is False
    queries = client.get("/v1/account/queries", headers=headers).json()["queries"]
    assert queries[0]["summary"] == "unscoped query"
    assert queries[0]["cost"] == pytest.approx(0.1)


def test_budget_rate_and_map_limits(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    _client(monkeypatch, AUTH_REQUIRED="true", MAPI_ADMIN_TOKEN="admin-secret")
    admin = {"X-Admin-Token": "admin-secret"}
    broke = client.post(
        "/v1/clients", headers=admin, json={"name": "broke", "budget": 0, "requestsPerMinute": 10}
    ).json()
    broke_headers = {"Authorization": f"Bearer {broke['apiKey']}"}
    assert client.post("/v1/query/resolve", headers=broke_headers, json={}).status_code == 402
    assert client.patch(f"/v1/clients/{broke['id']}", headers=admin, json={"budget": 10}).status_code == 200
    assert client.post("/v1/query/resolve", headers=broke_headers, json={}).status_code == 200

    slow = client.post(
        "/v1/clients", headers=admin, json={"name": "slow", "budget": 10, "requestsPerMinute": 1}
    ).json()
    slow_headers = {"Authorization": f"Bearer {slow['apiKey']}"}
    assert client.post("/v1/query/resolve", headers=slow_headers, json={}).status_code == 200
    limited = client.post("/v1/query/resolve", headers=slow_headers, json={})
    assert limited.status_code == 429
    assert "per minute" in limited.json()["detail"]

    capped = client.post(
        "/v1/clients",
        headers=admin,
        json={"name": "capped", "budget": 10, "requestsPerMinute": 10, "mapsPerDay": 0},
    ).json()
    mapped = client.post(
        "/v1/map",
        headers={"Authorization": f"Bearer {capped['apiKey']}"},
        json={"taxon": {"q": "x", "gbifKey": 1}},
    )
    assert mapped.status_code == 429
    assert "map limit" in mapped.json()["detail"]


def test_inactive_key_is_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    _client(monkeypatch, AUTH_REQUIRED="true", MAPI_ADMIN_TOKEN="admin-secret")
    created = client.post(
        "/v1/clients",
        headers={"X-Admin-Token": "admin-secret"},
        json={"name": "paused"},
    ).json()
    client.patch(
        f"/v1/clients/{created['id']}",
        headers={"X-Admin-Token": "admin-secret"},
        json={"active": False},
    )
    response = client.get("/v1/account", headers={"Authorization": f"Bearer {created['apiKey']}"})
    assert response.status_code == 401


@respx.mock
def test_gbif_account_is_verified_and_used_for_downloads(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    _client(monkeypatch, AUTH_REQUIRED="true", MAPI_ADMIN_TOKEN="admin-secret", MAPI_SECRET_KEY="test-secret")
    created = client.post(
        "/v1/clients",
        headers={"X-Admin-Token": "admin-secret"},
        json={"name": "gbif-user", "budget": 20},
    ).json()
    headers = {"Authorization": f"Bearer {created['apiKey']}"}

    attempts = {"n": 0}

    def login(request):
        assert request.headers["Authorization"].startswith("Basic ")
        attempts["n"] += 1
        if attempts["n"] == 1:
            return Response(401, json={"message": "no"})
        return Response(200, json={"userName": "ada"})

    respx.get("https://api.gbif.org/v1/user/login").mock(side_effect=login)
    rejected = client.put(
        "/v1/account/gbif",
        headers=headers,
        json={"username": "ada", "password": "wrong", "email": "ada@example.test"},
    )
    assert rejected.status_code == 401
    connected = client.put(
        "/v1/account/gbif",
        headers=headers,
        json={"username": "ada", "password": "correct-horse", "email": "ada@example.test"},
    )
    assert connected.status_code == 200
    assert connected.json()["gbif"] == {
        "connected": True,
        "username": "ada",
        "email": "ada@example.test",
    }
    assert "correct-horse" not in connected.text

    respx.get("https://api.gbif.org/v1/species/5219426").mock(
        return_value=Response(200, json={"key": 5219426, "canonicalName": "Panthera onca", "rank": "SPECIES"})
    )

    def download(request):
        assert request.headers["Authorization"].startswith("Basic ")
        import base64

        raw = base64.b64decode(request.headers["Authorization"].split()[1]).decode()
        assert raw == "ada:correct-horse"
        return Response(201, text='"0001234-250000000000000"')

    respx.post("https://api.gbif.org/v1/occurrence/download/request").mock(side_effect=download)
    result = client.post(
        "/v1/downloads/gbif",
        headers=headers,
        json={"query": {"taxon": {"q": "Panthera onca", "gbifKey": 5219426}}},
    )
    assert result.status_code == 200
    assert result.json()["available"] is True
    assert result.json()["key"] == "0001234-250000000000000"

    cleared = client.delete("/v1/account/gbif", headers=headers)
    assert cleared.json()["gbif"]["connected"] is False
