"""Country and bbox polygons for map overlay and GIS export.

QGIS Desktop has a Python API (PyQGIS) and an optional self-hosted QGIS Server
(WMS/WFS). There is no public QGIS cloud REST API comparable to GBIF, so MAPI
pulls official ADM0 outlines from geoBoundaries and packages them as GeoJSON
that QGIS can open natively.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.cache import cache_get, cache_set
from app.models import PlaceQuery
from app.rate_limit import geoboundaries_limiter
from app.services.resolve import load_countries

GEOB_META = "https://www.geoboundaries.org/api/current/gbOpen/{iso3}/ADM0/"
BOUNDARY_TTL = 60 * 60 * 24 * 7
GEOB_ATTRIBUTION = "Administrative boundaries from geoBoundaries (www.geoboundaries.org)."


def empty_feature_collection() -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": []}


def bbox_feature_collection(bbox: list[float], title: str | None = None) -> dict[str, Any]:
    min_lon, min_lat, max_lon, max_lat = bbox
    ring = [
        [min_lon, min_lat],
        [max_lon, min_lat],
        [max_lon, max_lat],
        [min_lon, max_lat],
        [min_lon, min_lat],
    ]
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "title": title or "Bounding box",
                    "kind": "bbox",
                },
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        ],
    }


def as_feature_collection(payload: Any, properties: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    extra = properties or {}
    kind = payload.get("type")
    if kind == "FeatureCollection":
        features = []
        for feature in payload.get("features") or []:
            if not isinstance(feature, dict):
                continue
            props = {**(feature.get("properties") or {}), **extra}
            features.append({**feature, "properties": props})
        return {"type": "FeatureCollection", "features": features}
    if kind == "Feature":
        props = {**(payload.get("properties") or {}), **extra}
        return {"type": "FeatureCollection", "features": [{**payload, "properties": props}]}
    if kind in {"Polygon", "MultiPolygon", "GeometryCollection"}:
        return {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": extra, "geometry": payload}],
        }
    return None


def _meta_record(data: Any) -> dict[str, Any] | None:
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    if isinstance(data, dict) and (data.get("simplifiedGeometryGeoJSON") or data.get("gjDownloadURL")):
        return data
    return None


async def iso3_for_place(client: httpx.AsyncClient, place: PlaceQuery) -> str | None:
    if not place.iso2:
        return None
    countries = await load_countries(client)
    for country in countries:
        if country.iso2 == place.iso2.upper() and country.iso3:
            return country.iso3.upper()
    return None


async def country_boundary(client: httpx.AsyncClient, iso3: str) -> tuple[dict[str, Any] | None, str | None]:
    iso3 = iso3.upper()
    cache_key = f"geob:adm0:{iso3}"
    cached = await cache_get(cache_key)
    if isinstance(cached, dict) and cached.get("collection"):
        return cached["collection"], cached.get("attribution") or GEOB_ATTRIBUTION

    await geoboundaries_limiter.acquire()
    meta_response = await client.get(GEOB_META.format(iso3=iso3), timeout=20.0)
    if meta_response.status_code >= 400:
        return None, None
    meta = _meta_record(meta_response.json())
    if not meta:
        return None, None
    geo_url = meta.get("simplifiedGeometryGeoJSON") or meta.get("gjDownloadURL")
    if not geo_url:
        return None, None

    await geoboundaries_limiter.acquire()
    geo_response = await client.get(str(geo_url), timeout=30.0)
    if geo_response.status_code >= 400:
        return None, None
    license_name = meta.get("boundaryLicense") or meta.get("licenseDetail")
    attribution = GEOB_ATTRIBUTION
    if license_name:
        attribution = f"{GEOB_ATTRIBUTION} {iso3}: {license_name}."
    collection = as_feature_collection(
        geo_response.json(),
        {
            "title": meta.get("boundaryName") or iso3,
            "iso3": iso3,
            "kind": "adm0",
            "source": "geoBoundaries",
            "license": license_name,
        },
    )
    if not collection or not collection.get("features"):
        return None, None
    await cache_set(cache_key, {"collection": collection, "attribution": attribution}, BOUNDARY_TTL)
    return collection, attribution


async def shape_for_place(
    client: httpx.AsyncClient, place: PlaceQuery | None
) -> tuple[dict[str, Any] | None, str | None]:
    if not place:
        return None, None
    if place.kind == "bbox" and place.bbox and len(place.bbox) == 4:
        return bbox_feature_collection(place.bbox, place.title or place.q), "Query bounding box."
    if place.iso2:
        try:
            iso3 = await iso3_for_place(client, place)
            if iso3:
                return await country_boundary(client, iso3)
        except Exception:
            return None, None
    if place.bbox and len(place.bbox) == 4:
        return bbox_feature_collection(place.bbox, place.title or place.q), "Query bounding box."
    return None, None
