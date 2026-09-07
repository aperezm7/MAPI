import pytest

from app.compile import (
    choose_mode,
    occurrence_params,
    record_to_feature,
    should_skip_record,
    tile_url_template,
    year_param,
)
from app.models import DownloadRequest, MapQuery
from app.services.downloads import mapquery_to_predicate


def _jaguar() -> MapQuery:
    return MapQuery.model_validate(
        {
            "taxon": {"q": "Panthera onca", "gbifKey": 5219426, "rank": "SPECIES"},
            "place": {"q": "Costa Rica", "iso2": "CR"},
            "time": {"yearMin": 2015},
        }
    )


def test_year_param_range():
    query = MapQuery.model_validate({"time": {"yearMin": 2015}})
    assert year_param(query) == "2015,2026"


def test_occurrence_params_jaguar():
    params = occurrence_params(_jaguar())
    assert params["taxonKey"] == 5219426
    assert params["country"] == "CR"
    assert params["eventDate"] == "2015-01-01,2026-12-31"
    assert "year" not in params
    assert params["hasCoordinate"] == "true"


def test_tile_template_density_for_species():
    template, source = tile_url_template(_jaguar(), "points")
    assert source == "density"
    assert "occurrence/density/{z}/{x}/{y}@1x.png" in template
    assert "taxonKey=5219426" in template
    assert "country=CR" in template
    assert "year=2015%2C2026" in template or "year=2015,2026" in template
    assert "srs=EPSG%3A3857" in template or "srs=EPSG:3857" in template


def test_tile_adhoc_when_iucn():
    query = MapQuery.model_validate(
        {
            "taxon": {"gbifKey": 131, "rank": "CLASS"},
            "place": {"iso2": "CR"},
            "conservation": {"iucn": ["CR", "EN"]},
            "map": {"style": "hex"},
        }
    )
    template, source = tile_url_template(query)
    assert source == "adhoc"
    assert "occurrence/adhoc/" in template
    assert "bin=hex" in template
    assert "iucnRedListCategory" in template


def test_heat_style():
    template, _source = tile_url_template(_jaguar(), "heat")
    assert "purpleHeat.point" in template


def test_skip_zero_coordinate():
    skip, sensitive = should_skip_record(
        {
            "decimalLatitude": 0,
            "decimalLongitude": 0,
            "issues": ["ZERO_COORDINATE"],
        }
    )
    assert skip is True
    assert sensitive is False


def test_omit_coarse_endangered():
    skip, sensitive = should_skip_record(
        {
            "decimalLatitude": 9.5,
            "decimalLongitude": -84.0,
            "issues": ["COORDINATE_ROUNDED"],
            "iucnRedListCategory": "CR",
            "coordinateUncertaintyInMeters": 100000,
        }
    )
    assert skip is True
    assert sensitive is True


def test_keep_rounded_threatened_points():
    skip, _sensitive = should_skip_record(
        {
            "decimalLatitude": 9.5,
            "decimalLongitude": -84.0,
            "issues": ["COORDINATE_ROUNDED"],
            "iucnRedListCategory": "CR",
            "coordinateUncertaintyInMeters": 100,
        }
    )
    assert skip is False


def test_record_to_feature():
    feature = record_to_feature(
        {
            "gbifID": 1,
            "decimalLatitude": 9.7,
            "decimalLongitude": -83.9,
            "scientificName": "Panthera onca",
            "issues": [],
        }
    )
    assert feature is not None
    assert feature["geometry"]["coordinates"] == [-83.9, 9.7]


def test_choose_mode_high_rank_uses_tiles():
    query = MapQuery.model_validate({"taxon": {"gbifKey": 131, "rank": "CLASS"}})
    assert choose_mode(query, 50000) == "tiles_plus_sample"


def test_choose_mode_small_species_points():
    query = MapQuery.model_validate({"taxon": {"gbifKey": 5219426, "rank": "SPECIES"}})
    assert choose_mode(query, 400) == "points"


def test_choose_mode_hex_keeps_tiles_for_small_counts():
    query = MapQuery.model_validate(
        {"taxon": {"gbifKey": 5219426, "rank": "SPECIES"}, "map": {"style": "hex"}}
    )
    assert choose_mode(query, 400) == "tiles_plus_sample"


def test_choose_mode_heat_keeps_tiles_for_small_counts():
    query = MapQuery.model_validate(
        {"taxon": {"gbifKey": 5219426, "rank": "SPECIES"}, "map": {"style": "heat"}}
    )
    assert choose_mode(query, 400) == "tiles_plus_sample"


def test_download_predicate():
    predicate = mapquery_to_predicate(DownloadRequest(query=_jaguar()))
    assert predicate["type"] == "and"
    keys = {p["key"] for p in predicate["predicates"] if "key" in p}
    assert "TAXON_KEY" in keys
    assert "COUNTRY" in keys
    assert "HAS_COORDINATE" in keys


@pytest.mark.asyncio
async def test_unscoped_map_rejected():
    import httpx
    from app.services.mapping import compile_map

    async with httpx.AsyncClient() as client:
        result = await compile_map(client, MapQuery())
    assert result.count == 0
    assert result.tile is None
    assert any("taxon" in w.lower() or "country" in w.lower() for w in result.warnings)
