from __future__ import annotations

from typing import Any

import httpx

from app.compile import (
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


async def compile_map(client: httpx.AsyncClient, query: MapQuery) -> MapResponse:
    warnings: list[str] = []
    params = occurrence_params(query)
    if "taxonKey" not in params and "country" not in params:
        warnings.append("Add a taxon or country before mapping — unbounded queries are rejected.")
        return MapResponse(
            query=query,
            count=0,
            sample=empty_feature_collection(),
            attribution=[gbif_attribution()],
            warnings=warnings,
            mode=query.map.mode,
            style=query.map.style,
        )

    page_size = min(query.map.sampleLimit, 300)
    page = await gbif.occurrence_search(client, params, limit=page_size, offset=0)
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

    histogram = _histogram_from_records(records)
    if truncated:
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

    return MapResponse(
        query=query,
        count=count,
        countIsApproximate=False,
        tile=tile,
        sample={"type": "FeatureCollection", "features": sample_features},
        sampleTruncated=truncated,
        sampleOmittedSensitive=omitted_sensitive,
        histogram=histogram,
        attribution=attribution,
        warnings=warnings,
        mode=mode,
        style=query.map.style,
    )
