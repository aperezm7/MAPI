from __future__ import annotations

from typing import Any

import httpx

from app.cache import cache_get, cache_set
from app.config import get_settings
from app.models import IucnStatusResponse
from app.rate_limit import iucn_limiter


def _split_binomial(name: str) -> tuple[str, str] | None:
    parts = [p for p in name.replace("×", " ").split() if p and not p.endswith(".")]
    # Drop authorship tokens that start lowercase or are all-caps abbreviations poorly; keep first two words.
    cleaned = [p.strip(",") for p in parts if p[0].isalpha()]
    if len(cleaned) < 2:
        return None
    return cleaned[0], cleaned[1]


async def iucn_status(client: httpx.AsyncClient, scientific_name: str) -> IucnStatusResponse:
    settings = get_settings()
    citation = "IUCN 2026. IUCN Red List of Threatened Species. Version 2026-1 www.iucnredlist.org"
    if not settings.iucn_api_token:
        return IucnStatusResponse(
            available=False,
            taxonName=scientific_name,
            citation=citation,
            message="IUCN Red List v4 token is not configured. Map filters still use GBIF iucnRedListCategory.",
        )

    split = _split_binomial(scientific_name)
    if not split:
        return IucnStatusResponse(
            available=False,
            taxonName=scientific_name,
            citation=citation,
            message="IUCN lookup needs a binomial scientific name.",
        )
    genus, species = split
    cache_key = f"iucn:v4:{genus}:{species}"
    cached = await cache_get(cache_key)
    if cached:
        return IucnStatusResponse.model_validate(cached)

    await iucn_limiter.acquire()
    url = f"{settings.iucn_base_url}/api/v4/taxa/scientific_name"
    headers = {
        "Accept": "application/json",
        "Authorization": settings.iucn_api_token,
        "User-Agent": settings.gbif_user_agent,
    }
    response = await client.get(
        url,
        params={"genus_name": genus, "species_name": species},
        headers=headers,
        timeout=40.0,
    )
    if response.status_code in {401, 403}:
        return IucnStatusResponse(
            available=False,
            taxonName=scientific_name,
            citation=citation,
            message="IUCN API rejected the token.",
        )
    if response.status_code == 404:
        return IucnStatusResponse(
            available=True,
            taxonName=f"{genus} {species}",
            citation=citation,
            message="No IUCN assessment found for this binomial.",
        )
    if response.status_code >= 400:
        return IucnStatusResponse(
            available=False,
            taxonName=scientific_name,
            citation=citation,
            message=f"IUCN API error {response.status_code}.",
        )

    data = response.json()
    assessments = data.get("assessments") or data.get("assessment") or []
    if isinstance(assessments, dict):
        assessments = [assessments]
    latest = assessments[0] if assessments else data
    category = None
    label = None
    assessment_id = None
    if isinstance(latest, dict):
        category = (
            latest.get("red_list_category_code")
            or (latest.get("red_list_category") or {}).get("code")
            or latest.get("category")
        )
        label = (
            (latest.get("red_list_category") or {}).get("title")
            or latest.get("red_list_category_title")
        )
        assessment_id = latest.get("assessment_id") or latest.get("assessmentId")

    result = IucnStatusResponse(
        available=True,
        taxonName=f"{genus} {species}",
        category=category,
        categoryLabel=label,
        assessmentId=assessment_id,
        citation=citation,
        url=f"https://www.iucnredlist.org/search?query={genus}%20{species}",
        raw={"keys": list(data.keys())} if isinstance(data, dict) else None,
    )
    await cache_set(cache_key, result.model_dump(), 86400)
    return result
