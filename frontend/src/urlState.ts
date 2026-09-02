import type { MapQuery } from "./types";

export function encodeQuery(query: MapQuery): string {
  const json = JSON.stringify(query);
  return btoa(json).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

export function decodeQuery(raw: string): MapQuery | null {
  try {
    const padded = raw.replaceAll("-", "+").replaceAll("_", "/");
    const pad = padded.length % 4 === 0 ? "" : "=".repeat(4 - (padded.length % 4));
    return JSON.parse(atob(padded + pad)) as MapQuery;
  } catch {
    return null;
  }
}

export function writeQueryToUrl(query: MapQuery): void {
  const url = new URL(window.location.href);
  url.searchParams.set("q", encodeQuery(query));
  window.history.replaceState({}, "", url);
}

export function readQueryFromUrl(): MapQuery | null {
  const raw = new URLSearchParams(window.location.search).get("q");
  return raw ? decodeQuery(raw) : null;
}
