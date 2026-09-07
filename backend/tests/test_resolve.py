import pytest
import respx
from httpx import Response

from app.cache import reset_cache_for_tests
from app.config import get_settings
from app.models import MapQuery
from app.services.resolve import resolve_query


@pytest.fixture(autouse=True)
def _clear_cache():
    get_settings.cache_clear()
    reset_cache_for_tests()
    yield
    reset_cache_for_tests()
    get_settings.cache_clear()


MATCH_JAGUAR = {
    "usageKey": 5219426,
    "scientificName": "Panthera onca (Linnaeus, 1758)",
    "canonicalName": "Panthera onca",
    "rank": "SPECIES",
    "confidence": 98,
    "matchType": "EXACT",
    "status": "ACCEPTED",
    "kingdom": "Animalia",
    "class": "Mammalia",
}

SUGGEST_JAGUAR = [
    {
        "key": 5219426,
        "canonicalName": "Panthera onca",
        "scientificName": "Panthera onca (Linnaeus, 1758)",
        "rank": "SPECIES",
        "kingdom": "Animalia",
        "class": "Mammalia",
    }
]

COUNTRIES = [
    {"iso2": "CR", "iso3": "CRI", "title": "Costa Rica", "gbifRegion": "LATIN_AMERICA"},
    {"iso2": "PA", "iso3": "PAN", "title": "Panama", "gbifRegion": "LATIN_AMERICA"},
]


@respx.mock
@pytest.mark.asyncio
async def test_resolve_jaguar_costa_rica():
    import httpx

    respx.get("https://api.gbif.org/v1/species/match").mock(return_value=Response(200, json=MATCH_JAGUAR))
    respx.get("https://api.gbif.org/v1/species/suggest").mock(return_value=Response(200, json=SUGGEST_JAGUAR))
    respx.get("https://api.gbif.org/v1/enumeration/country").mock(return_value=Response(200, json=COUNTRIES))

    async with httpx.AsyncClient() as client:
        resolved = await resolve_query(
            client,
            MapQuery.model_validate({"taxon": {"q": "Panthera onca"}, "place": {"q": "Costa Rica"}}),
        )

    assert resolved.query.taxon and resolved.query.taxon.gbifKey == 5219426
    assert resolved.query.place and resolved.query.place.iso2 == "CR"
    assert resolved.taxonNeedsDisambiguation is False
    assert resolved.placeNeedsDisambiguation is False


@respx.mock
@pytest.mark.asyncio
async def test_resolve_amphibians_via_alias():
    import httpx

    def match_side(request):
        return Response(200, json={"confidence": 100, "matchType": "NONE"})

    respx.get("https://api.gbif.org/v1/species/match").mock(side_effect=match_side)
    respx.get("https://api.gbif.org/v1/species/suggest").mock(
        return_value=Response(
            200,
            json=[
                {"key": 8001309, "canonicalName": "Amphibia", "rank": "GENUS"},
                {"key": 131, "canonicalName": "Amphibia", "rank": "CLASS", "kingdom": "Animalia"},
            ],
        )
    )

    async with httpx.AsyncClient() as client:
        resolved = await resolve_query(
            client,
            MapQuery.model_validate({"taxon": {"q": "amphibians", "rankHint": "class"}}),
        )

    assert resolved.query.taxon and resolved.query.taxon.gbifKey == 131
    assert resolved.query.taxon.rank == "CLASS"
    assert resolved.taxonNeedsDisambiguation is False


@respx.mock
@pytest.mark.asyncio
async def test_homonym_needs_disambiguation():
    import httpx

    respx.get("https://api.gbif.org/v1/species/match").mock(
        return_value=Response(
            200,
            json={
                "usageKey": 1,
                "canonicalName": "Pica",
                "rank": "GENUS",
                "confidence": 70,
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

    async with httpx.AsyncClient() as client:
        resolved = await resolve_query(client, MapQuery.model_validate({"taxon": {"q": "Pica"}}))

    assert resolved.taxonNeedsDisambiguation is True
    assert len(resolved.taxonCandidates) >= 2
