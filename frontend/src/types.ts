export type IucnCode = "EX" | "EW" | "CR" | "EN" | "VU" | "NT" | "LC" | "DD" | "NE";
export type MapMode = "tiles_plus_sample" | "points" | "tiles";
export type MapStyle = "points" | "hex" | "heat";

export interface TaxonQuery {
  q?: string | null;
  rankHint?: string | null;
  gbifKey?: number | null;
  scientificName?: string | null;
  canonicalName?: string | null;
  rank?: string | null;
}

export interface PlaceQuery {
  q?: string | null;
  kind?: "country" | "bbox" | "gadm";
  iso2?: string | null;
  title?: string | null;
  bbox?: number[] | null;
}

export interface MapQuery {
  taxon?: TaxonQuery | null;
  place?: PlaceQuery | null;
  time?: { yearMin?: number | null; yearMax?: number | null } | null;
  conservation?: { iucn?: IucnCode[] } | null;
  filters?: {
    hasCoordinate?: boolean;
    occurrenceStatus?: string;
    basisOfRecord?: string[] | null;
  };
  map?: {
    mode?: MapMode;
    sampleLimit?: number;
    style?: MapStyle;
    includeInat?: boolean;
  };
}

export interface TaxonCandidate {
  gbifKey: number;
  scientificName?: string | null;
  canonicalName?: string | null;
  rank?: string | null;
  status?: string | null;
  confidence?: number | null;
  matchType?: string | null;
  kingdom?: string | null;
  class?: string | null;
}

export interface PlaceCandidate {
  iso2: string;
  iso3?: string | null;
  title: string;
  gbifRegion?: string | null;
}

export interface YearCount {
  year: number;
  count: number;
}

export interface TileSpec {
  urlTemplate: string;
  tileSize: number;
  source: "density" | "adhoc";
  attribution: string;
}

export interface MapResponse {
  query: MapQuery;
  count: number;
  tile: TileSpec | null;
  sample: GeoJSON.FeatureCollection;
  sampleTruncated: boolean;
  sampleOmittedSensitive: number;
  histogram: YearCount[];
  attribution: string[];
  warnings: string[];
  mode: MapMode;
  style: MapStyle;
  taxonCandidates?: TaxonCandidate[];
  placeCandidates?: PlaceCandidate[];
  taxonNeedsDisambiguation?: boolean;
  placeNeedsDisambiguation?: boolean;
  blocked?: boolean;
}

export interface InatOverlay {
  type: "FeatureCollection";
  features: GeoJSON.Feature[];
  attribution: string[];
  count: number;
  sampleTruncated: boolean;
}

export interface IucnStatus {
  available: boolean;
  taxonName?: string | null;
  category?: string | null;
  categoryLabel?: string | null;
  assessmentId?: number | null;
  citation?: string | null;
  url?: string | null;
  message?: string | null;
}

export interface NlPlanResponse {
  query: MapQuery;
  resolve: {
    query: MapQuery;
    taxonCandidates: TaxonCandidate[];
    placeCandidates: PlaceCandidate[];
    taxonNeedsDisambiguation: boolean;
    placeNeedsDisambiguation: boolean;
    warnings: string[];
  };
  notes: string[];
  model?: string | null;
}

export const IUCN_OPTIONS: { code: IucnCode; label: string }[] = [
  { code: "CR", label: "Critically endangered" },
  { code: "EN", label: "Endangered" },
  { code: "VU", label: "Vulnerable" },
  { code: "NT", label: "Near threatened" },
  { code: "LC", label: "Least concern" },
  { code: "DD", label: "Data deficient" },
];

export const NORTHSTAR: MapQuery = {
  taxon: { q: "amphibians", rankHint: "class" },
  place: { q: "Costa Rica", kind: "country" },
  time: { yearMin: 2015, yearMax: null },
  conservation: { iucn: ["CR", "EN"] },
  filters: { hasCoordinate: true, occurrenceStatus: "PRESENT" },
  map: { mode: "tiles_plus_sample", sampleLimit: 300, style: "hex", includeInat: false },
};

export const JAGUAR_PRESET: MapQuery = {
  taxon: { q: "Panthera onca" },
  place: { q: "Costa Rica", kind: "country" },
  time: { yearMin: 2015, yearMax: null },
  conservation: { iucn: [] },
  filters: { hasCoordinate: true, occurrenceStatus: "PRESENT" },
  map: { mode: "tiles_plus_sample", sampleLimit: 300, style: "points", includeInat: false },
};

export function emptyQuery(): MapQuery {
  return {
    taxon: { q: "" },
    place: { q: "", kind: "country" },
    time: { yearMin: 2015, yearMax: null },
    conservation: { iucn: [] },
    filters: { hasCoordinate: true, occurrenceStatus: "PRESENT" },
    map: { mode: "tiles_plus_sample", sampleLimit: 300, style: "points", includeInat: false },
  };
}
