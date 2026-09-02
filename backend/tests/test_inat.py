from app.services.inat import observation_to_feature


def test_observation_to_feature_from_geojson():
    feature = observation_to_feature(
        {
            "id": 99,
            "geojson": {"type": "Point", "coordinates": [-84.0, 9.9]},
            "taxon": {"name": "Panthera onca", "preferred_common_name": "Jaguar"},
            "observed_on": "2020-01-01",
            "quality_grade": "research",
            "photos": [{"url": "https://example.com/p.jpg", "license_code": "cc-by"}],
            "uri": "https://www.inaturalist.org/observations/99",
            "license_code": "cc-by",
        }
    )
    assert feature is not None
    assert feature["properties"]["source"] == "inaturalist"
    assert feature["properties"]["photoUrl"] == "https://example.com/p.jpg"
    assert feature["geometry"]["coordinates"] == [-84.0, 9.9]


def test_observation_skips_unlocated():
    assert observation_to_feature({"id": 1, "taxon": {"name": "x"}}) is None
