from io import BytesIO
from zipfile import ZipFile

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response
import httpx

from app.config import get_settings


TINY_CR = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"shapeName": "Costa Rica"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[-85.9, 8.0], [-82.5, 8.0], [-82.5, 11.2], [-85.9, 11.2], [-85.9, 8.0]]
                ],
            },
        }
    ],
}


def mock_geoboundaries_cri() -> None:
    respx.get("https://www.geoboundaries.org/api/current/gbOpen/CRI/ADM0/").mock(
        return_value=Response(
            200,
            json={
                "boundaryName": "Costa Rica",
                "boundaryISO": "CRI",
                "boundaryLicense": "Open Data Commons Open Database License 1.0",
                "simplifiedGeometryGeoJSON": "https://example.test/CRI.geojson",
                "gjDownloadURL": "https://example.test/CRI-full.geojson",
            },
        )
    )
    respx.get("https://example.test/CRI.geojson").mock(return_value=Response(200, json=TINY_CR))


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@respx.mock
def test_taxon_suggest_uses_rank_hint(client: TestClient):
    respx.get("https://api.gbif.org/v1/species/match").mock(
        return_value=Response(200, json={"confidence": 100, "matchType": "NONE"})
    )
    respx.get("https://api.gbif.org/v1/species/suggest").mock(
        return_value=Response(
            200,
            json=[
                {"key": 8001309, "canonicalName": "Amphibia", "rank": "GENUS"},
                {"key": 131, "canonicalName": "Amphibia", "rank": "CLASS", "kingdom": "Animalia"},
            ],
        )
    )
    response = client.get("/v1/taxon/suggest", params={"q": "amphibians", "rankHint": "class"})
    assert response.status_code == 200
    body = response.json()
    assert body["query"]["gbifKey"] == 131
    assert body["query"]["rank"] == "CLASS"
    assert body["needsDisambiguation"] is False


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
    mock_geoboundaries_cri()
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
    assert body["boundary"]["features"]
    assert "geoBoundaries" in (body["boundaryAttribution"] or "")


@respx.mock
def test_map_colors_each_selected_taxon(client: TestClient):
    respx.get("https://api.gbif.org/v1/species/5219426").mock(
        return_value=Response(200, json={"key": 5219426, "canonicalName": "Panthera onca", "rank": "SPECIES"})
    )
    respx.get("https://api.gbif.org/v1/species/2435099").mock(
        return_value=Response(200, json={"key": 2435099, "canonicalName": "Puma concolor", "rank": "SPECIES"})
    )
    respx.get("https://api.gbif.org/v1/enumeration/country").mock(
        return_value=Response(200, json=[{"iso2": "CR", "iso3": "CRI", "title": "Costa Rica"}])
    )
    mock_geoboundaries_cri()

    def occurrence(request):
        key = request.url.params.get("taxonKey")
        name = "Panthera onca" if key == "5219426" else "Puma concolor"
        gbif_id = 111 if key == "5219426" else 222
        lat = 9.7 if key == "5219426" else 10.1
        return Response(
            200,
            json={
                "count": 2,
                "results": [
                    {
                        "gbifID": gbif_id,
                        "decimalLatitude": lat,
                        "decimalLongitude": -83.9,
                        "scientificName": name,
                        "eventDate": "2020-03-01",
                        "year": 2020,
                        "country": "Costa Rica",
                        "basisOfRecord": "HUMAN_OBSERVATION",
                        "issues": [],
                    }
                ],
                "facets": [{"field": "YEAR", "counts": [{"name": "2020", "count": 2}]}],
            },
        )

    respx.get("https://api.gbif.org/v1/occurrence/search").mock(side_effect=occurrence)
    response = client.post(
        "/v1/map",
        json={
            "taxa": [
                {"q": "Panthera onca", "gbifKey": 5219426},
                {"q": "Puma concolor", "gbifKey": 2435099},
            ],
            "place": {"q": "Costa Rica", "iso2": "CR"},
            "time": {"yearMin": 2015},
            "map": {"pointDisplay": "individual"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["blocked"] is False
    assert body["count"] == 4
    assert body["tile"] is None
    assert body["mode"] == "points"
    features = body["sample"]["features"]
    assert {feature["properties"]["taxonName"] for feature in features} == {"Panthera onca", "Puma concolor"}
    assert len({feature["properties"]["taxonColor"] for feature in features}) == 2
    assert body["query"]["map"]["pointDisplay"] == "individual"
    assert [(row["year"], row["count"]) for row in body["histogram"]] == [(2020, 4)]


@respx.mock
def test_map_histogram_uses_full_year_facet(client: TestClient):
    respx.get("https://api.gbif.org/v1/species/2481907").mock(
        return_value=Response(200, json={"key": 2481907, "canonicalName": "Vultur gryphus", "rank": "SPECIES"})
    )
    respx.get("https://api.gbif.org/v1/enumeration/country").mock(
        return_value=Response(200, json=[{"iso2": "CR", "iso3": "CRI", "title": "Costa Rica"}])
    )
    mock_geoboundaries_cri()

    seen: list[str] = []

    def search(request):
        seen.append(str(request.url))
        if "facet=year" in str(request.url):
            return Response(
                200,
                json={
                    "count": 40,
                    "results": [],
                    "facets": [
                        {
                            "field": "YEAR",
                            "counts": [{"name": "2014", "count": 10}, {"name": "2016", "count": 30}],
                        }
                    ],
                },
            )
        return Response(
            200,
            json={
                "count": 1,
                "results": [
                    {
                        "gbifID": 111,
                        "decimalLatitude": 9.7,
                        "decimalLongitude": -83.9,
                        "year": 2020,
                        "issues": [],
                    }
                ],
            },
        )

    respx.get("https://api.gbif.org/v1/occurrence/search").mock(side_effect=search)
    response = client.post(
        "/v1/map",
        json={
            "taxon": {"gbifKey": 2481907},
            "place": {"iso2": "CR"},
            "time": {"yearMin": 2015, "yearMax": 2016},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert [(item["year"], item["count"]) for item in body["histogram"]] == [
        (2014, 10),
        (2015, 0),
        (2016, 30),
    ]
    assert not any("inspectable sample" in warning for warning in body["warnings"])
    facet_urls = [url for url in seen if "facet=year" in url]
    assert facet_urls and "eventDate" not in facet_urls[0]
    assert any("eventDate" in url for url in seen)


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


@respx.mock
def test_nl_plan_maps_connection_errors_to_503(client: TestClient):
    respx.post("http://127.0.0.1:11434/v1/chat/completions").mock(side_effect=httpx.ConnectError("down"))
    response = client.post("/v1/nl/plan", json={"prompt": "show jaguars in Costa Rica"})
    assert response.status_code == 503
    assert "unreachable" in response.json()["detail"].lower()


def test_nl_without_key(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    get_settings.cache_clear()
    response = client.post("/v1/nl/plan", json={"prompt": "show jaguars in Costa Rica"})
    assert response.status_code == 503
    assert "GROQ_API_KEY" in response.json()["detail"]

    status = client.get("/v1/nl/status").json()
    assert status["available"] is False
    assert status["provider"] == "groq"


@respx.mock
def test_nl_status_defaults_to_ollama(client: TestClient):
    respx.get("http://127.0.0.1:11434/api/tags").mock(
        return_value=Response(200, json={"models": [{"name": "gemma4:latest"}]})
    )
    response = client.get("/v1/nl/status")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["provider"] == "ollama"
    assert body["model"] == "gemma4"


@respx.mock
def test_nl_status_reports_ollama_down_or_model_missing(client: TestClient):
    route = respx.get("http://127.0.0.1:11434/api/tags")
    route.mock(side_effect=httpx.ConnectError("down"))
    body = client.get("/v1/nl/status").json()
    assert body["available"] is False
    assert "ollama serve" in body["message"]

    route.mock(return_value=Response(200, json={"models": [{"name": "llama3.2:3b"}]}))
    body = client.get("/v1/nl/status").json()
    assert body["available"] is False
    assert "ollama pull gemma4" in body["message"]


def test_nl_status_hosted_provider_never_exposes_key(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-gemini-key")
    get_settings.cache_clear()
    response = client.get("/v1/nl/status")
    body = response.json()
    assert body["available"] is True
    assert body["provider"] == "gemini"
    assert "secret-gemini-key" not in response.text


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


@respx.mock
def test_qgis_export_zip(client: TestClient):
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
    mock_geoboundaries_cri()
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
            },
        )
    )
    response = client.post(
        "/v1/export/qgis",
        json={
            "taxon": {"q": "Panthera onca", "gbifKey": 5219426},
            "place": {"q": "Costa Rica", "iso2": "CR"},
            "time": {"yearMin": 2015},
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
    names = ZipFile(BytesIO(response.content)).namelist()
    assert "occurrences.geojson" in names
    assert "boundary.geojson" in names
    assert "load_in_qgis.py" in names
    assert "mapi.qgs" in names


@respx.mock
def test_taxon_autocomplete_prefers_alias_and_rank(client: TestClient):
    def suggest(request):
        q = request.url.params["q"]
        if q == "Amphibia":
            return Response(200, json=[
                {"key": 8001309, "canonicalName": "Amphibia", "rank": "GENUS", "status": "DOUBTFUL"},
                {"key": 131, "canonicalName": "Amphibia", "rank": "CLASS", "status": "ACCEPTED"},
                {"key": 999, "canonicalName": "Amphibiaceae", "rank": "FAMILY", "status": "ACCEPTED"},
            ])
        return Response(200, json=[
            {"key": 7, "canonicalName": "Amphibolis", "rank": "GENUS", "status": "SYNONYM"},
            {"key": 5, "canonicalName": "Amphibium", "rank": "GENUS", "status": "ACCEPTED"},
            {"key": 131, "canonicalName": "Amphibia", "rank": "CLASS", "status": "ACCEPTED"},
        ])

    respx.get("https://api.gbif.org/v1/species/suggest").mock(side_effect=suggest)
    body = client.get("/v1/taxon/autocomplete", params={"q": "amphib"}).json()
    assert [c["gbifKey"] for c in body["candidates"]] == [131, 5, 7]

    body = client.get("/v1/taxon/autocomplete", params={"q": "amphib", "rankHint": "genus"}).json()
    assert [c["gbifKey"] for c in body["candidates"]] == [5, 7, 131]


def test_taxon_autocomplete_short_query_is_empty(client: TestClient):
    assert client.get("/v1/taxon/autocomplete", params={"q": "a"}).json() == {"candidates": []}
    assert client.get("/v1/taxon/autocomplete", params={"q": ""}).status_code == 422


@respx.mock
def test_place_suggest_matches_and_reports_misses(client: TestClient):
    respx.get("https://api.gbif.org/v1/enumeration/country").mock(
        return_value=Response(200, json=[
            {"iso2": "CO", "iso3": "COL", "title": "Colombia"},
            {"iso2": "CR", "iso3": "CRI", "title": "Costa Rica"},
            {"iso2": "CA", "iso3": "CAN", "title": "Canada"},
        ])
    )
    body = client.get("/v1/place/suggest", params={"q": "co"}).json()
    assert [c["iso2"] for c in body["candidates"]] == ["CO", "CR"]

    body = client.get("/v1/place/suggest", params={"q": "colombia"}).json()
    assert body["query"]["iso2"] == "CO"
    assert body["needsDisambiguation"] is False

    body = client.get("/v1/place/suggest", params={"q": "Atlantis"}).json()
    assert body["candidates"] == []
    assert body["query"] is None
    assert "Atlantis" in body["warnings"][0]


@respx.mock
def test_map_unions_selected_countries(client: TestClient):
    from urllib.parse import parse_qs

    respx.get("https://api.gbif.org/v1/species/5219426").mock(
        return_value=Response(200, json={"key": 5219426, "canonicalName": "Panthera onca", "rank": "SPECIES"})
    )
    respx.get("https://api.gbif.org/v1/enumeration/country").mock(
        return_value=Response(
            200,
            json=[
                {"iso2": "CR", "iso3": "CRI", "title": "Costa Rica"},
                {"iso2": "PA", "iso3": "PAN", "title": "Panama"},
            ],
        )
    )
    mock_geoboundaries_cri()
    respx.get("https://www.geoboundaries.org/api/current/gbOpen/PAN/ADM0/").mock(
        return_value=Response(
            200,
            json={
                "boundaryName": "Panama",
                "boundaryISO": "PAN",
                "boundaryLicense": "Open Data Commons Open Database License 1.0",
                "simplifiedGeometryGeoJSON": "https://example.test/PAN.geojson",
            },
        )
    )
    respx.get("https://example.test/PAN.geojson").mock(return_value=Response(200, json=TINY_CR))

    def occurrence(request):
        raw = request.url.query.decode() if isinstance(request.url.query, bytes) else str(request.url.query)
        countries = set(parse_qs(raw).get("country", []))
        assert countries == {"CR", "PA"}
        return Response(
            200,
            json={
                "count": 3,
                "results": [
                    {
                        "gbifID": 1,
                        "decimalLatitude": 9.1,
                        "decimalLongitude": -83.0,
                        "scientificName": "Panthera onca",
                        "year": 2020,
                        "country": "Costa Rica",
                        "issues": [],
                    }
                ],
                "facets": [{"field": "YEAR", "counts": [{"name": "2020", "count": 3}]}],
            },
        )

    respx.get("https://api.gbif.org/v1/occurrence/search").mock(side_effect=occurrence)
    response = client.post(
        "/v1/map",
        json={
            "taxon": {"q": "Panthera onca", "gbifKey": 5219426},
            "places": [
                {"q": "Costa Rica", "iso2": "CR", "title": "Costa Rica"},
                {"q": "Panama", "iso2": "PA", "title": "Panama"},
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 3
    assert len(body["boundary"]["features"]) == 2
    assert {place["iso2"] for place in body["query"]["places"]} == {"CR", "PA"}
