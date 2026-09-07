from __future__ import annotations

from typing import Any

import httpx

from app.cache import cache_get, cache_set
from app.config import get_settings
from app.rate_limit import gbif_limiter

OCCURRENCE_PAGE = 300


class GbifError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    return {
        "User-Agent": get_settings().gbif_user_agent,
        "Accept": "application/json",
    }


async def gbif_get(client: httpx.AsyncClient, path: str, params: dict[str, Any] | None = None) -> Any:
    settings = get_settings()
    url = f"{settings.gbif_base_url}{path}"
    cache_key = f"gbif:{path}:{repr(sorted((params or {}).items()))}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached
    await gbif_limiter.acquire()
    response = await client.get(url, params=params, headers=_headers(), timeout=20.0)
    if response.status_code == 429:
        raise GbifError("GBIF rate limited this request. Retry shortly.")
    if response.status_code >= 400:
        raise GbifError(f"GBIF {response.status_code}: {response.text[:300]}")
    data = response.json()
    ttl = 3600 if "species" in path or "enumeration" in path else 90
    if "occurrence/search" in path:
        ttl = 60
    if "occurrence/count" in path:
        ttl = 300
    await cache_set(cache_key, data, ttl)
    return data


async def match_species(client: httpx.AsyncClient, name: str) -> dict[str, Any]:
    return await gbif_get(client, "/v1/species/match", {"name": name, "verbose": "true"})


async def search_species(
    client: httpx.AsyncClient,
    q: str,
    rank: str | None = None,
    vernacular: bool = False,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"q": q, "limit": 20, "status": "ACCEPTED"}
    if rank:
        params["rank"] = rank.upper()
    if vernacular:
        params["qField"] = "VERNACULAR"
    data = await gbif_get(client, "/v1/species/search", params)
    return list(data.get("results") or []) if isinstance(data, dict) else []


async def suggest_species(client: httpx.AsyncClient, q: str, limit: int = 12) -> list[dict[str, Any]]:
    data = await gbif_get(client, "/v1/species/suggest", {"q": q, "limit": limit})
    return data if isinstance(data, list) else []


async def get_species(client: httpx.AsyncClient, key: int) -> dict[str, Any]:
    return await gbif_get(client, f"/v1/species/{key}")


async def list_countries(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    return await gbif_get(client, "/v1/enumeration/country")


async def occurrence_search(
    client: httpx.AsyncClient,
    params: dict[str, Any],
    limit: int = 0,
    offset: int = 0,
) -> dict[str, Any]:
    merged = {**params, "limit": limit, "offset": offset}
    return await gbif_get(client, "/v1/occurrence/search", merged)


async def occurrence_pages(
    client: httpx.AsyncClient,
    params: dict[str, Any],
    sample_limit: int,
) -> list[dict[str, Any]]:
    remaining = sample_limit
    offset = 0
    records: list[dict[str, Any]] = []
    while remaining > 0:
        page_size = min(OCCURRENCE_PAGE, remaining)
        data = await occurrence_search(client, params, limit=page_size, offset=offset)
        results = data.get("results") or []
        records.extend(results)
        if len(results) < page_size:
            break
        remaining -= len(results)
        offset += len(results)
        if offset >= int(data.get("count") or 0):
            break
    return records
