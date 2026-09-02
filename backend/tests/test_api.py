import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from app.cache import reset_cache_for_tests
from app.config import get_settings
from app.main import create_app


@pytest.fixture
def client():
    get_settings.cache_clear()
    reset_cache_for_tests()
    with TestClient(create_app()) as test_client:
        yield test_client
    reset_cache_for_tests()
    get_settings.cache_clear()


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@respx.mock
def test_map_blocked_without_disambiguation_choice(client: TestClient):
    respx.get("https://api.gbif.org/v1/species/match").mock(
        return_value=Response(
            200,
            json={
                "usageKey": 1,
                "canonicalName": "Pica",
                "rank": "GENUS",
                "confidence": 60,
                "matchType": "FUZZY",
            },
        )
    )
    respx.get("https://api.gbif.org/v1/species/suggest").mock(
        return_value=Response(
            200,
            json=[
                {"key": 1, "canonicalName": "Pica", "rank": "GENUS"},
                {"key": 2, "canonicalName": "Pica pica", "rank": "SPECIES"},
            ],
        )
    )
    response = client.post("/v1/map", json={"taxon": {"q": "Pica"}})
    assert response.status_code == 200
    body = response.json()
    assert body["blocked"] is True
    assert body["taxonNeedsDisambiguation"] is True


@respx.mock
def test_map_with_resolved_jaguar(client: TestClient):
    respx.get("https://api.gbif.org/v1/species/5219426").mock(
        return_value=Response(
            200,
            json={
                "key": 5219426,
                "scientificName": "Panthera onca (Linnaeus, 1758)",
                "canonicalName": "Panthera onca",
                "rank": "SPECIES",
                "kingdom": "Animalia",
            },
        )
    )
    respx.get("https://api.gbif.org/v1/enumeration/country").mock(
        return_value=Response(
            200,
            json=[{"iso2": "CR", "iso3": "CRI", "title": "Costa Rica"}],
        )
    )
    respx.get("https://api.gbif.org/v1/occurrence/search").mock(
        return_value=Response(
            200,
            json={
                "count": 1,
                "results": [
                    {
                        "gbifID": 111,
                        "decimalLatitude": 9.7,
                        "decimalLongitude": -83.9,
                        "scientificName": "Panthera onca",
                        "eventDate": "2020-03-01",
                        "country": "Costa Rica",
                        "basisOfRecord": "HUMAN_OBSERVATION",
                        "issues": [],
                    }
                ],
                "facets": [{"field": "YEAR", "counts": [{"name": "2020", "count": 1}]}],
            },
        )
    )
    response = client.post(
        "/v1/map",
        json={
            "taxon": {"q": "Panthera onca", "gbifKey": 5219426},
            "place": {"q": "Costa Rica", "iso2": "CR"},
            "time": {"yearMin": 2015},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["blocked"] is False
    assert body["count"] == 1
    assert body["sample"]["features"][0]["properties"]["gbifID"] == 111
    assert "occurrence/density" in (body["tile"] or {}).get("urlTemplate", "") or body["mode"] == "points"
    assert any("GBIF" in line for line in body["attribution"])


@respx.mock
def test_iucn_without_token(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    class Dummy:
        iucn_api_token = None
        iucn_base_url = "https://api.iucnredlist.org"
        gbif_user_agent = "MAPI-test"

    monkeypatch.setattr("app.services.iucn.get_settings", lambda: Dummy())
    response = client.get("/v1/species/iucn", params={"name": "Panthera onca"})
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert "token" in (body["message"] or "").lower()


def test_nl_without_key(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    class Dummy:
        openai_api_key = None
        openai_model = "gpt-4o-mini"
        openai_base_url = "https://api.openai.com/v1"

    monkeypatch.setattr("app.services.llm.get_settings", lambda: Dummy())
    response = client.post("/v1/nl/plan", json={"prompt": "show jaguars in Costa Rica"})
    assert response.status_code == 503


@respx.mock
def test_download_without_gbif_account(client: TestClient):
    respx.get("https://api.gbif.org/v1/species/5219426").mock(
        return_value=Response(
            200,
            json={
                "key": 5219426,
                "scientificName": "Panthera onca",
                "canonicalName": "Panthera onca",
                "rank": "SPECIES",
            },
        )
    )
    response = client.post(
        "/v1/downloads/gbif",
        json={"query": {"taxon": {"q": "Panthera onca", "gbifKey": 5219426}}},
    )
    assert response.status_code == 200
    assert response.json()["available"] is False
