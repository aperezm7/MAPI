import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { InatOverlay, MapResponse, PointDisplay } from "./types";

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
  pointDisplay: PointDisplay;
  onSelect: (feature: GeoJSON.Feature | null) => void;
};

export type PngOptions = {
  grid: boolean;
  scaleBar: boolean;
  compass: boolean;
};

export type MapViewHandle = {
  exportPng: (options?: PngOptions) => string | null;
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

function syncSampleVisibility(map: maplibregl.Map, style: string | undefined, pointDisplay: PointDisplay) {
  if (pointDisplay === "individual") {
    if (map.getLayer("gbif-points")) map.setLayoutProperty("gbif-points", "visibility", "visible");
    return;
  }
  const hidePoints = style === "heat" && map.getZoom() < 7;
  const visibility = hidePoints ? "none" : "visible";
  for (const layerId of ["gbif-points", "gbif-clusters", "gbif-cluster-count"]) {
    if (map.getLayer(layerId)) {
      map.setLayoutProperty(layerId, "visibility", visibility);
    }
  }
}

function niceDegreeStep(span: number): number {
  const target = Math.max(span, 0.01) / 5;
  const steps = [0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 20, 30, 45];
  return steps.find((step) => step >= target) ?? 45;
}

function formatCoord(value: number, lat: boolean): string {
  const hemisphere = lat ? (value >= 0 ? "N" : "S") : value >= 0 ? "E" : "W";
  const abs = Math.abs(value);
  const rounded = Math.round(abs * 100) / 100;
  const text = Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(rounded < 1 ? 2 : 1);
  return `${text}°${hemisphere}`;
}

function niceMeters(meters: number): number {
  if (!Number.isFinite(meters) || meters <= 0) return 0;
  const power = 10 ** Math.floor(Math.log10(meters));
  const fraction = meters / power;
  const nice = fraction >= 5 ? 5 : fraction >= 2 ? 2 : 1;
  return nice * power;
}

function drawGraticule(ctx: CanvasRenderingContext2D, map: maplibregl.Map, ratio: number) {
  const bounds = map.getBounds();
  const west = bounds.getWest();
  const east = bounds.getEast();
  const south = bounds.getSouth();
  const north = bounds.getNorth();
  if (!(east > west) || !(north > south)) return;
  const step = niceDegreeStep(Math.max(east - west, north - south));
  const canvas = map.getCanvas();
  ctx.save();
  ctx.strokeStyle = "rgba(28, 36, 36, 0.55)";
  ctx.fillStyle = "rgba(20, 24, 24, 0.92)";
  ctx.lineWidth = Math.max(1, ratio);
  ctx.font = `${Math.round(11 * ratio)}px Georgia, "Times New Roman", serif`;
  for (let lon = Math.ceil(west / step) * step; lon < east; lon += step) {
    const x = map.project([lon, south]).x * ratio;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, canvas.height);
    ctx.stroke();
    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    ctx.fillText(formatCoord(lon, false), x + 4 * ratio, 6 * ratio);
  }
  for (let lat = Math.ceil(south / step) * step; lat < north; lat += step) {
    const y = map.project([west, lat]).y * ratio;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(canvas.width, y);
    ctx.stroke();
    ctx.textBaseline = "bottom";
    ctx.textAlign = "left";
    ctx.fillText(formatCoord(lat, true), 6 * ratio, y - 3 * ratio);
  }
  ctx.restore();
}

function drawScaleBar(ctx: CanvasRenderingContext2D, map: maplibregl.Map, ratio: number) {
  const maxCss = 128;
  const xCss = 18;
  const yCss = map.getContainer().clientHeight - 28;
  const meters = map.unproject([xCss, yCss]).distanceTo(map.unproject([xCss + maxCss, yCss]));
  const nice = niceMeters(meters * 0.9);
  if (!nice) return;
  const bar = maxCss * (nice / meters) * ratio;
  const x = xCss * ratio;
  const y = yCss * ratio;
  const label = nice >= 1000 ? `${nice / 1000} km` : `${Math.round(nice)} m`;
  ctx.save();
  ctx.fillStyle = "rgba(247, 244, 238, 0.92)";
  ctx.fillRect(x - 8 * ratio, y - 20 * ratio, bar + 16 * ratio, 30 * ratio);
  ctx.strokeStyle = "#1c2424";
  ctx.fillStyle = "#1c2424";
  ctx.lineWidth = Math.max(1, ratio);
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(x + bar, y);
  ctx.moveTo(x, y - 6 * ratio);
  ctx.lineTo(x, y + 4 * ratio);
  ctx.moveTo(x + bar, y - 6 * ratio);
  ctx.lineTo(x + bar, y + 4 * ratio);
  ctx.stroke();
  ctx.font = `${Math.round(12 * ratio)}px Georgia, "Times New Roman", serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "bottom";
  ctx.fillText(label, x + bar / 2, y - 3 * ratio);
  ctx.restore();
}

function drawCompass(ctx: CanvasRenderingContext2D, map: maplibregl.Map, ratio: number) {
  const canvas = map.getCanvas();
  const cx = canvas.width - 42 * ratio;
  const cy = 52 * ratio;
  const size = 16 * ratio;
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate((-map.getBearing() * Math.PI) / 180);
  ctx.beginPath();
  ctx.moveTo(0, -size);
  ctx.lineTo(size * 0.42, size * 0.85);
  ctx.lineTo(0, size * 0.35);
  ctx.closePath();
  ctx.fillStyle = "#1c2424";
  ctx.fill();
  ctx.beginPath();
  ctx.moveTo(0, -size);
  ctx.lineTo(-size * 0.42, size * 0.85);
  ctx.lineTo(0, size * 0.35);
  ctx.closePath();
  ctx.fillStyle = "#f7f4ee";
  ctx.strokeStyle = "#1c2424";
  ctx.lineWidth = Math.max(1, ratio);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "#1c2424";
  ctx.font = `${Math.round(13 * ratio)}px Georgia, "Times New Roman", serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "bottom";
  ctx.fillText("N", 0, -size - 2 * ratio);
  ctx.restore();
}

function installSampleLayers(map: maplibregl.Map, cluster: boolean) {
  for (const layerId of ["gbif-points", "gbif-cluster-count", "gbif-clusters"]) {
    if (map.getLayer(layerId)) map.removeLayer(layerId);
  }
  if (map.getSource("gbif-sample")) map.removeSource("gbif-sample");
  map.addSource("gbif-sample", {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
    cluster,
    clusterRadius: 42,
    clusterMaxZoom: 12,
  });
  const before = map.getLayer("inat-points") ? "inat-points" : undefined;
  if (cluster) {
    map.addLayer(
      {
        id: "gbif-clusters",
        type: "circle",
        source: "gbif-sample",
        filter: ["has", "point_count"],
        paint: {
          "circle-color": "#1f5f5b",
          "circle-radius": ["step", ["get", "point_count"], 14, 20, 18, 100, 24],
          "circle-opacity": 0.86,
        },
      },
      before,
    );
    map.addLayer(
      {
        id: "gbif-cluster-count",
        type: "symbol",
        source: "gbif-sample",
        filter: ["has", "point_count"],
        layout: { "text-field": "{point_count_abbreviated}", "text-size": 12 },
        paint: { "text-color": "#f7f4ee" },
      },
      before,
    );
  }
  map.addLayer(
    {
      id: "gbif-points",
      type: "circle",
      source: "gbif-sample",
      filter: ["!", ["has", "point_count"]],
      paint: {
        "circle-color": ["case", ["has", "taxonColor"], ["get", "taxonColor"], "#b4532a"],
        "circle-radius": cluster ? 5 : ["interpolate", ["linear"], ["zoom"], 2, 2.5, 6, 4, 11, 6],
        "circle-stroke-width": 1,
        "circle-stroke-color": "#f7f4ee",
      },
    },
    before,
  );
}

const MapView = forwardRef<MapViewHandle, Props>(function MapView({ mapData, inat, pointDisplay, onSelect }, ref) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const clusterRef = useRef<boolean | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useImperativeHandle(ref, () => ({
    exportPng: (options) => {
      const map = mapRef.current;
      if (!map) return null;
      map.triggerRepaint();
      const source = map.getCanvas();
      const decorations = options && (options.grid || options.scaleBar || options.compass);
      if (!decorations) return source.toDataURL("image/png");
      const canvas = document.createElement("canvas");
      canvas.width = source.width;
      canvas.height = source.height;
      const ctx = canvas.getContext("2d");
      if (!ctx) return null;
      ctx.drawImage(source, 0, 0);
      const ratio = source.width / (map.getContainer().clientWidth || 1);
      if (options.grid) drawGraticule(ctx, map, ratio);
      if (options.scaleBar) drawScaleBar(ctx, map, ratio);
      if (options.compass) drawCompass(ctx, map, ratio);
      return canvas.toDataURL("image/png");
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
      installSampleLayers(map, true);
      clusterRef.current = true;

      map.on("click", (event) => {
        if (map.getLayer("gbif-clusters")) {
          const cluster = map.queryRenderedFeatures(event.point, { layers: ["gbif-clusters"] })[0];
          const clusterId = cluster?.properties?.cluster_id;
          const source = map.getSource("gbif-sample") as maplibregl.GeoJSONSource | undefined;
          if (cluster && clusterId != null && source) {
            source.getClusterExpansionZoom(clusterId).then((zoom) => {
              const coords = (cluster.geometry as GeoJSON.Point).coordinates as [number, number];
              map.easeTo({ center: coords, zoom });
            });
            return;
          }
        }
        const layers = ["gbif-points", "inat-points"].filter((id) => map.getLayer(id));
        const feature = layers.length ? map.queryRenderedFeatures(event.point, { layers })[0] : undefined;
        if (feature) onSelectRef.current(feature);
      });
      map.on("mousemove", (event) => {
        const layers = ["gbif-points", "gbif-clusters", "inat-points"].filter((id) => map.getLayer(id));
        const hit = layers.length ? map.queryRenderedFeatures(event.point, { layers })[0] : undefined;
        map.getCanvas().style.cursor = hit ? "pointer" : "";
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
      const cluster = pointDisplay !== "individual";
      if (clusterRef.current !== cluster || !map.getSource("gbif-sample")) {
        installSampleLayers(map, cluster);
        clusterRef.current = cluster;
      }
      const tileAnchor = map.getLayer("boundary-fill") ? "boundary-fill" : map.getLayer("gbif-clusters") ? "gbif-clusters" : "gbif-points";
      if (mapData?.tile && tileAnchor && map.getLayer(tileAnchor)) {
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
          tileAnchor,
        );
      }
      const boundarySource = map.getSource("boundary") as maplibregl.GeoJSONSource | undefined;
      const boundary = mapData?.boundary ?? { type: "FeatureCollection", features: [] };
      boundarySource?.setData(boundary);
      const sampleSource = map.getSource("gbif-sample") as maplibregl.GeoJSONSource | undefined;
      sampleSource?.setData(mapData?.sample ?? { type: "FeatureCollection", features: [] });
      syncSampleVisibility(map, mapData?.style, pointDisplay);
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
    const onZoom = () => syncSampleVisibility(map, mapData?.style, pointDisplay);
    map.on("zoom", onZoom);
    return () => {
      map.off("zoom", onZoom);
      map.off("load", apply);
    };
  }, [mapData, pointDisplay]);

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
