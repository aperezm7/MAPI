import type { IucnStatus, InatOverlay, MapQuery, MapResponse, NlPlanResponse, PlaceCandidate, TaxonCandidate } from "./types";

async function parse<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = (body as { detail?: string }).detail || response.statusText;
    throw new Error(detail);
  }
  return body as T;
}

export async function fetchCountries(): Promise<PlaceCandidate[]> {
  const data = await parse<{ countries: PlaceCandidate[] }>(await fetch("/v1/countries"));
  return data.countries;
}

export async function suggestTaxon(q: string): Promise<{
  candidates: TaxonCandidate[];
  needsDisambiguation: boolean;
  warnings: string[];
}> {
  const response = await fetch(`/v1/taxon/suggest?q=${encodeURIComponent(q)}`);
  return parse(response);
}

export async function resolveQuery(query: MapQuery) {
  const response = await fetch("/v1/query/resolve", {
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
  const response = await fetch("/v1/map", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(query),
  });
  return parse<MapResponse>(response);
}

export async function fetchInat(query: MapQuery): Promise<InatOverlay> {
  const response = await fetch("/v1/inat/overlay", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(query),
  });
  return parse<InatOverlay>(response);
}

export async function fetchIucn(name: string): Promise<IucnStatus> {
  const response = await fetch(`/v1/species/iucn?name=${encodeURIComponent(name)}`);
  return parse<IucnStatus>(response);
}

export async function planNl(prompt: string): Promise<NlPlanResponse> {
  const response = await fetch("/v1/nl/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
  return parse<NlPlanResponse>(response);
}

export async function requestGbifDownload(query: MapQuery): Promise<{ available: boolean; message?: string; key?: string; statusUrl?: string }> {
  const response = await fetch("/v1/downloads/gbif", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, format: "SIMPLE_CSV" }),
  });
  return parse(response);
}
