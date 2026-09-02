from __future__ import annotations

from typing import Any

import httpx

from app.models import (
    MapQuery,
    PlaceCandidate,
    PlaceQuery,
    ResolveResponse,
    TaxonCandidate,
    TaxonQuery,
)
from app.services import gbif

BACKBONE_DATASET = "d7dddbf4-2cf0-4f39-9b2a-bb099caae36c"
VERNACULAR_ALIASES = {
    "amphibians": "Amphibia",
    "amphibia": "Amphibia",
    "birds": "Aves",
    "aves": "Aves",
    "mammals": "Mammalia",
    "mammalia": "Mammalia",
    "reptiles": "Reptilia",
    "reptilia": "Reptilia",
    "insects": "Insecta",
    "plants": "Plantae",
    "plantae": "Plantae",
    "fungi": "Fungi",
    "trees": "Plantae",
    "fishes": "Actinopterygii",
    "fish": "Actinopterygii",
}

FALLBACK_COUNTRIES = [
    {"iso2": "CR", "iso3": "CRI", "title": "Costa Rica", "gbifRegion": "LATIN_AMERICA"},
    {"iso2": "US", "iso3": "USA", "title": "United States of America", "gbifRegion": "NORTH_AMERICA"},
    {"iso2": "BR", "iso3": "BRA", "title": "Brazil", "gbifRegion": "LATIN_AMERICA"},
    {"iso2": "MX", "iso3": "MEX", "title": "Mexico", "gbifRegion": "LATIN_AMERICA"},
    {"iso2": "KE", "iso3": "KEN", "title": "Kenya", "gbifRegion": "AFRICA"},
    {"iso2": "AU", "iso3": "AUS", "title": "Australia", "gbifRegion": "OCEANIA"},
    {"iso2": "IN", "iso3": "IND", "title": "India", "gbifRegion": "ASIA"},
    {"iso2": "ES", "iso3": "ESP", "title": "Spain", "gbifRegion": "EUROPE"},
]


def _taxon_from_match(match: dict[str, Any]) -> TaxonCandidate | None:
    key = match.get("usageKey") or match.get("speciesKey") or match.get("key")
    if not key:
        return None
    return TaxonCandidate(
        gbifKey=int(key),
        scientificName=match.get("scientificName"),
        canonicalName=match.get("canonicalName"),
        rank=match.get("rank"),
        status=match.get("status"),
        confidence=match.get("confidence"),
        matchType=match.get("matchType"),
        kingdom=match.get("kingdom"),
        className=match.get("class") or match.get("clazz"),
    )


def _taxon_from_suggest(item: dict[str, Any]) -> TaxonCandidate | None:
    key = item.get("key") or item.get("nubKey")
    if not key:
        return None
    return TaxonCandidate(
        gbifKey=int(key),
        scientificName=item.get("scientificName") or item.get("canonicalName"),
        canonicalName=item.get("canonicalName"),
        rank=item.get("rank"),
        status=item.get("status"),
        kingdom=item.get("kingdom"),
        className=item.get("class"),
    )


def _rank_matches(rank: str | None, hint: str | None) -> bool:
    if not hint or not rank:
        return True
    return rank.upper() == hint.upper()


def _taxon_from_search(item: dict[str, Any]) -> TaxonCandidate | None:
    key = item.get("nubKey") or item.get("key")
    if not key:
        return None
    return TaxonCandidate(
        gbifKey=int(key),
        scientificName=item.get("scientificName"),
        canonicalName=item.get("canonicalName"),
        rank=item.get("rank"),
        status=item.get("taxonomicStatus") or item.get("status"),
        kingdom=item.get("kingdom"),
        className=item.get("class"),
    )


def _search_score(item: dict[str, Any], rank_hint: str | None) -> int:
    score = 0
    if item.get("datasetKey") == BACKBONE_DATASET:
        score += 100
    rank = (item.get("rank") or "").upper()
    if rank_hint and rank == rank_hint.upper():
        score += 50
    if (item.get("taxonomicStatus") or "").upper() == "ACCEPTED":
        score += 10
    if item.get("nubKey"):
        score += 5
    return score


def _dedupe(candidates: list[TaxonCandidate]) -> list[TaxonCandidate]:
    seen: set[int] = set()
    out: list[TaxonCandidate] = []
    for item in candidates:
        if item.gbifKey in seen:
            continue
        seen.add(item.gbifKey)
        out.append(item)
    return out


async def resolve_taxon(client: httpx.AsyncClient, taxon: TaxonQuery) -> tuple[TaxonQuery | None, list[TaxonCandidate], bool, list[str]]:
    warnings: list[str] = []
    candidates: list[TaxonCandidate] = []

    if taxon.gbifKey:
        species = await gbif.get_species(client, taxon.gbifKey)
        chosen = TaxonCandidate(
            gbifKey=int(species.get("key") or taxon.gbifKey),
            scientificName=species.get("scientificName"),
            canonicalName=species.get("canonicalName"),
            rank=species.get("rank"),
            status=species.get("taxonomicStatus") or species.get("status"),
            kingdom=species.get("kingdom"),
            className=species.get("class"),
        )
        q = taxon.q or chosen.canonicalName or chosen.scientificName
        resolved = TaxonQuery(
            q=q,
            rankHint=taxon.rankHint,
            gbifKey=chosen.gbifKey,
            scientificName=chosen.scientificName,
            canonicalName=chosen.canonicalName,
            rank=chosen.rank,
        )
        return resolved, [chosen], False, warnings

    name = (taxon.q or taxon.scientificName or taxon.canonicalName or "").strip()
    if not name:
        return None, [], False, ["No taxon name or GBIF key provided."]

    original_q = name
    lookup_names = [name]
    alias = VERNACULAR_ALIASES.get(name.casefold())
    if alias and alias.casefold() != name.casefold():
        lookup_names.append(alias)

    match: dict[str, Any] = {}
    match_candidate = None
    suggestions: list[dict[str, Any]] = []
    for lookup in lookup_names:
        match = await gbif.match_species(client, lookup)
        match_candidate = _taxon_from_match(match)
        suggestions = await gbif.suggest_species(client, lookup)
        if match_candidate or suggestions:
            name = lookup
            break

    search_rows: list[dict[str, Any]] = []
    if not match_candidate and not suggestions:
        for lookup in lookup_names:
            search_rows = await gbif.search_species(
                client, lookup, rank=taxon.rankHint, vernacular=True
            )
            if not search_rows:
                search_rows = await gbif.search_species(client, lookup, rank=taxon.rankHint)
            if search_rows:
                name = lookup
                break
        search_rows.sort(key=lambda row: _search_score(row, taxon.rankHint), reverse=True)

    candidates = _dedupe(
        ([match_candidate] if match_candidate else [])
        + [c for item in suggestions if (c := _taxon_from_suggest(item))]
        + [c for item in search_rows if (c := _taxon_from_search(item))]
    )

    if taxon.rankHint:
        ranked = [c for c in candidates if _rank_matches(c.rank, taxon.rankHint)]
        if ranked:
            candidates = ranked + [c for c in candidates if c not in ranked]
        else:
            warnings.append(f"No GBIF match at rank {taxon.rankHint}; showing closest matches.")

    if not candidates:
        return None, [], True, [f"No GBIF taxon match for “{name}”."]

    chosen = candidates[0]
    confidence = match.get("confidence") or 0
    match_type = (match.get("matchType") or "").upper()
    rank_ok = bool(taxon.rankHint and chosen.rank and _rank_matches(chosen.rank, taxon.rankHint))
    needs = False
    if match_type == "EXACT" and confidence >= 90:
        needs = False
    elif rank_ok:
        needs = False
    elif confidence < 90 or match_type in {"NONE", "FUZZY", "HIGHERRANK"}:
        needs = True
    if len(candidates) > 1 and match_type != "EXACT" and not rank_ok:
        needs = True
    if taxon.rankHint and chosen.rank and not _rank_matches(chosen.rank, taxon.rankHint):
        needs = True
        warnings.append("Best match is a different rank than requested.")

    resolved = TaxonQuery(
        q=original_q,
        rankHint=taxon.rankHint,
        gbifKey=chosen.gbifKey,
        scientificName=chosen.scientificName,
        canonicalName=chosen.canonicalName,
        rank=chosen.rank,
    )
    return resolved, candidates[:12], needs, warnings


def _place_candidate(row: dict[str, Any]) -> PlaceCandidate | None:
    iso2 = row.get("iso2") or row.get("isoCode")
    title = row.get("title") or row.get("name")
    if not iso2 or not title:
        return None
    return PlaceCandidate(
        iso2=str(iso2).upper(),
        iso3=row.get("iso3"),
        title=title,
        gbifRegion=row.get("gbifRegion"),
    )


async def load_countries(client: httpx.AsyncClient) -> list[PlaceCandidate]:
    try:
        rows = await gbif.list_countries(client)
        places = [p for row in rows if (p := _place_candidate(row))]
        if places:
            return places
    except Exception:
        pass
    return [PlaceCandidate.model_validate(row) for row in FALLBACK_COUNTRIES]


def match_places(countries: list[PlaceCandidate], q: str) -> list[PlaceCandidate]:
    needle = q.strip().casefold()
    if not needle:
        return []
    exact = [
        c
        for c in countries
        if c.iso2.casefold() == needle or (c.iso3 and c.iso3.casefold() == needle) or c.title.casefold() == needle
    ]
    if exact:
        return exact
    starts = [c for c in countries if c.title.casefold().startswith(needle)]
    contains = [c for c in countries if needle in c.title.casefold() and c not in starts]
    return (starts + contains)[:12]


async def resolve_place(client: httpx.AsyncClient, place: PlaceQuery) -> tuple[PlaceQuery | None, list[PlaceCandidate], bool, list[str]]:
    warnings: list[str] = []
    countries = await load_countries(client)

    if place.iso2:
        hits = [c for c in countries if c.iso2 == place.iso2.upper()]
        if not hits:
            return None, [], True, [f"Unknown ISO country code {place.iso2}."]
        chosen = hits[0]
        resolved = PlaceQuery(
            q=place.q or chosen.title,
            kind="country",
            iso2=chosen.iso2,
            title=chosen.title,
            bbox=place.bbox,
        )
        return resolved, hits, False, warnings

    q = (place.q or place.title or "").strip()
    if not q:
        return None, countries[:20], False, []

    hits = match_places(countries, q)
    if not hits:
        return None, [], True, [f"No country match for “{q}”."]
    needs = len(hits) > 1 and hits[0].title.casefold() != q.casefold()
    chosen = hits[0]
    resolved = PlaceQuery(
        q=q,
        kind="country",
        iso2=chosen.iso2,
        title=chosen.title,
        bbox=place.bbox,
    )
    return resolved, hits, needs, warnings


async def resolve_query(client: httpx.AsyncClient, query: MapQuery) -> ResolveResponse:
    warnings: list[str] = []
    resolved = query.model_copy(deep=True)
    taxon_candidates: list[TaxonCandidate] = []
    place_candidates: list[PlaceCandidate] = []
    taxon_needs = False
    place_needs = False

    if query.taxon and (query.taxon.q or query.taxon.gbifKey or query.taxon.scientificName):
        taxon, taxon_candidates, taxon_needs, taxon_warnings = await resolve_taxon(client, query.taxon)
        warnings.extend(taxon_warnings)
        resolved.taxon = taxon
    elif query.taxon is None:
        warnings.append("Query has no taxon; the map will be unscoped and slow.")

    if query.place and (query.place.q or query.place.iso2):
        place, place_candidates, place_needs, place_warnings = await resolve_place(client, query.place)
        warnings.extend(place_warnings)
        resolved.place = place

    return ResolveResponse(
        query=resolved,
        taxonCandidates=taxon_candidates,
        placeCandidates=place_candidates,
        taxonNeedsDisambiguation=taxon_needs,
        placeNeedsDisambiguation=place_needs,
        warnings=warnings,
    )
