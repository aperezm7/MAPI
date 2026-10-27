from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.compile import (
    CURRENT_YEAR,
    choose_mode,
    empty_feature_collection,
    gbif_attribution,
    occurrence_params,
    record_to_feature,
    should_skip_record,
    tile_url_template,
    year_range,
)
from app.models import MapQuery, MapResponse, TileSpec, YearCount
from app.services import gbif
from app.services.shapes import shape_for_place


def histogram_from_facets(facets: list[dict[str, Any]] | None) -> list[YearCount]:
    """Full GBIF year counts, including years with no records between the first and last hit."""
    by_year: dict[int, int] = {}
    for facet in facets or []:
        if str(facet.get("field") or "").upper() != "YEAR":
            continue
        for row in facet.get("counts") or []:
            try:
                year = int(row.get("name"))
                count = int(row.get("count") or 0)
            except (TypeError, ValueError):
                continue
            if 1000 <= year <= CURRENT_YEAR and count > 0:
                by_year[year] = count
    if not by_year:
        return []
    first, last = min(by_year), max(by_year)
    if last - first > 400:
        return [YearCount(year=year, count=by_year[year]) for year in sorted(by_year)]
    return [YearCount(year=year, count=by_year.get(year, 0)) for year in range(first, last + 1)]


def _histogram_from_records(records: list[dict[str, Any]]) -> list[YearCount]:
    counts: dict[int, int] = {}
    for record in records:
        year = record.get("year")
        if year is None:
            continue
        try:
            year_i = int(year)
        except (TypeError, ValueError):
            continue
        counts[year_i] = counts.get(year_i, 0) + 1
    return [YearCount(year=year, count=counts[year]) for year in sorted(counts)]


async def _boundary_fields(
    client: httpx.AsyncClient, query: MapQuery, warnings: list[str]
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        boundary, attribution = await shape_for_place(client, query.place)
    except Exception:
        boundary, attribution = None, None
    if query.place and (query.place.iso2 or query.place.bbox) and not boundary:
        warnings.append("Place outline unavailable — map still uses the GBIF country or bbox filter.")
    return boundary, attribution


async def _year_histogram(client: httpx.AsyncClient, query: MapQuery) -> list[YearCount]:
    """Year counts for the query with the year window removed, so the slider keeps the full span."""
    untimed = query.model_copy(update={"time": None})
    params = occurrence_params(untimed)
    if "taxonKey" not in params and "country" not in params and "geometry" not in params:
        return []
    params["facet"] = "year"
    params["facetLimit"] = 1000
    try:
        page = await gbif.occurrence_search(client, params, limit=0)
    except Exception:
        return []
    return histogram_from_facets(page.get("facets") if isinstance(page, dict) else None)


async def compile_map(client: httpx.AsyncClient, query: MapQuery) -> MapResponse:
    warnings: list[str] = []
    params = occurrence_params(query)
    if "taxonKey" not in params and "country" not in params:
        warnings.append("Add a taxon or country before mapping — unbounded queries are rejected.")
        boundary, boundary_attr = await _boundary_fields(client, query, warnings)
        return MapResponse(
            query=query,
            count=0,
            sample=empty_feature_collection(),
            boundary=boundary,
            boundaryAttribution=boundary_attr,
            attribution=[gbif_attribution()],
            warnings=warnings,
            mode=query.map.mode,
            style=query.map.style,
        )

    page_size = min(query.map.sampleLimit, 300)
    page, facet_histogram = await asyncio.gather(
        gbif.occurrence_search(client, params, limit=page_size, offset=0),
        _year_histogram(client, query),
    )
    count = int(page.get("count") or 0)
    records = list(page.get("results") or [])
    truncated = count > len(records)

    mode = choose_mode(query, count)
    sample_features: list[dict[str, Any]] = []
    omitted_sensitive = 0

    if mode in {"tiles_plus_sample", "points"}:
        for record in records:
            skip, sensitive = should_skip_record(record)
            if skip:
                if sensitive:
                    omitted_sensitive += 1
                continue
            feature = record_to_feature(record)
            if feature:
                sample_features.append(feature)

    histogram = facet_histogram or _histogram_from_records(records)
    if not facet_histogram and truncated and histogram:
        warnings.append("Histogram reflects the inspectable sample, not the full GBIF count.")

    if omitted_sensitive:
        warnings.append(
            f"Omitted {omitted_sensitive} threatened records with rounded/fuzzy coordinates."
        )

    tile = None
    if mode in {"tiles_plus_sample", "tiles"}:
        template, source = tile_url_template(query, query.map.style)
        tile = TileSpec(urlTemplate=template, tileSize=512, source=source)

    if count == 0:
        warnings.append("No georeferenced GBIF occurrences for this query.")

    attribution = [gbif_attribution()]
    span = year_range(query)
    if span:
        attribution.append(f"Filtered to years {span[0]}–{span[1]}.")
    boundary, boundary_attr = await _boundary_fields(client, query, warnings)
    if boundary_attr:
        attribution.append(boundary_attr)

    return MapResponse(
        query=query,
        count=count,
        countIsApproximate=False,
        tile=tile,
        sample={"type": "FeatureCollection", "features": sample_features},
        sampleTruncated=truncated,
        sampleOmittedSensitive=omitted_sensitive,
        boundary=boundary,
        boundaryAttribution=boundary_attr,
        histogram=histogram,
        attribution=attribution,
        warnings=warnings,
        mode=mode,
        style=query.map.style,
    )
