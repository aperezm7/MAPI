from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import get_settings
from app.models import MapQuery, NlPlanResponse, NlStatusResponse
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
  "taxon": {"q": "...", "rankHint": "class"},
  "place": {"q": "...", "kind": "country"},
  "time": {"yearMin": 2015, "yearMax": null},
  "conservation": {"iucn": ["CR","EN"]},
  "filters": {"hasCoordinate": true, "occurrenceStatus": "PRESENT"},
  "map": {"mode": "tiles_plus_sample", "sampleLimit": 300, "style": "points", "includeInat": false}
}

When you are done, call submit_mapquery with the JSON.
If you cannot call tools, reply with only that JSON object.
"""

JSON_ONLY = """Return ONLY a MapQuery JSON object. No markdown, no tools, no prose.
Use names only — omit gbifKey and iso2. Example:
{"taxon":{"q":"amphibians","rankHint":"class"},"place":{"q":"Costa Rica","kind":"country"},"time":{"yearMin":2015},"conservation":{"iucn":["CR","EN"]},"filters":{"hasCoordinate":true,"occurrenceStatus":"PRESENT"},"map":{"mode":"tiles_plus_sample","sampleLimit":300,"style":"hex"}}
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


def planner_status() -> NlStatusResponse:
    settings = get_settings()
    available = settings.llm_available()
    message = None
    if not available:
        message = "Set OPENAI_API_KEY, or switch LLM_PROVIDER=ollama for a local model."
    elif settings.provider() == "ollama":
        message = f"Local Ollama model {settings.openai_model}."
    else:
        message = f"Remote OpenAI-compatible model {settings.openai_model}."
    return NlStatusResponse(
        available=available,
        provider=settings.provider(),
        model=settings.openai_model,
        baseUrl=settings.openai_base_url,
        message=message,
    )


def extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    cleaned = re.sub(r"```(?:json)?\s*", "", cleaned)
    cleaned = cleaned.replace("```", "").strip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed.get("query") if isinstance(parsed.get("query"), dict) else parsed
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed.get("query") if isinstance(parsed.get("query"), dict) else parsed
    return None


async def _chat(
    client: httpx.AsyncClient,
    messages: list[dict[str, Any]],
    *,
    use_tools: bool,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.llm_available():
        raise LlmError("No LLM is configured. Use Ollama (LLM_PROVIDER=ollama) or set OPENAI_API_KEY.")
    await llm_limiter.acquire()
    url = settings.openai_base_url.rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": settings.openai_model,
        "messages": messages,
        "temperature": 0,
    }
    if use_tools:
        payload["tools"] = TOOLS
        payload["tool_choice"] = "auto"
    if settings.provider() == "ollama":
        payload["think"] = False
    try:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.llm_api_key()}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=180.0,
        )
    except httpx.HTTPError as exc:
        raise LlmError(f"LLM unreachable ({settings.openai_base_url}): {exc}") from exc
    if response.status_code >= 400:
        raise LlmError(f"LLM HTTP {response.status_code}: {response.text[:400]}")
    try:
        return response.json()
    except ValueError as exc:
        raise LlmError("LLM returned a non-JSON body.") from exc


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
        extracted = extract_json_object(raw or "")
        return extracted or {}


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    reasoning = message.get("reasoning") or message.get("thinking")
    return str(reasoning or "")


async def plan_nl(client: httpx.AsyncClient, prompt: str) -> NlPlanResponse:
    settings = get_settings()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": prompt},
    ]
    submitted: dict[str, Any] | None = None
    notes: list[str] = []
    use_tools = True

    for _ in range(6):
        data = await _chat(client, messages, use_tools=use_tools)
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
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
            continue

        extracted = extract_json_object(_message_text(message))
        if extracted:
            submitted = extracted
            notes.append("Parsed MapQuery from model JSON (tools unused or unavailable).")
            break

        if use_tools:
            use_tools = False
            messages.append(
                {
                    "role": "user",
                    "content": JSON_ONLY,
                }
            )
            continue
        raise LlmError("Model did not return MapQuery JSON or tool calls.")

    if submitted is None:
        raise LlmError("Model did not submit a MapQuery.")

    query = MapQuery.model_validate(submitted)
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
        provider=settings.provider(),
    )
