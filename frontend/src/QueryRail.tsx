import { FormEvent, useEffect, useMemo, useState } from "react";
import AccountCard from "./AccountCard";
import Autocomplete from "./Autocomplete";
import MapShelf from "./MapShelf";
import { autocompleteTaxon, fetchCountries } from "./api";
import type { SavedMap } from "./mapLibrary";
import type { IucnCode, MapQuery, PlaceCandidate, TaxonCandidate } from "./types";
import { IUCN_OPTIONS, JAGUAR_PRESET, NORTHSTAR } from "./types";

type Props = {
  query: MapQuery;
  setQuery: (query: MapQuery) => void;
  taxonCandidates: TaxonCandidate[];
  taxonNeeds: boolean;
  placeNeeds: boolean;
  loading: boolean;
  maps: SavedMap[];
  activeMapId: string;
  onOpenMap: (id: string) => void;
  onNewMap: () => void;
  onDuplicateMap: () => void;
  onDeleteMap: () => void;
  onRenameMap: (name: string) => void;
  onSuggest: (q: string, rankHint?: string | null) => void;
  onPickTaxon: (candidate: TaxonCandidate) => void;
  onPickPlace: (candidate: PlaceCandidate) => void;
  taxonError: string | null;
  clearLookupError: (field: "taxon" | "place") => void;
  onMap: () => void;
};

export default function QueryRail({
  query,
  setQuery,
  taxonCandidates,
  taxonNeeds,
  placeNeeds,
  loading,
  maps,
  activeMapId,
  onOpenMap,
  onNewMap,
  onDuplicateMap,
  onDeleteMap,
  onRenameMap,
  onSuggest,
  onPickTaxon,
  onPickPlace,
  taxonError,
  clearLookupError,
  onMap,
}: Props) {
  const selectedIucn = query.conservation?.iucn ?? [];
  const resolved = useMemo(() => {
    const bits = [
      query.taxon?.canonicalName || query.taxon?.scientificName,
      query.taxon?.rank,
      query.place?.iso2,
      query.time?.yearMin ? `${query.time.yearMin}–${query.time.yearMax ?? "now"}` : null,
      selectedIucn.length ? selectedIucn.join("/") : null,
    ].filter(Boolean);
    return bits.join(" · ");
  }, [query, selectedIucn]);

  function patch(partial: MapQuery) {
    setQuery({
      ...query,
      ...partial,
      taxon: { ...query.taxon, ...partial.taxon },
      place: { ...query.place, ...partial.place },
      time: { ...query.time, ...partial.time },
      conservation: { ...query.conservation, ...partial.conservation },
      map: { ...query.map, ...partial.map },
    });
  }

  function toggleIucn(code: IucnCode) {
    const next = selectedIucn.includes(code)
      ? selectedIucn.filter((c) => c !== code)
      : [...selectedIucn, code];
    patch({ conservation: { iucn: next } });
  }

  function onTaxonSubmit(event?: FormEvent) {
    event?.preventDefault();
    if (!loading) onSuggest(query.taxon?.q ?? "", query.taxon?.rankHint);
  }

  const [countries, setCountries] = useState<PlaceCandidate[]>([]);
  const [countriesError, setCountriesError] = useState<string | null>(null);

  useEffect(() => {
    fetchCountries()
      .then((rows) => setCountries([...rows].sort((a, b) => a.title.localeCompare(b.title))))
      .catch((err) => setCountriesError(err instanceof Error ? err.message : "Country list unavailable"));
  }, []);

  function chooseCountry(iso2: string) {
    clearLookupError("place");
    const country = countries.find((item) => item.iso2 === iso2);
    if (!country) {
      patch({ place: { q: "", iso2: null, title: null, kind: "country" } });
      return;
    }
    onPickPlace(country);
  }

  return (
    <aside className="rail">
      <div className="brand">
        <h1>MAPI</h1>
        <p>Build each map from the menus. Coordinates come from GBIF, never from a model.</p>
      </div>

      <MapShelf
        maps={maps}
        activeId={activeMapId}
        onOpen={onOpenMap}
        onNew={onNewMap}
        onDuplicate={onDuplicateMap}
        onDelete={onDeleteMap}
        onRename={onRenameMap}
      />

      <AccountCard />

      <section className="card">
        <h2>Connections</h2>
        <div className="footer-attr">GBIF supplies the taxon, the country list, occurrence tiles, and the sample.</div>
        <div className="footer-attr">geoBoundaries draws the country outline.</div>
        <div className="footer-attr">IUCN categories filter through GBIF. A species click asks the Red List for the card.</div>
        <div className="footer-attr">iNaturalist is optional and adds research-grade photo points.</div>
      </section>

      <section className="card">
        <h2>MapQuery</h2>
        {resolved ? <div className="chip active">{resolved}</div> : <div className="empty">Nothing resolved yet.</div>}
        <div className="actions">
          <button type="button" className="linkish" onClick={() => setQuery(NORTHSTAR)}>
            Example: endangered amphibians, Costa Rica, 2015+
          </button>
          <button type="button" className="linkish" onClick={() => setQuery(JAGUAR_PRESET)}>
            Example: jaguar in Costa Rica
          </button>
        </div>
      </section>

      <form className="card" onSubmit={onTaxonSubmit}>
        <h2>Taxon</h2>
        <label className="field">
          Name
          <Autocomplete<TaxonCandidate>
            value={query.taxon?.q ?? ""}
            onChange={(q) => {
              clearLookupError("taxon");
              patch({ taxon: { q, gbifKey: null, scientificName: null, canonicalName: null, rank: null } });
            }}
            fetchOptions={(q, signal) => autocompleteTaxon(q, query.taxon?.rankHint, signal)}
            describe={(c) => ({
              label: c.canonicalName || c.scientificName || String(c.gbifKey),
              detail: [
                c.rank,
                c.class || c.kingdom,
                c.status && c.status.toUpperCase() !== "ACCEPTED" ? c.status.toLowerCase() : null,
              ]
                .filter(Boolean)
                .join(" · "),
            })}
            getKey={(c) => c.gbifKey}
            onPick={onPickTaxon}
            onEnter={() => onTaxonSubmit()}
            placeholder="Amphibia, Panthera onca…"
            emptyHint="No quick matches. Press Enter to search GBIF, including common names."
            invalid={Boolean(taxonError)}
            describedBy={taxonError ? "taxon-error" : undefined}
          />
        </label>
        <label className="field">
          Rank hint
          <select
            value={query.taxon?.rankHint ?? ""}
            onChange={(e) => patch({ taxon: { rankHint: e.target.value || null } })}
          >
            <option value="">any</option>
            <option value="kingdom">kingdom</option>
            <option value="phylum">phylum</option>
            <option value="class">class</option>
            <option value="order">order</option>
            <option value="family">family</option>
            <option value="genus">genus</option>
            <option value="species">species</option>
          </select>
        </label>
        <button type="submit" className="secondary" disabled={loading}>
          Resolve taxon
        </button>
        {taxonError ? (
          <div className="warn" id="taxon-error" role="alert">
            {taxonError}
          </div>
        ) : null}
        {taxonNeeds ? <div className="warn">Multiple matches — pick the intended taxon.</div> : null}
        {taxonCandidates.length > 0 ? (
          <ul className="candidates">
            {taxonCandidates.map((c) => (
              <li key={c.gbifKey}>
                <button
                  type="button"
                  className={c.gbifKey === query.taxon?.gbifKey ? "selected" : ""}
                  onClick={() => onPickTaxon(c)}
                >
                  {c.canonicalName || c.scientificName}
                  <small>
                    {c.rank} · GBIF {c.gbifKey}
                    {c.kingdom ? ` · ${c.kingdom}` : ""}
                  </small>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </form>

      <section className="card">
        <h2>Place</h2>
        <label className="field">
          Country
          <select value={query.place?.iso2 ?? ""} onChange={(event) => chooseCountry(event.target.value)} disabled={!countries.length}>
            <option value="">{countries.length ? "Choose a country" : "Loading countries…"}</option>
            {query.place?.iso2 && !countries.some((country) => country.iso2 === query.place?.iso2) ? (
              <option value={query.place.iso2}>{query.place.title || query.place.q || query.place.iso2}</option>
            ) : null}
            {countries.map((country) => (
              <option key={country.iso2} value={country.iso2}>
                {country.title}
              </option>
            ))}
          </select>
        </label>
        {countriesError ? <div className="warn">{countriesError}</div> : null}
        {placeNeeds ? <div className="warn">Pick a country from the list.</div> : null}
      </section>

      <section className="card">
        <h2>Time</h2>
        <div className="row">
          <label className="field">
            From
            <input
              type="number"
              value={query.time?.yearMin ?? ""}
              onChange={(e) => patch({ time: { yearMin: e.target.value ? Number(e.target.value) : null } })}
            />
          </label>
          <label className="field">
            To
            <input
              type="number"
              value={query.time?.yearMax ?? ""}
              onChange={(e) => patch({ time: { yearMax: e.target.value ? Number(e.target.value) : null } })}
            />
          </label>
        </div>
      </section>

      <section className="card">
        <h2>IUCN (via GBIF)</h2>
        <div className="chips">
          {IUCN_OPTIONS.map((opt) => (
            <button
              key={opt.code}
              type="button"
              className={selectedIucn.includes(opt.code) ? "chip active" : "chip ghost"}
              title={opt.label}
              aria-pressed={selectedIucn.includes(opt.code)}
              onClick={() => toggleIucn(opt.code)}
            >
              {opt.code}
            </button>
          ))}
        </div>
      </section>

      <section className="card">
        <h2>Map style</h2>
        <label className="field">
          Drawing
          <select
            value={query.map?.style ?? "points"}
            onChange={(event) => patch({ map: { style: event.target.value as "points" | "hex" | "heat" } })}
          >
            <option value="points">Points</option>
            <option value="hex">Hexagons</option>
            <option value="heat">Heat</option>
          </select>
        </label>
        <label className="field">
          <span>
            <input
              type="checkbox"
              checked={Boolean(query.map?.includeInat)}
              onChange={(e) => patch({ map: { includeInat: e.target.checked } })}
            />{" "}
            iNaturalist research-grade overlay
          </span>
        </label>
      </section>

      <div className="actions">
        <button type="button" className="primary" onClick={onMap} disabled={loading}>
          {loading ? "Compiling…" : "Draw map"}
        </button>
      </div>
    </aside>
  );
}
