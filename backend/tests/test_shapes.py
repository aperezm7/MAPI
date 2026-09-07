from app.models import MapQuery, MapResponse
from app.services.qgis_export import build_qgis_zip, package_slug
from app.services.shapes import as_feature_collection, bbox_feature_collection


TINY_CR = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"shapeName": "Costa Rica"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[-85.9, 8.0], [-82.5, 8.0], [-82.5, 11.2], [-85.9, 11.2], [-85.9, 8.0]]
                ],
            },
        }
    ],
}


def test_bbox_polygon_closes():
    collection = bbox_feature_collection([-86, 8, -82, 11], "box")
    ring = collection["features"][0]["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1]
    assert collection["features"][0]["properties"]["kind"] == "bbox"


def test_as_feature_collection_wraps_polygon():
    wrapped = as_feature_collection(
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
        {"iso3": "CRI"},
    )
    assert wrapped is not None
    assert wrapped["features"][0]["properties"]["iso3"] == "CRI"


def test_qgis_zip_contains_loader_and_layers():
    mapped = MapResponse(
        query=MapQuery.model_validate(
            {"taxon": {"q": "Panthera onca", "canonicalName": "Panthera onca"}, "place": {"iso2": "CR"}}
        ),
        count=1,
        sample={
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-84, 10]},
                    "properties": {"gbifID": 1},
                }
            ],
        },
        boundary=TINY_CR,
        boundaryAttribution="Administrative boundaries from geoBoundaries.",
        attribution=["Occurrence data © GBIF contributors."],
        tile={
            "urlTemplate": "https://api.gbif.org/v2/map/occurrence/density/{z}/{x}/{y}@1x.png?taxonKey=1",
            "tileSize": 512,
            "source": "density",
            "attribution": "© GBIF",
        },
    )
    payload = build_qgis_zip(mapped)
    assert payload[:2] == b"PK"
    from zipfile import ZipFile
    from io import BytesIO

    names = ZipFile(BytesIO(payload)).namelist()
    assert "occurrences.geojson" in names
    assert "boundary.geojson" in names
    assert "load_in_qgis.py" in names
    assert "mapi.qgs" in names
    assert "gbif_tiles.txt" in names
    script = ZipFile(BytesIO(payload)).read("load_in_qgis.py").decode()
    assert "GBIF_TILES" in script
    assert "OpenStreetMap" in script


def test_package_slug():
    query = MapQuery.model_validate(
        {"taxon": {"canonicalName": "Panthera onca"}, "place": {"iso2": "CR", "title": "Costa Rica"}}
    )
    assert package_slug(query) == "panthera-onca-cr"
