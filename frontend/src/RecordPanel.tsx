import type { IucnStatus } from "./types";

type Props = {
  feature: GeoJSON.Feature | null;
  iucn: IucnStatus | null;
  onClose: () => void;
};

export default function RecordPanel({ feature, iucn, onClose }: Props) {
  if (!feature) return null;
  const p = feature.properties || {};
  const photo = typeof p.photoUrl === "string" ? p.photoUrl : null;
  const name = String(p.scientificName || p.canonicalName || "Record");
  const gbifId = p.gbifID;
  const inatId = p.source === "inaturalist" ? p.id : null;

  return (
    <article className="card record">
      <div className="row">
        <h2>Selected record</h2>
        <button className="linkish" type="button" onClick={onClose}>
          Close
        </button>
      </div>
      {photo ? <img className="popup-photo" src={photo.replace("square", "medium")} alt="" /> : null}
      <strong>{name}</strong>
      {p.commonName ? <div>{String(p.commonName)}</div> : null}
      <dl>
        {p.eventDate || p.observedOn ? (
          <>
            <dt>Date</dt>
            <dd>{String(p.eventDate || p.observedOn)}</dd>
          </>
        ) : null}
        {p.country ? (
          <>
            <dt>Country</dt>
            <dd>{String(p.country)}</dd>
          </>
        ) : null}
        {p.basisOfRecord ? (
          <>
            <dt>Basis</dt>
            <dd>{String(p.basisOfRecord)}</dd>
          </>
        ) : null}
        {p.iucnRedListCategory ? (
          <>
            <dt>GBIF IUCN field</dt>
            <dd>{String(p.iucnRedListCategory)}</dd>
          </>
        ) : null}
        {p.license ? (
          <>
            <dt>License</dt>
            <dd>{String(p.license)}</dd>
          </>
        ) : null}
      </dl>
      {typeof gbifId === "number" || typeof gbifId === "string" ? (
        <a href={`https://www.gbif.org/occurrence/${gbifId}`} target="_blank" rel="noreferrer">
          Open on GBIF
        </a>
      ) : null}
      {inatId ? (
        <a href={String(p.uri || `https://www.inaturalist.org/observations/${inatId}`)} target="_blank" rel="noreferrer">
          Open on iNaturalist
        </a>
      ) : null}
      {iucn ? (
        <div className={iucn.available && iucn.category ? "ok" : "empty"}>
          {iucn.category ? (
            <div>
              IUCN: {iucn.category}
              {iucn.categoryLabel ? ` — ${iucn.categoryLabel}` : ""}
            </div>
          ) : (
            <div>{iucn.message || "IUCN status unavailable"}</div>
          )}
          {iucn.citation ? <div className="footer-attr">{iucn.citation}</div> : null}
          {iucn.url ? (
            <a href={iucn.url} target="_blank" rel="noreferrer">
              Red List page
            </a>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}
