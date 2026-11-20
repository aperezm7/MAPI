import { useEffect, useRef, useState } from "react";
import QueryRail from "./QueryRail";
import YearRange from "./YearRange";
import MapView, { type MapViewHandle } from "./MapView";
import RecordPanel from "./RecordPanel";
import { downloadQgisPackage, fetchIucn, fetchInat, fetchMap, requestGbifDownload, resolveQuery, suggestTaxon, triggerDownload } from "./api";
import { loadLibrary, mapFileSlug, newMapId, saveLibrary, type MapLibrary } from "./mapLibrary";
import { emptyQuery, type IucnStatus, type InatOverlay, type MapQuery, type MapResponse, type PlaceCandidate, type TaxonCandidate, type YearCount } from "./types";
import { writeQueryToUrl } from "./urlState";

function clampedYearWindow(bins: YearCount[], time: MapQuery["time"]): { start: number; end: number } {
  const first = bins[0].year;
  const last = bins[bins.length - 1].year;
  const start = Math.min(last, Math.max(time?.yearMin ?? first, first));
  const end = Math.min(last, Math.max(time?.yearMax ?? last, first));
  return start <= end ? { start, end } : { start: end, end: start };
}

export default function App() {
  const [boot] = useState(loadLibrary);
  const [library, setLibrary] = useState<MapLibrary>(boot);
  const [query, setQuery] = useState<MapQuery>(
    () => boot.maps.find((map) => map.id === boot.activeId)?.query ?? emptyQuery(),
  );
  const [taxonCandidates, setTaxonCandidates] = useState<TaxonCandidate[]>([]);
  const [taxonNeeds, setTaxonNeeds] = useState(false);
  const [placeNeeds, setPlaceNeeds] = useState(false);
  const [mapData, setMapData] = useState<MapResponse | null>(null);
  const [inat, setInat] = useState<InatOverlay | null>(null);
  const [selected, setSelected] = useState<GeoJSON.Feature | null>(null);
  const [iucn, setIucn] = useState<IucnStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [taxonError, setTaxonError] = useState<string | null>(null);
  const [downloadMsg, setDownloadMsg] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<"qgis" | "gbif" | null>(null);
  const mapRef = useRef<MapViewHandle>(null);
  const queryRef = useRef(query);
  queryRef.current = query;

  useEffect(() => {
    writeQueryToUrl(query);
  }, [query]);

  useEffect(() => {
    setLibrary((prev) => ({
      ...prev,
      maps: prev.maps.map((map) => (map.id === prev.activeId ? { ...map, query } : map)),
    }));
  }, [query]);

  useEffect(() => {
    saveLibrary(library);
  }, [library]);

  function commitYearWindow(start: number, end: number) {
    if (!mapData?.histogram.length) return;
    const first = mapData.histogram[0].year;
    const last = mapData.histogram[mapData.histogram.length - 1].year;
    const yearMin = start <= first ? null : start;
    const yearMax = end >= last ? null : end;
    const applied = mapData.query.time;
    const unchanged =
      (applied?.yearMin ?? first) === start &&
      (applied?.yearMax ?? last) === end &&
      (queryRef.current.time?.yearMin ?? null) === yearMin &&
      (queryRef.current.time?.yearMax ?? null) === yearMax;
    if (unchanged) return;
    const next = { ...queryRef.current, time: { ...queryRef.current.time, yearMin, yearMax } };
    setQuery(next);
    void compile(next);
  }

  async function applyResolved(next: MapQuery, extras?: {
    taxonCandidates?: TaxonCandidate[];
    placeCandidates?: PlaceCandidate[];
    taxonNeedsDisambiguation?: boolean;
    placeNeedsDisambiguation?: boolean;
    warnings?: string[];
  }) {
    setQuery(next);
    if (extras?.taxonCandidates) setTaxonCandidates(extras.taxonCandidates);
    setTaxonNeeds(Boolean(extras?.taxonNeedsDisambiguation));
    setPlaceNeeds(Boolean(extras?.placeNeedsDisambiguation));
    if (extras?.warnings?.length) setError(extras.warnings.join(" "));
  }

  async function onSuggest(q: string, rankHint?: string | null) {
    const name = q.trim();
    if (!name) {
      setTaxonError("Type a taxon name first.");
      return;
    }
    setLoading(true);
    setTaxonError(null);
    try {
      const data = await suggestTaxon(name, rankHint);
      setTaxonCandidates(data.candidates);
      setTaxonNeeds(data.needsDisambiguation && data.candidates.length > 0);
      if (!data.candidates.length) {
        setQuery((prev) => ({ ...prev, taxon: { q, rankHint: rankHint ?? prev.taxon?.rankHint } }));
        setTaxonError(data.warnings[0] ?? `No GBIF taxon matches “${name}”.`);
        return;
      }
      if (data.warnings.length) setTaxonError(data.warnings.join(" "));
      if (!data.needsDisambiguation) onPickTaxon(data.candidates[0], q, data.warnings);
    } catch (err) {
      setTaxonError(err instanceof Error ? err.message : "Taxon lookup failed");
    } finally {
      setLoading(false);
    }
  }

  function onPickTaxon(candidate: TaxonCandidate, typed?: string, warnings: string[] = []) {
    setQuery((prev) => ({
      ...prev,
      taxon: {
        q: typed ?? candidate.canonicalName ?? candidate.scientificName,
        rankHint: prev.taxon?.rankHint,
        gbifKey: candidate.gbifKey,
        scientificName: candidate.scientificName,
        canonicalName: candidate.canonicalName,
        rank: candidate.rank,
      },
    }));
    setTaxonCandidates((prev) => (prev.some((c) => c.gbifKey === candidate.gbifKey) ? prev : [candidate]));
    setTaxonNeeds(false);
    setTaxonError(warnings.length ? warnings.join(" ") : null);
  }

  function onPickPlace(candidate: PlaceCandidate) {
    setQuery((prev) => ({ ...prev, place: { q: candidate.title, kind: "country", iso2: candidate.iso2, title: candidate.title } }));
    setPlaceNeeds(false);
  }

  async function compile(target: MapQuery = query) {
    setLoading(true);
    setError(null);
    setSelected(null);
    setDownloadMsg(null);
    try {
      const resolved = await resolveQuery(target);
      await applyResolved(resolved.query, resolved);
      if (resolved.taxonNeedsDisambiguation && !target.taxon?.gbifKey) {
        setMapData(null);
        setError("Pick a taxon match before drawing the map.");
        return;
      }
      const mapped = await fetchMap(resolved.query);
      setMapData(mapped);
      setTaxonCandidates(mapped.taxonCandidates ?? resolved.taxonCandidates);
      setTaxonNeeds(Boolean(mapped.taxonNeedsDisambiguation));
      setPlaceNeeds(Boolean(mapped.placeNeedsDisambiguation));
      if (mapped.blocked) {
        setError("Homonym or weak match — confirm the taxon in the list.");
        return;
      }
      if (mapped.warnings.length) setError(mapped.warnings.join(" "));
      if (resolved.query.map?.includeInat) {
        try {
          setInat(await fetchInat(resolved.query));
        } catch (err) {
          setInat(null);
          setError((err instanceof Error ? err.message : "iNaturalist overlay failed") + (mapped.warnings.length ? ` ${mapped.warnings.join(" ")}` : ""));
        }
      } else {
        setInat(null);
      }
      const name = resolved.query.taxon?.scientificName || resolved.query.taxon?.canonicalName;
      if (name && (resolved.query.taxon?.rank || "").toUpperCase() === "SPECIES") {
        setIucn(await fetchIucn(name));
      } else {
        setIucn(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Map compile failed");
    } finally {
      setLoading(false);
    }
  }

  const activeMap = library.maps.find((map) => map.id === library.activeId);

  function openMap(id: string) {
    const next = library.maps.find((map) => map.id === id);
    if (!next || next.id === library.activeId) return;
    setLibrary((prev) => ({ ...prev, activeId: id }));
    setQuery(next.query);
    setSelected(null);
    void compile(next.query);
  }

  function newMap() {
    const id = newMapId();
    const created = { id, name: `Map ${library.maps.length + 1}`, query: emptyQuery() };
    setLibrary((prev) => ({ maps: [...prev.maps, created], activeId: id }));
    setQuery(created.query);
    setMapData(null);
    setInat(null);
    setSelected(null);
    setError(null);
  }

  function duplicateMap() {
    if (!activeMap) return;
    const id = newMapId();
    const created = { id, name: `Copy of ${activeMap.name}`, query };
    setLibrary((prev) => ({ maps: [...prev.maps, created], activeId: id }));
    setQuery(created.query);
    void compile(created.query);
  }

  function deleteMap() {
    if (library.maps.length < 2 || !activeMap) return;
    const remaining = library.maps.filter((map) => map.id !== activeMap.id);
    const next = remaining[0];
    setLibrary({ maps: remaining, activeId: next.id });
    setQuery(next.query);
    void compile(next.query);
  }

  function renameMap(name: string) {
    setLibrary((prev) => ({
      ...prev,
      maps: prev.maps.map((map) => (map.id === prev.activeId ? { ...map, name } : map)),
    }));
  }

  async function onSelectFeature(feature: GeoJSON.Feature | null) {
    setSelected(feature);
    const name = feature?.properties?.scientificName;
    if (typeof name === "string" && name.split(" ").length >= 2) {
      try {
        setIucn(await fetchIucn(name));
      } catch {
        setIucn(null);
      }
    }
  }

  function exportSample() {
    if (!mapData?.sample) return;
    const blob = new Blob([JSON.stringify(mapData.sample, null, 2)], { type: "application/geo+json" });
    triggerDownload(blob, `${mapFileSlug(activeMap?.name ?? "map")}-sample.geojson`);
  }

  function exportBoundary() {
    if (!mapData?.boundary?.features.length) return;
    const blob = new Blob([JSON.stringify(mapData.boundary, null, 2)], { type: "application/geo+json" });
    triggerDownload(blob, `${mapFileSlug(activeMap?.name ?? "map")}-boundary.geojson`);
  }

  function exportPng() {
    try {
      const dataUrl = mapRef.current?.exportPng();
      if (!dataUrl) {
        setDownloadMsg("Map is not ready to export yet.");
        return;
      }
      const link = document.createElement("a");
      link.href = dataUrl;
      link.download = `${mapFileSlug(activeMap?.name ?? "map")}.png`;
      link.click();
    } catch (err) {
      const message = err instanceof Error ? err.message : "PNG export failed";
      setDownloadMsg(
        /taint|security/i.test(message)
          ? "PNG export was blocked by the browser (cross-origin basemap tiles). Use GeoJSON or QGIS export instead."
          : message,
      );
    }
  }

  async function exportQgis() {
    setDownloadMsg(null);
    setBusyAction("qgis");
    try {
      await downloadQgisPackage(query);
      setDownloadMsg("Downloaded a QGIS package (GeoJSON + PyQGIS loader). Open it in QGIS Desktop.");
    } catch (err) {
      setDownloadMsg(err instanceof Error ? err.message : "QGIS export failed");
    } finally {
      setBusyAction(null);
    }
  }

  async function onDownload() {
    setDownloadMsg(null);
    setBusyAction("gbif");
    try {
      const result = await requestGbifDownload(query);
      setDownloadMsg(result.message || (result.available ? `Queued ${result.key}` : "Download unavailable"));
    } catch (err) {
      setDownloadMsg(err instanceof Error ? err.message : "Download failed");
    } finally {
      setBusyAction(null);
    }
  }

  return (
    <div className="app">
      <QueryRail
        query={query}
        setQuery={setQuery}
        taxonCandidates={taxonCandidates}
        taxonNeeds={taxonNeeds}
        placeNeeds={placeNeeds}
        loading={loading}
        maps={library.maps}
        activeMapId={library.activeId}
        onOpenMap={openMap}
        onNewMap={newMap}
        onDuplicateMap={duplicateMap}
        onDeleteMap={deleteMap}
        onRenameMap={renameMap}
        onSuggest={(q, rankHint) => void onSuggest(q, rankHint)}
        onPickTaxon={(c) => onPickTaxon(c)}
        onPickPlace={onPickPlace}
        taxonError={taxonError}
        clearLookupError={() => setTaxonError(null)}
        onMap={() => void compile()}
      />
      <main className="stage">
        <MapView ref={mapRef} mapData={mapData} inat={inat} onSelect={(f) => void onSelectFeature(f)} />
        <div className="hud">
          {error ? <div className="warn">{error}</div> : null}
          {!mapData && !error ? (
            <div className="empty">Resolve a taxon and place, then draw the map. Tiles show density; points are a capped inspectable sample.</div>
          ) : null}
          {mapData && !mapData.blocked ? (
            <div className="card">
              <div className="count-badge">{mapData.count.toLocaleString()} records</div>
              <div className="footer-attr">{activeMap?.name ?? "Map"}</div>
              <div className="footer-attr">
                {mapData.mode} · {mapData.style}
                {mapData.sampleTruncated ? " · sample truncated" : ""}
                {mapData.sampleOmittedSensitive ? ` · omitted ${mapData.sampleOmittedSensitive} sensitive points` : ""}
              </div>
              {mapData.histogram.length > 0 ? (
                <YearRange
                  bins={mapData.histogram}
                  {...clampedYearWindow(mapData.histogram, query.time)}
                  disabled={loading}
                  onChange={(start, end) =>
                    setQuery((prev) => ({ ...prev, time: { ...prev.time, yearMin: start, yearMax: end } }))
                  }
                  onCommit={commitYearWindow}
                />
              ) : null}
              <div className="actions">
                <button type="button" className="secondary" onClick={exportSample} disabled={!mapData.sample.features.length}>
                  Export sample GeoJSON
                </button>
                <button type="button" className="secondary" onClick={exportBoundary} disabled={!mapData.boundary?.features.length}>
                  Export boundary GeoJSON
                </button>
                <button type="button" className="secondary" onClick={exportPng}>
                  Export map PNG
                </button>
                <button type="button" className="secondary" onClick={() => void exportQgis()} disabled={busyAction !== null}>
                  {busyAction === "qgis" ? "Exporting QGIS…" : "Export QGIS package"}
                </button>
                <button type="button" className="secondary" onClick={() => void onDownload()} disabled={busyAction !== null}>
                  {busyAction === "gbif" ? "Requesting…" : "Request GBIF download"}
                </button>
              </div>
              {downloadMsg ? <div className="empty">{downloadMsg}</div> : null}
              {mapData.attribution.map((line) => (
                <div className="footer-attr" key={line}>
                  {line}
                </div>
              ))}
              {inat ? <div className="footer-attr">{inat.attribution.join(" ")}</div> : null}
            </div>
          ) : null}
          <RecordPanel feature={selected} iucn={iucn} onClose={() => setSelected(null)} />
        </div>
      </main>
    </div>
  );
}
