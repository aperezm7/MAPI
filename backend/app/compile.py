from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from app.models import MapQuery

CURRENT_YEAR = 2026

SKIP_ISSUES = {
    "ZERO_COORDINATE",
    "GEODETIC_DATUM_INVALID",
    "COORDINATE_INVALID",
    "COUNTRY_COORDINATE_MISMATCH",
}


def year_range(query: MapQuery) -> tuple[int, int] | None:
    if not query.time:
        return None
    lo = query.time.yearMin
    hi = query.time.yearMax
    if lo is None and hi is None:
        return None
    if lo is None:
        lo = 1000
    if hi is None:
        hi = CURRENT_YEAR
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


def year_param(query: MapQuery) -> str | None:
    span = year_range(query)
    if not span:
        return None
    lo, hi = span
    if lo == hi:
        return str(lo)
    return f"{lo},{hi}"


def event_date_param(query: MapQuery) -> str | None:
    span = year_range(query)
    if not span:
        return None
    lo, hi = span
    return f"{lo}-01-01,{hi}-12-31"


def iucn_codes(query: MapQuery) -> list[str]:
    if not query.conservation:
        return []
    return [code.upper() for code in query.conservation.iucn]


def _core_filters(query: MapQuery) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if query.taxon and query.taxon.gbifKey:
        params["taxonKey"] = query.taxon.gbifKey
    if query.place and query.place.iso2:
        params["country"] = query.place.iso2
    codes = iucn_codes(query)
    if codes:
        params["iucnRedListCategory"] = codes if len(codes) > 1 else codes[0]
    if query.filters.basisOfRecord:
        params["basisOfRecord"] = query.filters.basisOfRecord
    return params


def occurrence_params(query: MapQuery) -> dict[str, Any]:
    """Occurrence search params. Use eventDate — GBIF `year=` on search can hang."""
    params = _core_filters(query)
    if query.place and query.place.bbox and len(query.place.bbox) == 4:
        min_lon, min_lat, max_lon, max_lat = query.place.bbox
        params["geometry"] = (
            f"POLYGON(({min_lon} {min_lat},{max_lon} {min_lat},"
            f"{max_lon} {max_lat},{min_lon} {max_lat},{min_lon} {min_lat}))"
        )
    event_date = event_date_param(query)
    if event_date:
        params["eventDate"] = event_date
    if query.filters.hasCoordinate:
        params["hasCoordinate"] = "true"
    if query.filters.occurrenceStatus:
        params["occurrenceStatus"] = query.filters.occurrenceStatus
    return params


def use_adhoc_tiles(query: MapQuery) -> bool:
    return bool(iucn_codes(query) or (query.place and query.place.bbox))


def choose_mode(query: MapQuery, count: int) -> str:
    if query.map.mode != "tiles_plus_sample":
        return query.map.mode
    # Hex/heat only exist as GBIF raster styles. Keep tiles so the UI style chips
    # are not silently ignored when the sample is small enough for "points".
    if query.map.style in {"hex", "heat"}:
        return "tiles_plus_sample"
    rank = (query.taxon.rank or "").upper() if query.taxon else ""
    high_rank = rank in {"KINGDOM", "PHYLUM", "CLASS", "ORDER", "FAMILY"}
    if high_rank or count > 8000:
        return "tiles_plus_sample"
    if count <= 2500 and not high_rank:
        return "points"
    return "tiles_plus_sample"


def tile_style_params(style: str, adhoc: bool) -> dict[str, str]:
    if style == "hex":
        return {"bin": "hex", "hexPerTile": "79", "style": "classic.poly"}
    if style == "heat":
        return {"style": "purpleHeat.point"}
    if adhoc:
        return {"bin": "hex", "hexPerTile": "79", "style": "classic.poly"}
    return {"style": "classic.point"}


def tile_url_template(query: MapQuery, style: str | None = None) -> tuple[str, str]:
    adhoc = use_adhoc_tiles(query)
    source = "adhoc" if adhoc else "density"
    params = _core_filters(query)
    year = year_param(query)
    if year:
        params["year"] = year
    style_name = style or query.map.style
    params.update(tile_style_params(style_name, adhoc))
    params["srs"] = "EPSG:3857"
    querystring = urlencode(params, doseq=True)
    template = (
        f"https://api.gbif.org/v2/map/occurrence/{source}/{{z}}/{{x}}/{{y}}@1x.png"
        f"?{querystring}"
    )
    return template, source


def should_skip_record(record: dict[str, Any]) -> tuple[bool, bool]:
    lat = record.get("decimalLatitude")
    lon = record.get("decimalLongitude")
    if lat is None or lon is None:
        return True, False
    issues = set(record.get("issues") or [])
    if issues & SKIP_ISSUES:
        return True, False
    iucn = (record.get("iucnRedListCategory") or "").upper()
    uncertainty = record.get("coordinateUncertaintyInMeters")
    try:
        uncertainty_m = float(uncertainty) if uncertainty is not None else None
    except (TypeError, ValueError):
        uncertainty_m = None
    if iucn in {"CR", "EN", "EW"} and uncertainty_m is not None and uncertainty_m >= 50000:
        return True, True
    return False, False


def record_to_feature(record: dict[str, Any]) -> dict[str, Any] | None:
    skip, _sensitive = should_skip_record(record)
    if skip:
        return None
    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [record["decimalLongitude"], record["decimalLatitude"]],
        },
        "properties": {
            "gbifID": record.get("gbifID") or record.get("key"),
            "scientificName": record.get("scientificName"),
            "decimalLatitude": record.get("decimalLatitude"),
            "decimalLongitude": record.get("decimalLongitude"),
            "eventDate": record.get("eventDate"),
            "year": record.get("year"),
            "country": record.get("country"),
            "countryCode": record.get("countryCode"),
            "basisOfRecord": record.get("basisOfRecord"),
            "iucnRedListCategory": record.get("iucnRedListCategory"),
            "occurrenceID": record.get("occurrenceID"),
            "datasetKey": record.get("datasetKey"),
            "license": record.get("license"),
            "issues": record.get("issues") or [],
        },
    }


def empty_feature_collection() -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": []}


def gbif_attribution() -> str:
    return "Occurrence data © GBIF contributors. https://www.gbif.org"
