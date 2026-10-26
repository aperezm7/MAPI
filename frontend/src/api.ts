import type { IucnStatus, InatOverlay, MapQuery, MapResponse, NlPlanResponse, NlStatus, PlaceCandidate, PlaceQuery, TaxonCandidate } from "./types";

function errorMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) {
          const loc = Array.isArray((item as { loc?: unknown }).loc)
            ? (item as { loc: unknown[] }).loc.filter((part) => part !== "body").join(".")
            : "";
          const msg = String((item as { msg: unknown }).msg);
          return loc ? `${loc}: ${msg}` : msg;
        }
        return "";
      })
      .filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  return fallback;
}

const API_KEY_STORAGE = "mapi.apiKey";

export function getApiKey(): string {
  try {
    return localStorage.getItem(API_KEY_STORAGE) || "";
  } catch {
    return "";
  }
}

export function setApiKey(value: string) {
  const key = value.trim();
  if (key) localStorage.setItem(API_KEY_STORAGE, key);
  else localStorage.removeItem(API_KEY_STORAGE);
  window.dispatchEvent(new Event("mapi-account"));
}

export async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const key = getApiKey();
  if (key && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${key}`);
  const response = await fetch(input, { ...init, headers });
  if (response.ok && /\/v1\/(map|nl\/plan|query\/resolve|downloads|export|inat)/.test(input)) {
    window.dispatchEvent(new Event("mapi-usage"));
  }
  return response;
}

export interface AccountStatus {
  authRequired: boolean;
  currency: string;
  prices: Record<string, number>;
  defaultBudget: number;
  mapsPerDay: number;
  plansPerDay: number;
  requestsPerMinute: number;
}

export interface Account {
  id: string;
  name: string;
  unlimited: boolean;
  budget: number | null;
  spent: number;
  month: string;
  mapsPerDay: number | null;
  plansPerDay: number | null;
  requestsPerMinute: number | null;
  keyPrefix: string | null;
  gbif: { connected: boolean; username: string | null; email: string | null };
}

export interface StoredQuery {
  id: string;
  kind: string;
  summary: string;
  cost: number;
  status: string;
  createdAt: string;
}

export async function fetchAccountStatus(): Promise<AccountStatus> {
  return parse(await apiFetch("/v1/account/status"));
}

export async function fetchAccount(): Promise<Account> {
  return parse(await apiFetch("/v1/account"));
}

export async function fetchAccountQueries(): Promise<StoredQuery[]> {
  const data = await parse<{ queries: StoredQuery[] }>(await apiFetch("/v1/account/queries"));
  return data.queries;
}

export async function connectGbif(username: string, password: string, email: string): Promise<Account> {
  return parse(
    await apiFetch("/v1/account/gbif", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password, email: email || null }),
    }),
  );
}

export async function disconnectGbif(): Promise<Account> {
  return parse(await apiFetch("/v1/account/gbif", { method: "DELETE" }));
}

async function parse<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(errorMessage(body, response.statusText));
  }
  return body as T;
}

export async function fetchCountries(): Promise<PlaceCandidate[]> {
  const data = await parse<{ countries: PlaceCandidate[] }>(await apiFetch("/v1/countries"));
  return data.countries;
}

export async function suggestTaxon(
  q: string,
  rankHint?: string | null,
): Promise<{
  candidates: TaxonCandidate[];
  needsDisambiguation: boolean;
  warnings: string[];
}> {
  const params = new URLSearchParams({ q });
  if (rankHint) params.set("rankHint", rankHint);
  const response = await apiFetch(`/v1/taxon/suggest?${params}`);
  return parse(response);
}

export async function autocompleteTaxon(q: string, rankHint?: string | null, signal?: AbortSignal): Promise<TaxonCandidate[]> {
  const params = new URLSearchParams({ q });
  if (rankHint) params.set("rankHint", rankHint);
  const data = await parse<{ candidates: TaxonCandidate[] }>(await apiFetch(`/v1/taxon/autocomplete?${params}`, { signal }));
  return data.candidates;
}

export async function suggestPlace(
  q: string,
  signal?: AbortSignal,
): Promise<{
  query: PlaceQuery | null;
  candidates: PlaceCandidate[];
  needsDisambiguation: boolean;
  warnings: string[];
}> {
  const response = await apiFetch(`/v1/place/suggest?${new URLSearchParams({ q })}`, { signal });
  return parse(response);
}

export async function resolveQuery(query: MapQuery) {
  const response = await apiFetch("/v1/query/resolve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(query),
  });
  return parse<{
    query: MapQuery;
    taxonCandidates: TaxonCandidate[];
    placeCandidates: PlaceCandidate[];
    taxonNeedsDisambiguation: boolean;
    placeNeedsDisambiguation: boolean;
    warnings: string[];
  }>(response);
}

export async function fetchMap(query: MapQuery): Promise<MapResponse> {
  const response = await apiFetch("/v1/map", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(query),
  });
  return parse<MapResponse>(response);
}

export async function fetchInat(query: MapQuery): Promise<InatOverlay> {
  const response = await apiFetch("/v1/inat/overlay", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(query),
  });
  return parse<InatOverlay>(response);
}

export async function fetchIucn(name: string): Promise<IucnStatus> {
  const response = await apiFetch(`/v1/species/iucn?name=${encodeURIComponent(name)}`);
  return parse<IucnStatus>(response);
}

export async function fetchNlStatus(): Promise<NlStatus> {
  const response = await apiFetch("/v1/nl/status");
  return parse<NlStatus>(response);
}

export async function planNl(prompt: string): Promise<NlPlanResponse> {
  const response = await apiFetch("/v1/nl/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
  return parse<NlPlanResponse>(response);
}

export async function requestGbifDownload(query: MapQuery): Promise<{ available: boolean; message?: string; key?: string; statusUrl?: string }> {
  const response = await apiFetch("/v1/downloads/gbif", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, format: "SIMPLE_CSV" }),
  });
  return parse(response);
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export async function downloadQgisPackage(query: MapQuery): Promise<void> {
  const response = await apiFetch("/v1/export/qgis", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(query),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(errorMessage(body, response.statusText));
  }
  const blob = await response.blob();
  const header = response.headers.get("Content-Disposition") || "";
  const match = header.match(/filename="([^"]+)"/);
  triggerDownload(blob, match?.[1] || "mapi-qgis.zip");
}

export { triggerDownload };
