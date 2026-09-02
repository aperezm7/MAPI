from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import get_settings
from app.models import MapQuery, NlPlanResponse, ResolveResponse
from app.rate_limit import llm_limiter
from app.services.resolve import resolve_query

SYSTEM = """You are MAPI's query planner for species occurrence maps.
You NEVER invent coordinates, GBIF taxon keys, or ISO country codes.
You convert a natural-language request into a MapQuery JSON object.

Allowed IUCN codes: EX, EW, CR, EN, VU, NT, LC, DD, NE.
"endangered" means CR and EN. "threatened" means CR, EN, VU.

Use tools to resolve taxon names and place names to canonical IDs.
Do not guess taxon.gbifKey or place.iso2 — call tools.

Final MapQuery shape:
{
  "taxon": {"q": "...", "rankHint": "class"|null, "gbifKey": 123},
  "place": {"q": "...", "kind": "country", "iso2": "CR"},
  "time": {"yearMin": 2015, "yearMax": null},
  "conservation": {"iucn": ["CR","EN"]},
  "filters": {"hasCoordinate": true, "occurrenceStatus": "PRESENT"},
  "map": {"mode": "tiles_plus_sample", "sampleLimit": 900, "style": "points", "includeInat": false}
}

When you are done, call submit_mapquery with the JSON.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "resolve_taxon",
            "description": "Match a vernacular or scientific name to GBIF backbone candidates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {"type": "string"},
                    "rankHint": {"type": "string", "description": "kingdom, phylum, class, order, family, genus, species"},
                },
                "required": ["q"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_place",
            "description": "Match a place name to an ISO country.",
            "parameters": {
                "type": "object",
                "properties": {"q": {"type": "string"}},
                "required": ["q"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_mapquery",
            "description": "Submit the finished MapQuery. gbifKey and iso2 must come from tools.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "object"},
                    "notes": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["query"],
            },
        },
    },
]


class LlmError(RuntimeError):
    pass


async def _chat(client: httpx.AsyncClient, messages: list[dict[str, Any]]) -> dict[str, Any]:
    settings = get_settings()
    if not settings.openai_api_key:
        raise LlmError("OPENAI_API_KEY is not configured.")
    await llm_limiter.acquire()
    url = settings.openai_base_url.rstrip("/") + "/chat/completions"
    response = await client.post(
        url,
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.openai_model,
            "messages": messages,
            "tools": TOOLS,
            "tool_choice": "auto",
            "temperature": 0,
        },
        timeout=90.0,
    )
    if response.status_code >= 400:
        raise LlmError(f"LLM HTTP {response.status_code}: {response.text[:400]}")
    return response.json()


async def _run_tool(client: httpx.AsyncClient, name: str, arguments: dict[str, Any]) -> Any:
    if name == "resolve_taxon":
        query = MapQuery.model_validate({"taxon": {"q": arguments.get("q"), "rankHint": arguments.get("rankHint")}})
        resolved = await resolve_query(client, query)
        return {
            "selected": resolved.query.taxon.model_dump() if resolved.query.taxon else None,
            "candidates": [c.model_dump(by_alias=True) for c in resolved.taxonCandidates[:8]],
            "needsDisambiguation": resolved.taxonNeedsDisambiguation,
            "warnings": resolved.warnings,
        }
    if name == "resolve_place":
        query = MapQuery.model_validate({"place": {"q": arguments.get("q")}})
        resolved = await resolve_query(client, query)
        return {
            "selected": resolved.query.place.model_dump() if resolved.query.place else None,
            "candidates": [c.model_dump() for c in resolved.placeCandidates[:8]],
            "needsDisambiguation": resolved.placeNeedsDisambiguation,
            "warnings": resolved.warnings,
        }
    if name == "submit_mapquery":
        return {"ok": True, "query": arguments.get("query"), "notes": arguments.get("notes") or []}
    return {"error": f"unknown tool {name}"}


def _parse_arguments(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}


async def plan_nl(client: httpx.AsyncClient, prompt: str) -> NlPlanResponse:
    settings = get_settings()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": prompt},
    ]
    submitted: dict[str, Any] | None = None
    notes: list[str] = []

    for _ in range(6):
        data = await _chat(client, messages)
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            content = message.get("content") or ""
            try:
                parsed = json.loads(content)
                submitted = parsed.get("query") or parsed
            except json.JSONDecodeError as exc:
                raise LlmError("Model did not return MapQuery JSON or tool calls.") from exc
            break

        messages.append(message)
        for call in tool_calls:
            fn = call.get("function") or {}
            name = fn.get("name")
            args = _parse_arguments(fn.get("arguments"))
            result = await _run_tool(client, name, args)
            if name == "submit_mapquery":
                submitted = result.get("query")
                notes = result.get("notes") or []
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "content": json.dumps(result),
                }
            )
        if submitted is not None:
            break

    if submitted is None:
        raise LlmError("Model did not submit a MapQuery.")

    query = MapQuery.model_validate(submitted)
    # Re-resolve names so the model cannot invent taxon keys or ISO codes.
    if query.taxon:
        query.taxon.gbifKey = None
    if query.place and query.place.q:
        query.place.iso2 = None
    resolved = await resolve_query(client, query)
    return NlPlanResponse(
        query=resolved.query,
        resolve=resolved,
        notes=notes,
        model=settings.openai_model,
    )
