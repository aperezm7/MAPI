from __future__ import annotations

from typing import Any

import httpx

from app.cache import cache_get, cache_set
from app.compile import year_range
from app.config import get_settings
from app.models import MapQuery
from app.rate_limit import inat_limiter


class InatError(RuntimeError):
    pass


async def inat_get(client: httpx.AsyncClient, path: str, params: dict[str, Any] | None = None) -> Any:
    settings = get_settings()
    url = f"{settings.inat_base_url}{path}"
    cache_key = f"inat:{path}:{repr(sorted((params or {}).items()))}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached
    await inat_limiter.acquire()
    headers = {"User-Agent": settings.gbif_user_agent, "Accept": "application/json"}
    response = await client.get(url, params=params, headers=headers, timeout=40.0)
    if response.status_code >= 400:
        raise InatError(f"iNaturalist {response.status_code}: {response.text[:240]}")
    data = response.json()
    await cache_set(cache_key, data, 90)
    return data


async def resolve_inat_place_id(client: httpx.AsyncClient, query: MapQuery) -> int | None:
    q = None
    if query.place:
        q = query.place.title or query.place.q
    if not q:
        return None
    data = await inat_get(client, "/v1/places/autocomplete", {"q": q})
    results = data.get("results") or []
    if not results:
        return None
    if query.place and query.place.iso2:
        iso = query.place.iso2.upper()
        for row in results:
            codes = row.get("admin_level")
            name = (row.get("display_name") or row.get("name") or "").upper()
            if iso in name or (query.place.title or "").upper() in name:
                return int(row["id"])
            if codes == 0:
                return int(row["id"])
    return int(results[0]["id"])


def _photo_url(obs: dict[str, Any]) -> str | None:
    photos = obs.get("photos") or []
    if not photos:
        return None
    return photos[0].get("url") or photos[0].get("medium_url") or photos[0].get("square_url")


def observation_to_feature(obs: dict[str, Any]) -> dict[str, Any] | None:
    geojson = obs.get("geojson")
    coords = None
    if geojson and geojson.get("coordinates"):
        coords = geojson["coordinates"]
    elif obs.get("location"):
        try:
            lat_s, lon_s = str(obs["location"]).split(",")
            coords = [float(lon_s), float(lat_s)]
        except (TypeError, ValueError):
            return None
    if not coords:
        return None
    taxon = obs.get("taxon") or {}
    photo = _photo_url(obs)
    license_code = (obs.get("license_code") or photos_license(obs) or "").upper()
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": coords},
        "properties": {
            "source": "inaturalist",
            "id": obs.get("id"),
            "scientificName": taxon.get("name") or obs.get("species_guess"),
            "commonName": (taxon.get("preferred_common_name")),
            "observedOn": obs.get("observed_on"),
            "qualityGrade": obs.get("quality_grade"),
            "photoUrl": photo,
            "license": license_code,
            "uri": obs.get("uri"),
        },
    }


def photos_license(obs: dict[str, Any]) -> str | None:
    photos = obs.get("photos") or []
    if photos:
        return photos[0].get("license_code")
    return None


async def inat_overlay(client: httpx.AsyncClient, query: MapQuery) -> dict[str, Any]:
    params: dict[str, Any] = {
        "quality_grade": "research",
        "geo": "true",
        "photos": "true",
        "per_page": 200,
        "order_by": "observed_on",
        "order": "desc",
    }
    if query.taxon:
        params["taxon_name"] = query.taxon.canonicalName or query.taxon.scientificName or query.taxon.q
    place_id = await resolve_inat_place_id(client, query)
    if place_id:
        params["place_id"] = place_id
    span = year_range(query)
    if span:
        params["d1"] = f"{span[0]}-01-01"
        params["d2"] = f"{span[1]}-12-31"

    data = await inat_get(client, "/v1/observations", params)
    features = []
    for obs in data.get("results") or []:
        feature = observation_to_feature(obs)
        if feature:
            features.append(feature)
    return {
        "type": "FeatureCollection",
        "features": features,
        "attribution": [
            "iNaturalist research-grade observations. Respect individual photo licenses."
        ],
        "count": int(data.get("total_results") or len(features)),
        "sampleTruncated": int(data.get("total_results") or 0) > len(features),
    }
