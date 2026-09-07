from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.models import (
    DownloadRequest,
    IucnStatusResponse,
    MapQuery,
    NlPlanRequest,
    NlStatusResponse,
)
from app.services import downloads, inat, iucn, llm
from app.services.mapping import compile_map
from app.services.qgis_export import build_qgis_zip, package_slug
from app.services.resolve import load_countries, resolve_query, resolve_taxon
from app.models import TaxonQuery

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "mapi"}


@router.get("/v1/countries")
async def countries(request: Request) -> dict:
    client = request.app.state.http
    places = await load_countries(client)
    return {"countries": [p.model_dump() for p in places]}


@router.get("/v1/taxon/suggest")
async def taxon_suggest(
    request: Request, q: str, limit: int = 12, rankHint: str | None = None
) -> dict:
    client = request.app.state.http
    if not q.strip():
        return {"candidates": []}
    taxon, candidates, needs, warnings = await resolve_taxon(
        client, TaxonQuery(q=q.strip(), rankHint=rankHint)
    )
    return {
        "query": taxon.model_dump() if taxon else None,
        "candidates": [c.model_dump(by_alias=True) for c in candidates[:limit]],
        "needsDisambiguation": needs,
        "warnings": warnings,
    }


@router.post("/v1/query/resolve")
async def query_resolve(request: Request, query: MapQuery):
    client = request.app.state.http
    return await resolve_query(client, query)


@router.post("/v1/map")
async def build_map(request: Request, query: MapQuery):
    client = request.app.state.http
    resolved = await resolve_query(client, query)
    if resolved.taxonNeedsDisambiguation and (not query.taxon or not query.taxon.gbifKey):
        return {
            **resolved.model_dump(by_alias=True),
            "count": 0,
            "sample": {"type": "FeatureCollection", "features": []},
            "tile": None,
            "histogram": [],
            "attribution": ["Occurrence data © GBIF contributors. https://www.gbif.org"],
            "mode": query.map.mode,
            "style": query.map.style,
            "blocked": True,
        }
    mapped = await compile_map(client, resolved.query)
    return {
        **mapped.model_dump(),
        "taxonCandidates": [c.model_dump(by_alias=True) for c in resolved.taxonCandidates],
        "placeCandidates": [c.model_dump() for c in resolved.placeCandidates],
        "taxonNeedsDisambiguation": resolved.taxonNeedsDisambiguation,
        "placeNeedsDisambiguation": resolved.placeNeedsDisambiguation,
        "blocked": False,
    }


@router.post("/v1/inat/overlay")
async def inat_layer(request: Request, query: MapQuery):
    client = request.app.state.http
    resolved = await resolve_query(client, query)
    try:
        overlay = await inat.inat_overlay(client, resolved.query)
    except inat.InatError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return overlay


@router.get("/v1/species/iucn")
async def species_iucn(request: Request, name: str) -> IucnStatusResponse:
    client = request.app.state.http
    return await iucn.iucn_status(client, name)


@router.get("/v1/nl/status", response_model=NlStatusResponse)
async def nl_status() -> NlStatusResponse:
    return llm.planner_status()


@router.post("/v1/nl/plan")
async def nl_plan(request: Request, body: NlPlanRequest):
    client = request.app.state.http
    try:
        return await llm.plan_nl(client, body.prompt)
    except llm.LlmError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/v1/downloads/gbif")
async def gbif_download(request: Request, body: DownloadRequest):
    client = request.app.state.http
    resolved = await resolve_query(client, body.query)
    return await downloads.create_download(
        client, DownloadRequest(query=resolved.query, format=body.format)
    )


@router.post("/v1/export/qgis")
async def export_qgis(request: Request, query: MapQuery):
    client = request.app.state.http
    resolved = await resolve_query(client, query)
    if resolved.taxonNeedsDisambiguation and (not query.taxon or not query.taxon.gbifKey):
        raise HTTPException(status_code=409, detail="Pick a taxon match before exporting.")
    mapped = await compile_map(client, resolved.query)
    payload = build_qgis_zip(mapped)
    filename = f"mapi-{package_slug(mapped.query)}.zip"
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
