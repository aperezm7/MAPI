import { useEffect, useState } from "react";
import type { LegendItem, MapViewHandle, PngOptions } from "./MapView";

type Props = {
  open: boolean;
  onClose: () => void;
  map: MapViewHandle | null;
  items: LegendItem[];
};

export default function PngStudio({ open, onClose, map, items }: Props) {
  const [grid, setGrid] = useState(true);
  const [scaleBar, setScaleBar] = useState(true);
  const [compass, setCompass] = useState(true);
  const [legend, setLegend] = useState(true);
  const [included, setIncluded] = useState<Record<string, boolean>>({});
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setIncluded(Object.fromEntries(items.map((item) => [item.id, included[item.id] ?? true])));
    // Reset only when the set of legend rows changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items.map((item) => item.id).join("|")]);

  const options: PngOptions = {
    grid,
    scaleBar,
    compass,
    legend,
    legendItems: legend ? items.filter((item) => included[item.id] !== false) : [],
  };

  useEffect(() => {
    if (!open) return;
    let cancel = false;
    const frame = requestAnimationFrame(() => {
      try {
        const url = map?.exportPng(options) ?? null;
        if (!cancel) {
          setPreview(url);
          setError(url ? null : "Map is not ready to preview yet.");
        }
      } catch (err) {
        if (cancel) return;
        const message = err instanceof Error ? err.message : "PNG preview failed";
        setPreview(null);
        setError(
          /taint|security/i.test(message)
            ? "The basemap blocked a canvas preview. GeoJSON and QGIS export still work."
            : message,
        );
      }
    });
    return () => {
      cancel = true;
      cancelAnimationFrame(frame);
    };
  }, [open, map, grid, scaleBar, compass, legend, included, items]);

  if (!open) return null;

  function download() {
    if (!preview) return;
    const link = document.createElement("a");
    link.href = preview;
    link.download = "mapi-map.png";
    link.click();
  }

  return (
    <div className="studio-backdrop" role="presentation" onClick={onClose}>
      <div
        className="studio"
        role="dialog"
        aria-modal="true"
        aria-labelledby="png-studio-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="studio-preview">
          {preview ? <img src={preview} alt="Map preview with the selected decorations" /> : <div className="empty">{error ?? "Preparing preview…"}</div>}
          {error && preview ? <div className="warn">{error}</div> : null}
        </div>
        <form
          className="studio-menu"
          onSubmit={(event) => {
            event.preventDefault();
            download();
          }}
        >
          <h2 id="png-studio-title">Prepare map</h2>
          <p className="footer-attr">Turn decorations on and check the preview before downloading.</p>
          <label>
            <input type="checkbox" checked={grid} onChange={(event) => setGrid(event.target.checked)} /> Graticule
          </label>
          <label>
            <input type="checkbox" checked={scaleBar} onChange={(event) => setScaleBar(event.target.checked)} /> Scale bar
          </label>
          <label>
            <input type="checkbox" checked={compass} onChange={(event) => setCompass(event.target.checked)} /> North arrow
          </label>
          <label>
            <input type="checkbox" checked={legend} onChange={(event) => setLegend(event.target.checked)} /> Legend
          </label>
          {legend ? (
            <fieldset>
              <legend>Legend entries</legend>
              {items.length ? (
                items.map((item) => (
                  <label key={item.id}>
                    <input
                      type="checkbox"
                      checked={included[item.id] !== false}
                      onChange={(event) => setIncluded((prev) => ({ ...prev, [item.id]: event.target.checked }))}
                    />
                    <i className={item.kind === "line" ? "swatch line" : "swatch"} style={{ background: item.swatch }} />
                    <span>{item.label}</span>
                  </label>
                ))
              ) : (
                <div className="empty">Draw a map to fill the legend.</div>
              )}
            </fieldset>
          ) : null}
          <div className="actions">
            <button type="submit" className="primary" disabled={!preview}>
              Download PNG
            </button>
            <button type="button" className="secondary" onClick={onClose}>
              Close
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
