import type { SavedMap } from "./mapLibrary";

type Props = {
  maps: SavedMap[];
  activeId: string;
  onOpen: (id: string) => void;
  onNew: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onRename: (name: string) => void;
};

export default function MapShelf({ maps, activeId, onOpen, onNew, onDuplicate, onDelete, onRename }: Props) {
  const active = maps.find((map) => map.id === activeId);
  return (
    <section className="card">
      <h2>Maps</h2>
      <ul className="candidates">
        {maps.map((map) => (
          <li key={map.id}>
            <button type="button" className={map.id === activeId ? "selected" : ""} onClick={() => onOpen(map.id)}>
              {map.name}
              <small>
                {[map.query.taxon?.canonicalName || map.query.taxon?.q, map.query.place?.title || map.query.place?.q]
                  .filter(Boolean)
                  .join(" · ") || "Empty query"}
              </small>
            </button>
          </li>
        ))}
      </ul>
      {active ? (
        <label className="field">
          Name
          <input type="text" value={active.name} onChange={(event) => onRename(event.target.value)} />
        </label>
      ) : null}
      <div className="actions">
        <button type="button" className="secondary" onClick={onNew}>
          New map
        </button>
        <button type="button" className="secondary" onClick={onDuplicate}>
          Duplicate
        </button>
        <button type="button" className="secondary" onClick={onDelete} disabled={maps.length < 2}>
          Delete
        </button>
      </div>
    </section>
  );
}
