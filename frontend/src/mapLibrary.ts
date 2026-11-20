import { emptyQuery, type MapQuery } from "./types";
import { readQueryFromUrl } from "./urlState";

export type SavedMap = {
  id: string;
  name: string;
  query: MapQuery;
};

export type MapLibrary = {
  maps: SavedMap[];
  activeId: string;
};

const STORAGE_KEY = "mapi.builder.maps";

export function newMapId(): string {
  return crypto.randomUUID();
}

export function loadLibrary(): MapLibrary {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as MapLibrary;
      if (
        Array.isArray(parsed.maps) &&
        parsed.maps.length > 0 &&
        parsed.maps.every((map) => map.id && map.query) &&
        parsed.maps.some((map) => map.id === parsed.activeId)
      ) {
        return parsed;
      }
    }
  } catch {
    // A bad saved library should not block the builder.
  }
  const id = newMapId();
  return {
    maps: [{ id, name: "Map 1", query: readQueryFromUrl() ?? emptyQuery() }],
    activeId: id,
  };
}

export function saveLibrary(library: MapLibrary) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(library));
}

export function mapFileSlug(name: string): string {
  const slug = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  return slug || "map";
}
