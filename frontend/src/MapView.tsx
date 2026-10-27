import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { InatOverlay, MapResponse } from "./types";

const BASE_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

type Props = {
  mapData: MapResponse | null;
  inat: InatOverlay | null;
  onSelect: (feature: GeoJSON.Feature | null) => void;
};

export type MapViewHandle = {
  exportPng: () => string | null;
};

function collectPositions(geom: GeoJSON.Geometry | null | undefined): number[][] {
  if (!geom) return [];
  switch (geom.type) {
    case "Point":
      return [geom.coordinates];
    case "MultiPoint":
    case "LineString":
      return geom.coordinates;
    case "MultiLineString":
    case "Polygon":
      return geom.coordinates.flat();
    case "MultiPolygon":
      return geom.coordinates.flat(2);
    case "GeometryCollection":
      return geom.geometries.flatMap(collectPositions);
    default:
      return [];
  }
}

function fitCollection(map: maplibregl.Map, collection: GeoJSON.FeatureCollection, maxZoom: number) {
  const coords = collection.features.flatMap((feature) => collectPositions(feature.geometry));
  const usable = coords.filter((c) => Array.isArray(c) && c.length >= 2);
  if (usable.length === 0) return;
  const bounds = usable.reduce(
    (b, c) => b.extend(c as [number, number]),
    new maplibregl.LngLatBounds(usable[0] as [number, number], usable[0] as [number, number]),
  );
  map.fitBounds(bounds, { padding: 60, maxZoom, duration: 700 });
}

function syncSampleVisibility(map: maplibregl.Map, style: string | undefined) {
  const hidePoints = style === "heat" && map.getZoom() < 7;
  const visibility = hidePoints ? "none" : "visible";
  for (const layerId of ["gbif-points", "gbif-clusters", "gbif-cluster-count"]) {
    if (map.getLayer(layerId)) {
      map.setLayoutProperty(layerId, "visibility", visibility);
    }
  }
}

const MapView = forwardRef<MapViewHandle, Props>(function MapView({ mapData, inat, onSelect }, ref) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useImperativeHandle(ref, () => ({
    exportPng: () => {
      const map = mapRef.current;
      if (!map) return null;
      map.triggerRepaint();
      return map.getCanvas().toDataURL("image/png");
    },
  }));

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASE_STYLE,
      center: [-84.07, 9.93],
      zoom: 6,
      attributionControl: { compact: true },
      canvasContextAttributes: { preserveDrawingBuffer: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    mapRef.current = map;
    map.on("load", () => {
      map.addSource("boundary", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "boundary-fill",
        type: "fill",
        source: "boundary",
        paint: {
          "fill-color": "#1f5f5b",
          "fill-opacity": 0.1,
        },
      });
      map.addLayer({
        id: "boundary-line",
        type: "line",
        source: "boundary",
        paint: {
          "line-color": "#1f5f5b",
          "line-width": 1.8,
          "line-opacity": 0.9,
        },
      });
      map.addSource("gbif-sample", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
        cluster: true,
        clusterRadius: 42,
        clusterMaxZoom: 12,
      });
      map.addLayer({
        id: "gbif-clusters",
        type: "circle",
        source: "gbif-sample",
        filter: ["has", "point_count"],
        paint: {
          "circle-color": "#1f5f5b",
          "circle-radius": ["step", ["get", "point_count"], 14, 20, 18, 100, 24],
          "circle-opacity": 0.86,
        },
      });
      map.addLayer({
        id: "gbif-cluster-count",
        type: "symbol",
        source: "gbif-sample",
        filter: ["has", "point_count"],
        layout: { "text-field": "{point_count_abbreviated}", "text-size": 12 },
        paint: { "text-color": "#f7f4ee" },
      });
      map.addLayer({
        id: "gbif-points",
        type: "circle",
        source: "gbif-sample",
        filter: ["!", ["has", "point_count"]],
        paint: {
          "circle-color": "#b4532a",
          "circle-radius": 5,
          "circle-stroke-width": 1,
          "circle-stroke-color": "#f7f4ee",
        },
      });
      map.addSource("inat", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "inat-points",
        type: "circle",
        source: "inat",
        paint: {
          "circle-color": "#2b6cb0",
          "circle-radius": 5,
          "circle-stroke-width": 1,
          "circle-stroke-color": "#fff",
        },
      });

      map.on("click", "gbif-clusters", (event) => {
        const feature = map.queryRenderedFeatures(event.point, { layers: ["gbif-clusters"] })[0];
        const clusterId = feature?.properties?.cluster_id;
        const source = map.getSource("gbif-sample") as maplibregl.GeoJSONSource;
        if (clusterId == null) return;
        source.getClusterExpansionZoom(clusterId).then((zoom) => {
          const coords = (feature.geometry as GeoJSON.Point).coordinates as [number, number];
          map.easeTo({ center: coords, zoom });
        });
      });
      map.on("click", "gbif-points", (event) => {
        const feature = event.features?.[0];
        onSelectRef.current(feature ?? null);
      });
      map.on("click", "inat-points", (event) => {
        const feature = event.features?.[0];
        onSelectRef.current(feature ?? null);
      });
      map.on("mouseenter", "gbif-points", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "gbif-points", () => {
        map.getCanvas().style.cursor = "";
      });
    });
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const apply = () => {
      if (map.getLayer("gbif-tiles-layer")) {
        map.removeLayer("gbif-tiles-layer");
      }
      if (map.getSource("gbif-tiles")) {
        map.removeSource("gbif-tiles");
      }
      if (mapData?.tile && map.getLayer("gbif-clusters")) {
        map.addSource("gbif-tiles", {
          type: "raster",
          tiles: [mapData.tile.urlTemplate],
          tileSize: mapData.tile.tileSize || 512,
          attribution: mapData.tile.attribution,
        });
        map.addLayer(
          {
            id: "gbif-tiles-layer",
            type: "raster",
            source: "gbif-tiles",
            paint: { "raster-opacity": mapData.style === "points" ? 0.85 : 0.92 },
          },
          map.getLayer("boundary-fill") ? "boundary-fill" : "gbif-clusters",
        );
      }
      const boundarySource = map.getSource("boundary") as maplibregl.GeoJSONSource | undefined;
      const boundary = mapData?.boundary ?? { type: "FeatureCollection", features: [] };
      boundarySource?.setData(boundary);
      const sampleSource = map.getSource("gbif-sample") as maplibregl.GeoJSONSource | undefined;
      sampleSource?.setData(mapData?.sample ?? { type: "FeatureCollection", features: [] });
      syncSampleVisibility(map, mapData?.style);
      if (mapData?.sample?.features?.length) {
        fitCollection(map, mapData.sample, 8);
      } else if (boundary.features?.length) {
        fitCollection(map, boundary, 7);
      }
    };

    if (!map.isStyleLoaded()) {
      map.once("load", apply);
    } else {
      apply();
    }
    const onZoom = () => syncSampleVisibility(map, mapData?.style);
    map.on("zoom", onZoom);
    return () => {
      map.off("zoom", onZoom);
      map.off("load", apply);
    };
  }, [mapData]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      const source = map.getSource("inat") as maplibregl.GeoJSONSource | undefined;
      source?.setData(inat ?? { type: "FeatureCollection", features: [] });
    };
    if (!map.isStyleLoaded()) {
      map.once("load", apply);
      return;
    }
    apply();
  }, [inat]);

  return <div className="map" ref={containerRef} />;
});

export default MapView;
