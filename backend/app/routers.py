from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from app.config import get_settings
from app.accounts import (
    clear_gbif,
    create_client,
    list_clients,
    recent_queries,
    require_admin,
    resolve_request,
    set_gbif,
    update_client,
)
from app.models import (
    ClientCreate,
    ClientUpdate,
    DownloadRequest,
    GbifConnect,
    IucnStatusResponse,
    MapQuery,
    NlPlanRequest,
    NlStatusResponse,
)
from app.services import downloads, inat, iucn, llm
from app.usage import admit, prices, settle, summarize_query
from app.services.mapping import compile_map
from app.services.qgis_export import build_qgis_zip, package_slug
from app.services.resolve import autocomplete_taxa, load_countries, resolve_place, resolve_query, resolve_taxon, suggest_places
from app.models import PlaceQuery, TaxonQuery

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "mapi"}


@router.get("/v1/account/status")
async def account_status() -> dict:
    settings = get_settings()
    return {
        "authRequired": settings.auth_required,
        "currency": "credits",
        "prices": prices(),
        "defaultBudget": settings.default_budget,
        "mapsPerDay": settings.quota_maps_per_day,
        "plansPerDay": settings.quota_plans_per_day,
        "requestsPerMinute": settings.quota_requests_per_minute,
    }


@router.get("/v1/account")
async def account_me(request: Request) -> dict:
    client = resolve_request(request)
    return client.public()


@router.get("/v1/account/queries")
async def account_queries(request: Request, limit: int = Query(default=30, ge=1, le=100)) -> dict:
    client = resolve_request(request)
    return {"queries": recent_queries(client.id, limit)}


@router.put("/v1/account/gbif")
async def account_gbif_connect(request: Request, body: GbifConnect) -> dict:
    actor = resolve_request(request)
    if actor.unlimited:
        raise HTTPException(status_code=409, detail="Create a client API key before connecting a GBIF account.")
    http = request.app.state.http
    settings = get_settings()
    try:
        response = await http.get(
            f"{settings.gbif_base_url}/v1/user/login",
            auth=(body.username, body.password),
            headers={"User-Agent": settings.gbif_user_agent},
            timeout=20.0,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GBIF login unreachable: {exc}") from exc
    if response.status_code in (401, 403):
        raise HTTPException(status_code=401, detail="GBIF rejected that username or password.")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"GBIF login failed ({response.status_code}).")
    return set_gbif(actor.id, body.username, body.password, body.email).public()


@router.delete("/v1/account/gbif")
async def account_gbif_disconnect(request: Request) -> dict:
    actor = resolve_request(request)
    if actor.unlimited:
        raise HTTPException(status_code=409, detail="Open access has no GBIF account to remove.")
    updated = clear_gbif(actor.id)
    return updated.public() if updated else {}


@router.post("/v1/clients")
async def clients_create(request: Request, body: ClientCreate) -> dict:
    require_admin(request)
    client, api_key = create_client(
        body.name,
        budget=body.budget,
        maps_per_day=body.mapsPerDay,
        plans_per_day=body.plansPerDay,
        requests_per_minute=body.requestsPerMinute,
    )
    return {**client.public(), "apiKey": api_key}


@router.get("/v1/clients")
async def clients_list(request: Request) -> dict:
    require_admin(request)
    return {"clients": [client.public() for client in list_clients()]}


@router.patch("/v1/clients/{client_id}")
async def clients_update(request: Request, client_id: str, body: ClientUpdate) -> dict:
    require_admin(request)
    fields = {}
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        fields["name"] = data["name"]
    if "active" in data:
        fields["active"] = data["active"]
    if "budget" in data:
        fields["budget"] = data["budget"]
    if "mapsPerDay" in data:
        fields["maps_per_day"] = data["mapsPerDay"]
    if "plansPerDay" in data:
        fields["plans_per_day"] = data["plansPerDay"]
    if "requestsPerMinute" in data:
        fields["requests_per_minute"] = data["requestsPerMinute"]
    updated = update_client(client_id, fields)
    if updated is None:
        raise HTTPException(status_code=404, detail="No client with that id.")
    return updated.public()


@router.get("/v1/countries")
async def countries(request: Request) -> dict:
    resolve_request(request)
    client = request.app.state.http
    places = await load_countries(client)
    return {"countries": [p.model_dump() for p in places]}


@router.get("/v1/taxon/suggest")
async def taxon_suggest(
    request: Request, q: str, limit: int = 12, rankHint: str | None = None
) -> dict:
    resolve_request(request)
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


@router.get("/v1/taxon/autocomplete")
async def taxon_autocomplete(
    request: Request,
    q: str = Query(min_length=1, max_length=200),
    rankHint: str | None = None,
    limit: int = Query(default=8, ge=1, le=20),
) -> dict:
    resolve_request(request)
    client = request.app.state.http
    candidates = await autocomplete_taxa(client, q, rank_hint=rankHint, limit=limit)
    return {"candidates": [c.model_dump(by_alias=True) for c in candidates]}


@router.get("/v1/place/suggest")
async def place_suggest(request: Request, q: str = Query(min_length=1, max_length=200)) -> dict:
    resolve_request(request)
    client = request.app.state.http
    place, _, needs, warnings = await resolve_place(client, PlaceQuery(q=q.strip()))
    candidates = suggest_places(await load_countries(client), q)
    return {
        "query": place.model_dump() if place else None,
        "candidates": [c.model_dump() for c in candidates],
        "needsDisambiguation": needs,
        "warnings": warnings,
    }


@router.post("/v1/query/resolve")
async def query_resolve(request: Request, query: MapQuery):
    actor = await admit(request, "resolve")
    client = request.app.state.http
    try:
        resolved = await resolve_query(client, query)
    except Exception:
        settle(actor, "resolve", summarize_query(query), query.model_dump(), False)
        raise
    settle(actor, "resolve", summarize_query(query), query.model_dump(), True)
    return resolved


@router.post("/v1/map")
async def build_map(request: Request, query: MapQuery):
    actor = await admit(request, "map")
    client = request.app.state.http
    try:
        resolved = await resolve_query(client, query)
        if resolved.taxonNeedsDisambiguation and (not query.taxon or not query.taxon.gbifKey):
            mapped = {
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
        else:
            compiled = await compile_map(client, resolved.query)
            mapped = {
                **compiled.model_dump(),
                "taxonCandidates": [c.model_dump(by_alias=True) for c in resolved.taxonCandidates],
                "placeCandidates": [c.model_dump() for c in resolved.placeCandidates],
                "taxonNeedsDisambiguation": resolved.taxonNeedsDisambiguation,
                "placeNeedsDisambiguation": resolved.placeNeedsDisambiguation,
                "blocked": False,
            }
    except Exception:
        settle(actor, "map", summarize_query(query), query.model_dump(), False)
        raise
    settle(actor, "map", summarize_query(query), query.model_dump(), True)
    return mapped


@router.post("/v1/inat/overlay")
async def inat_layer(request: Request, query: MapQuery):
    actor = await admit(request, "inat")
    client = request.app.state.http
    resolved = await resolve_query(client, query)
    try:
        overlay = await inat.inat_overlay(client, resolved.query)
    except inat.InatError as exc:
        settle(actor, "inat", summarize_query(query), query.model_dump(), False)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception:
        settle(actor, "inat", summarize_query(query), query.model_dump(), False)
        raise
    settle(actor, "inat", summarize_query(query), query.model_dump(), True)
    return overlay


@router.get("/v1/species/iucn")
async def species_iucn(request: Request, name: str) -> IucnStatusResponse:
    resolve_request(request)
    client = request.app.state.http
    return await iucn.iucn_status(client, name)


@router.get("/v1/nl/status", response_model=NlStatusResponse)
async def nl_status(request: Request) -> NlStatusResponse:
    resolve_request(request)
    return await llm.planner_status(request.app.state.http)


@router.post("/v1/nl/plan")
async def nl_plan(request: Request, body: NlPlanRequest):
    actor = await admit(request, "plan")
    client = request.app.state.http
    try:
        planned = await llm.plan_nl(client, body.prompt)
    except llm.LlmError as exc:
        settle(actor, "plan", body.prompt, {"prompt": body.prompt}, False)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception:
        settle(actor, "plan", body.prompt, {"prompt": body.prompt}, False)
        raise
    settle(actor, "plan", body.prompt, {"prompt": body.prompt}, True)
    return planned


@router.post("/v1/downloads/gbif")
async def gbif_download(request: Request, body: DownloadRequest):
    actor = await admit(request, "download")
    client = request.app.state.http
    try:
        resolved = await resolve_query(client, body.query)
        gbif_account = (
            {
                "username": actor.gbif_username,
                "password": actor.gbif_password,
                "email": actor.gbif_email,
            }
            if actor.gbif_password
            else {}
        )
        result = await downloads.create_download(
            client,
            DownloadRequest(query=resolved.query, format=body.format),
            **gbif_account,
        )
    except Exception:
        settle(actor, "download", summarize_query(body.query), body.query.model_dump(), False)
        raise
    settle(actor, "download", summarize_query(body.query), body.query.model_dump(), result.available)
    return result


@router.post("/v1/export/qgis")
async def export_qgis(request: Request, query: MapQuery):
    actor = await admit(request, "export")
    client = request.app.state.http
    try:
        resolved = await resolve_query(client, query)
        if resolved.taxonNeedsDisambiguation and (not query.taxon or not query.taxon.gbifKey):
            raise HTTPException(status_code=409, detail="Pick a taxon match before exporting.")
        mapped = await compile_map(client, resolved.query)
        payload = build_qgis_zip(mapped)
    except HTTPException:
        settle(actor, "export", summarize_query(query), query.model_dump(), False)
        raise
    except Exception:
        settle(actor, "export", summarize_query(query), query.model_dump(), False)
        raise
    settle(actor, "export", summarize_query(query), query.model_dump(), True)
    filename = f"mapi-{package_slug(mapped.query)}.zip"
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
