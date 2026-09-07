from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import MapQuery


def test_northstar_query_parses():
    query = MapQuery.model_validate(
        {
            "taxon": {"q": "amphibians", "rankHint": "class"},
            "place": {"q": "Costa Rica", "kind": "country"},
            "time": {"yearMin": 2015},
            "conservation": {"iucn": ["CR", "EN"]},
            "filters": {"hasCoordinate": True, "occurrenceStatus": "PRESENT"},
            "map": {"mode": "tiles_plus_sample", "sampleLimit": 900, "style": "hex"},
        }
    )
    assert query.taxon and query.taxon.q == "amphibians"
    assert query.place and query.place.kind == "country"
    assert query.time and query.time.yearMin == 2015
    assert query.conservation and query.conservation.iucn == ["CR", "EN"]


def test_iso2_normalized():
    query = MapQuery.model_validate({"place": {"iso2": "cr"}})
    assert query.place and query.place.iso2 == "CR"


def test_rejects_bad_iucn():
    with pytest.raises(ValidationError):
        MapQuery.model_validate({"conservation": {"iucn": ["EXTINCTISH"]}})


def test_sample_limit_bounds():
    with pytest.raises(ValidationError):
        MapQuery.model_validate({"map": {"sampleLimit": 0}})
