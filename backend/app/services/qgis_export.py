"""Build a QGIS Desktop package (GeoJSON + PyQGIS loader).

QGIS is a desktop/GIS server product, not a hosted occurrence API. This zip is
meant to be opened in QGIS: drag the GeoJSON files onto the canvas, or run
load_in_qgis.py from the Python console.
"""

from __future__ import annotations

import io
import json
import re
import zipfile

from app.models import MapQuery, MapResponse

README = """MAPI QGIS package
=================

QGIS does not offer a public cloud REST API for drawing these maps. This folder
is a QGIS Desktop project you can open locally.

Quickest path
-------------
1. Open QGIS.
2. Drag occurrences.geojson and boundary.geojson onto the map.
3. Optional: Browser → XYZ Tiles → New Connection
   - OpenStreetMap: https://tile.openstreetmap.org/{z}/{x}/{y}.png
   - GBIF tiles: see gbif_tiles.txt (paste as an XYZ connection)

PyQGIS (adds OSM + GBIF tiles + vectors in one step)
----------------------------------------------------
Plugins → Python Console → Show editor → Open load_in_qgis.py → Run.

Files
-----
- occurrences.geojson  capped GBIF inspectable sample (not the full download)
- boundary.geojson     country ADM0 from geoBoundaries, or the query bbox
- mapquery.json        the MapQuery that produced this map
- gbif_tiles.txt       XYZ URL for the same GBIF density/adhoc layer
- load_in_qgis.py      PyQGIS loader
- mapi.qgs             QGIS 3 project pointing at the GeoJSON files

For the complete occurrence table, use MAPI's GBIF download request instead of
this sample.
"""

LOAD_SCRIPT = '''\
"""Load this MAPI export into the current QGIS project.

QGIS → Plugins → Python Console → Show editor → Open this file → Run.
"""
from __future__ import annotations

import urllib.parse
from pathlib import Path

from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer
from qgis.utils import iface

ROOT = Path(__file__).resolve().parent
PROJECT = QgsProject.instance()

GBIF_TILES = {gbif_tiles_repr}
OSM_URL = "https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png"


def add_xyz(url: str, name: str) -> None:
    uri = "type=xyz&url={{}}&zmax=19&zmin=0".format(urllib.parse.quote(url, safe=""))
    layer = QgsRasterLayer(uri, name, "wms")
    if layer.isValid():
        PROJECT.addMapLayer(layer)


def add_geojson(path: Path, name: str) -> None:
    if not path.exists():
        return
    layer = QgsVectorLayer(str(path), name, "ogr")
    if layer.isValid():
        PROJECT.addMapLayer(layer)
        return layer
    return None


add_xyz(OSM_URL, "OpenStreetMap")
if GBIF_TILES:
    add_xyz(GBIF_TILES, "GBIF occurrence tiles")
boundary = add_geojson(ROOT / "boundary.geojson", "boundary")
occurrences = add_geojson(ROOT / "occurrences.geojson", "occurrences")
target = occurrences or boundary
if target is not None and iface is not None:
    iface.setActiveLayer(target)
    iface.zoomToActiveLayer()
'''

QGS_TEMPLATE = """\
<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.34.0" projectname="MAPI">
  <title>MAPI export</title>
  <projectCrs>
    <spatialrefsys>
      <authid>EPSG:4326</authid>
      <srid>4326</srid>
      <geographicflag>true</geographicflag>
    </spatialrefsys>
  </projectCrs>
  <layer-tree-group name="" checked="Qt::Checked" expanded="1">
    {layer_tree}
  </layer-tree-group>
  <projectlayers>
    {project_layers}
  </projectlayers>
  <properties>
    <SpatialRefSys>
      <ProjectCrs type="QString">EPSG:4326</ProjectCrs>
    </SpatialRefSys>
  </properties>
</qgis>
"""

VECTOR_LAYER = """\
    <maplayer type="vector" geometry="{geometry}" hasScaleBasedVisibilityFlag="0">
      <id>{layer_id}</id>
      <datasource>./{filename}</datasource>
      <layername>{name}</layername>
      <provider>ogr</provider>
      <srs>
        <spatialrefsys>
          <authid>EPSG:4326</authid>
          <srid>4326</srid>
        </spatialrefsys>
      </srs>
    </maplayer>
"""

LAYER_TREE = (
    '    <layer-tree-layer id="{layer_id}" name="{name}" source="./{filename}" '
    'providerKey="ogr" checked="Qt::Checked" expanded="0"/>'
)


def package_slug(query: MapQuery) -> str:
    taxon = "map"
    if query.taxon:
        taxon = query.taxon.canonicalName or query.taxon.scientificName or query.taxon.q or "map"
    place = "world"
    if query.place:
        place = query.place.iso2 or query.place.title or query.place.q or "world"
    raw = f"{taxon}-{place}"
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", raw).strip("-").lower()
    return (slug or "mapi")[:72]


def _qgs_document(has_boundary: bool) -> str:
    layers: list[tuple[str, str, str, str]] = []
    if has_boundary:
        layers.append(("boundary_1", "boundary", "boundary.geojson", "Polygon"))
    layers.append(("occ_1", "occurrences", "occurrences.geojson", "Point"))
    tree = "\n".join(
        LAYER_TREE.format(layer_id=layer_id, name=name, filename=filename)
        for layer_id, name, filename, _geom in layers
    )
    bodies = "\n".join(
        VECTOR_LAYER.format(layer_id=layer_id, name=name, filename=filename, geometry=geometry)
        for layer_id, name, filename, geometry in layers
    )
    return QGS_TEMPLATE.format(layer_tree=tree, project_layers=bodies)


def build_qgis_zip(mapped: MapResponse) -> bytes:
    query = mapped.query
    sample = mapped.sample if isinstance(mapped.sample, dict) else {"type": "FeatureCollection", "features": []}
    boundary = mapped.boundary if isinstance(mapped.boundary, dict) else None
    tile_url = mapped.tile.urlTemplate if mapped.tile else ""
    script = LOAD_SCRIPT.format(gbif_tiles_repr=repr(tile_url or None))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", README)
        archive.writestr("mapquery.json", json.dumps(query.model_dump(), indent=2))
        archive.writestr("occurrences.geojson", json.dumps(sample, indent=2))
        if boundary and boundary.get("features"):
            archive.writestr("boundary.geojson", json.dumps(boundary, indent=2))
        if tile_url:
            archive.writestr("gbif_tiles.txt", tile_url + "\n")
        archive.writestr("load_in_qgis.py", script)
        archive.writestr("mapi.qgs", _qgs_document(bool(boundary and boundary.get("features"))))
        if mapped.boundaryAttribution:
            archive.writestr("ATTRIBUTION.txt", "\n".join([*mapped.attribution, mapped.boundaryAttribution]) + "\n")
        elif mapped.attribution:
            archive.writestr("ATTRIBUTION.txt", "\n".join(mapped.attribution) + "\n")
    return buffer.getvalue()
