import type { MapQuery } from "./types";

function bytesToBase64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

function base64UrlToBytes(raw: string): Uint8Array {
  const padded = raw.replaceAll("-", "+").replaceAll("_", "/");
  const pad = padded.length % 4 === 0 ? "" : "=".repeat(4 - (padded.length % 4));
  const binary = atob(padded + pad);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

export function encodeQuery(query: MapQuery): string {
  return bytesToBase64Url(new TextEncoder().encode(JSON.stringify(query)));
}

export function decodeQuery(raw: string): MapQuery | null {
  try {
    return JSON.parse(new TextDecoder().decode(base64UrlToBytes(raw))) as MapQuery;
  } catch {
    return null;
  }
}

export function writeQueryToUrl(query: MapQuery): void {
  try {
    const url = new URL(window.location.href);
    url.searchParams.set("q", encodeQuery(query));
    window.history.replaceState({}, "", url);
  } catch {
    // Shareable URL is best-effort; never crash the form on history/encoding errors.
  }
}

export function readQueryFromUrl(): MapQuery | null {
  const raw = new URLSearchParams(window.location.search).get("q");
  return raw ? decodeQuery(raw) : null;
}
