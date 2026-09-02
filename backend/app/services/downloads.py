from __future__ import annotations

from typing import Any

import httpx

from app.compile import iucn_codes, occurrence_params, year_range
from app.config import get_settings
from app.models import DownloadRequest, DownloadResponse
from app.rate_limit import gbif_limiter


def _equals(key: str, value: str) -> dict[str, str]:
    return {"type": "equals", "key": key, "value": str(value)}


def mapquery_to_predicate(request: DownloadRequest) -> dict[str, Any]:
    predicates: list[dict[str, Any]] = []
    params = occurrence_params(request.query)
    if "taxonKey" in params:
        predicates.append(_equals("TAXON_KEY", str(params["taxonKey"])))
    if "country" in params:
        predicates.append(_equals("COUNTRY", str(params["country"])))
    span = year_range(request.query)
    if span:
        predicates.append({"type": "greaterThanOrEquals", "key": "YEAR", "value": str(span[0])})
        predicates.append({"type": "lessThanOrEquals", "key": "YEAR", "value": str(span[1])})
    codes = iucn_codes(request.query)
    if len(codes) == 1:
        predicates.append(_equals("IUCN_RED_LIST_CATEGORY", codes[0]))
    elif len(codes) > 1:
        predicates.append(
            {
                "type": "or",
                "predicates": [_equals("IUCN_RED_LIST_CATEGORY", code) for code in codes],
            }
        )
    predicates.append(_equals("HAS_COORDINATE", "true"))
    if len(predicates) == 1:
        return predicates[0]
    return {"type": "and", "predicates": predicates}


async def create_download(client: httpx.AsyncClient, request: DownloadRequest) -> DownloadResponse:
    settings = get_settings()
    if not settings.gbif_username or not settings.gbif_password:
        return DownloadResponse(
            available=False,
            message="Set GBIF_USERNAME and GBIF_PASSWORD to request a full GBIF occurrence download.",
        )
    if not request.query.taxon or not request.query.taxon.gbifKey:
        return DownloadResponse(available=False, message="Resolve a taxon before requesting a download.")

    payload: dict[str, Any] = {
        "creator": settings.gbif_username,
        "sendNotification": bool(settings.gbif_download_email),
        "format": request.format,
        "predicate": mapquery_to_predicate(request),
    }
    if settings.gbif_download_email:
        payload["notificationAddresses"] = [settings.gbif_download_email]

    await gbif_limiter.acquire()
    response = await client.post(
        f"{settings.gbif_base_url}/v1/occurrence/download/request",
        json=payload,
        headers={"User-Agent": settings.gbif_user_agent},
        auth=(settings.gbif_username, settings.gbif_password),
        timeout=60.0,
    )
    if response.status_code >= 400:
        return DownloadResponse(
            available=False,
            message=f"GBIF download request failed ({response.status_code}): {response.text[:240]}",
        )
    key = response.text.strip().strip('"')
    return DownloadResponse(
        available=True,
        key=key,
        statusUrl=f"{settings.gbif_base_url}/v1/occurrence/download/{key}",
        message="Download queued at GBIF. Poll statusUrl; do not treat this as the map sample.",
    )
