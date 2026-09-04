import { FormEvent, useMemo } from "react";
import type { IucnCode, MapQuery, NlStatus, PlaceCandidate, TaxonCandidate } from "./types";
import { IUCN_OPTIONS, JAGUAR_PRESET, NORTHSTAR } from "./types";

type Props = {
  query: MapQuery;
  setQuery: (query: MapQuery) => void;
  taxonCandidates: TaxonCandidate[];
  placeCandidates: PlaceCandidate[];
  taxonNeeds: boolean;
  placeNeeds: boolean;
  loading: boolean;
  nlPrompt: string;
  setNlPrompt: (value: string) => void;
  nlNotes: string[];
  onSuggest: (q: string) => void;
  onMap: () => void;
  onPlan: () => void;
  onConfirmNl: () => void;
  hasNlDraft: boolean;
  nlStatus: NlStatus | null;
};

export default function QueryRail({
  query,
  setQuery,
  taxonCandidates,
  placeCandidates,
  taxonNeeds,
  placeNeeds,
  loading,
  nlPrompt,
  setNlPrompt,
  nlNotes,
  onSuggest,
  onMap,
  onPlan,
  onConfirmNl,
  hasNlDraft,
  nlStatus,
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

  function onTaxonSubmit(event: FormEvent) {
    event.preventDefault();
    if (query.taxon?.q) onSuggest(query.taxon.q);
  }

  return (
    <aside className="rail">
      <div className="brand">
        <h1>MAPI</h1>
        <p>Species APIs, compiled into a map query — never guessed coordinates.</p>
      </div>

      <section className="card">
        <h2>Natural language</h2>
        {nlStatus ? (
          <div className={nlStatus.available ? "ok" : "empty"}>
            {nlStatus.available
              ? `${nlStatus.provider} · ${nlStatus.model}`
              : nlStatus.message || "Planner unavailable"}
          </div>
        ) : null}
        <textarea
          value={nlPrompt}
          onChange={(e) => setNlPrompt(e.target.value)}
          placeholder="show endangered amphibians in Costa Rica since 2015"
        />
        <div className="actions">
          <button
            type="button"
            className={`secondary${loading ? " loading" : ""}`}
            onClick={onPlan}
            disabled={loading}
            aria-busy={loading}
          >
            {loading ? "Planning…" : "Plan query"}
          </button>
          <button
            type="button"
            className={`primary${loading ? " loading" : ""}`}
            onClick={onConfirmNl}
            disabled={!hasNlDraft || loading}
            title={!hasNlDraft ? "Run Plan query first" : "Confirm this query and draw the map"}
          >
            {hasNlDraft ? "Confirm & map" : "Plan query first"}
          </button>
        </div>
        {!hasNlDraft && !loading ? (
          <div className="footer-attr">First plan the sentence with Gemma 4, then confirm the resolved query.</div>
        ) : null}
        {nlNotes.map((note) => (
          <div className="empty" key={note}>
            {note}
          </div>
        ))}
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
          <input
            type="text"
            value={query.taxon?.q ?? ""}
            onChange={(e) => patch({ taxon: { q: e.target.value, gbifKey: null } })}
            placeholder="Amphibia, Panthera onca…"
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
        {taxonNeeds ? <div className="warn">Multiple matches — pick the intended taxon.</div> : null}
        {taxonCandidates.length > 0 ? (
          <ul className="candidates">
            {taxonCandidates.map((c) => (
              <li key={c.gbifKey}>
                <button
                  type="button"
                  className={c.gbifKey === query.taxon?.gbifKey ? "selected" : ""}
                  onClick={() =>
                    patch({
                      taxon: {
                        q: query.taxon?.q,
                        rankHint: query.taxon?.rankHint,
                        gbifKey: c.gbifKey,
                        scientificName: c.scientificName,
                        canonicalName: c.canonicalName,
                        rank: c.rank,
                      },
                    })
                  }
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
          <input
            type="text"
            value={query.place?.q ?? ""}
            onChange={(e) => patch({ place: { q: e.target.value, iso2: null, kind: "country" } })}
            placeholder="Costa Rica"
          />
        </label>
        {placeNeeds ? <div className="warn">Pick a country match.</div> : null}
        {placeCandidates.length > 0 ? (
          <ul className="candidates">
            {placeCandidates.slice(0, 8).map((c) => (
              <li key={c.iso2}>
                <button
                  type="button"
                  className={c.iso2 === query.place?.iso2 ? "selected" : ""}
                  onClick={() => patch({ place: { q: query.place?.q, kind: "country", iso2: c.iso2, title: c.title } })}
                >
                  {c.title}
                  <small>{c.iso2}</small>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
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
              onClick={() => toggleIucn(opt.code)}
            >
              {opt.code}
            </button>
          ))}
        </div>
      </section>

      <section className="card">
        <h2>Map style</h2>
        <div className="chips">
          {(["points", "hex", "heat"] as const).map((style) => (
            <button
              key={style}
              type="button"
              className={query.map?.style === style ? "chip active" : "chip ghost"}
              onClick={() => patch({ map: { style } })}
            >
              {style}
            </button>
          ))}
        </div>
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
