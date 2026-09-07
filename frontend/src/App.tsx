import { useEffect, useMemo, useRef, useState } from "react";
import QueryRail from "./QueryRail";
import MapView, { type MapViewHandle } from "./MapView";
import RecordPanel from "./RecordPanel";
import { downloadQgisPackage, fetchIucn, fetchInat, fetchMap, fetchNlStatus, planNl, requestGbifDownload, resolveQuery, suggestTaxon, triggerDownload } from "./api";
import { emptyQuery, type IucnStatus, type InatOverlay, type MapQuery, type MapResponse, type NlStatus, type PlaceCandidate, type TaxonCandidate } from "./types";
import { readQueryFromUrl, writeQueryToUrl } from "./urlState";

export default function App() {
  const [query, setQuery] = useState<MapQuery>(() => readQueryFromUrl() ?? emptyQuery());
  const [nlPrompt, setNlPrompt] = useState("show endangered amphibians in Costa Rica since 2015");
  const [nlDraft, setNlDraft] = useState<MapQuery | null>(null);
  const [nlNotes, setNlNotes] = useState<string[]>([]);
  const [nlStatus, setNlStatus] = useState<NlStatus | null>(null);
  const [taxonCandidates, setTaxonCandidates] = useState<TaxonCandidate[]>([]);
  const [placeCandidates, setPlaceCandidates] = useState<PlaceCandidate[]>([]);
  const [taxonNeeds, setTaxonNeeds] = useState(false);
  const [placeNeeds, setPlaceNeeds] = useState(false);
  const [mapData, setMapData] = useState<MapResponse | null>(null);
  const [inat, setInat] = useState<InatOverlay | null>(null);
  const [selected, setSelected] = useState<GeoJSON.Feature | null>(null);
  const [iucn, setIucn] = useState<IucnStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [downloadMsg, setDownloadMsg] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<"qgis" | "gbif" | null>(null);
  const mapRef = useRef<MapViewHandle>(null);

  useEffect(() => {
    writeQueryToUrl(query);
  }, [query]);

  useEffect(() => {
    fetchNlStatus()
      .then(setNlStatus)
      .catch(() => setNlStatus(null));
  }, []);

  const maxHist = useMemo(
    () => Math.max(1, ...(mapData?.histogram.map((h) => h.count) ?? [1])),
    [mapData],
  );

  async function applyResolved(next: MapQuery, extras?: {
    taxonCandidates?: TaxonCandidate[];
    placeCandidates?: PlaceCandidate[];
    taxonNeedsDisambiguation?: boolean;
    placeNeedsDisambiguation?: boolean;
    warnings?: string[];
  }) {
    setQuery(next);
    if (extras?.taxonCandidates) setTaxonCandidates(extras.taxonCandidates);
    if (extras?.placeCandidates) setPlaceCandidates(extras.placeCandidates);
    setTaxonNeeds(Boolean(extras?.taxonNeedsDisambiguation));
    setPlaceNeeds(Boolean(extras?.placeNeedsDisambiguation));
    if (extras?.warnings?.length) setError(extras.warnings.join(" "));
  }

  async function onSuggest(q: string, rankHint?: string | null) {
    setLoading(true);
    setError(null);
    try {
      const data = await suggestTaxon(q, rankHint);
      setTaxonCandidates(data.candidates);
      setTaxonNeeds(data.needsDisambiguation);
      if (data.candidates[0] && !data.needsDisambiguation) {
        const top = data.candidates[0];
        setQuery((prev) => ({
          ...prev,
          taxon: {
            ...prev.taxon,
            q,
            rankHint: rankHint ?? prev.taxon?.rankHint,
            gbifKey: top.gbifKey,
            scientificName: top.scientificName,
            canonicalName: top.canonicalName,
            rank: top.rank,
          },
        }));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Taxon lookup failed");
    } finally {
      setLoading(false);
    }
  }

  async function onResolvePlace() {
    setLoading(true);
    setError(null);
    try {
      const resolved = await resolveQuery(query);
      await applyResolved(resolved.query, resolved);
      if (resolved.warnings.length) setError(resolved.warnings.join(" "));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Place lookup failed");
    } finally {
      setLoading(false);
    }
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
      setPlaceCandidates(mapped.placeCandidates ?? resolved.placeCandidates);
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

  async function onPlan() {
    setLoading(true);
    setError(null);
    try {
      const planned = await planNl(nlPrompt);
      setNlDraft(planned.resolve.query);
      const origin = [planned.provider, planned.model].filter(Boolean).join(" · ");
      setNlNotes(origin ? [origin, ...planned.notes] : planned.notes);
      await applyResolved(planned.resolve.query, planned.resolve);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Planner unavailable");
    } finally {
      setLoading(false);
    }
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
    triggerDownload(blob, "mapi-sample.geojson");
  }

  function exportBoundary() {
    if (!mapData?.boundary?.features.length) return;
    const blob = new Blob([JSON.stringify(mapData.boundary, null, 2)], { type: "application/geo+json" });
    triggerDownload(blob, "mapi-boundary.geojson");
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
      link.download = "mapi-map.png";
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
        placeCandidates={placeCandidates}
        taxonNeeds={taxonNeeds}
        placeNeeds={placeNeeds}
        loading={loading}
        nlPrompt={nlPrompt}
        setNlPrompt={setNlPrompt}
        nlNotes={nlNotes}
        onSuggest={onSuggest}
        onResolvePlace={() => void onResolvePlace()}
        onMap={() => void compile()}
        onPlan={() => void onPlan()}
        onConfirmNl={() => void compile()}
        hasNlDraft={Boolean(nlDraft)}
        nlStatus={nlStatus}
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
              <div className="footer-attr">
                {mapData.mode} · {mapData.style}
                {mapData.sampleTruncated ? " · sample truncated" : ""}
                {mapData.sampleOmittedSensitive ? ` · omitted ${mapData.sampleOmittedSensitive} sensitive points` : ""}
              </div>
              {mapData.histogram.length > 0 ? (
                <>
                  <div className="histogram" title="GBIF occurrence counts by year">
                    {mapData.histogram.map((bin) => (
                      <span key={bin.year} style={{ height: `${Math.max(4, (bin.count / maxHist) * 100)}%` }} title={`${bin.year}: ${bin.count}`} />
                    ))}
                  </div>
                  <div className="row">
                    <label className="field">
                      Slider from
                      <input
                        type="range"
                        min={mapData.histogram[0].year}
                        max={mapData.histogram[mapData.histogram.length - 1].year}
                        value={query.time?.yearMin ?? mapData.histogram[0].year}
                        onChange={(e) =>
                          setQuery({
                            ...query,
                            time: { ...query.time, yearMin: Number(e.target.value) },
                          })
                        }
                      />
                    </label>
                    <label className="field">
                      Slider to
                      <input
                        type="range"
                        min={mapData.histogram[0].year}
                        max={mapData.histogram[mapData.histogram.length - 1].year}
                        value={query.time?.yearMax ?? mapData.histogram[mapData.histogram.length - 1].year}
                        onChange={(e) =>
                          setQuery({
                            ...query,
                            time: { ...query.time, yearMax: Number(e.target.value) },
                          })
                        }
                      />
                    </label>
                  </div>
                  <button type="button" className="linkish" onClick={() => void compile()} disabled={loading}>
                    Apply year window
                  </button>
                </>
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
