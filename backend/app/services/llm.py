from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import LlmConfig, get_settings
from app.models import MapQuery, NlPlanResponse, NlStatusResponse
from app.rate_limit import llm_limiter
from app.services.resolve import resolve_query

SYSTEM = """You are MAPI's query planner for species occurrence maps.
Convert the user's request into a JSON object with this exact shape:

{"query": MapQuery, "notes": [short strings explaining assumptions]}

MapQuery fields (omit any field the user did not ask for):
- taxon: {"q": taxon name as written or its scientific name, "rankHint": one of kingdom|phylum|class|order|family|genus|species}
- place: {"q": country name, "kind": "country"}
- time: {"yearMin": integer or null, "yearMax": integer or null}
- conservation: {"iucn": list of IUCN codes}
- filters: {"hasCoordinate": true, "occurrenceStatus": "PRESENT"}
- map: {"mode": "tiles_plus_sample", "sampleLimit": 300, "style": one of points|hex|heat, "includeInat": boolean}

Rules:
- Use names only. NEVER output gbifKey, iso2, coordinates, or bbox; MAPI resolves names itself.
- Allowed IUCN codes: EX, EW, CR, EN, VU, NT, LC, DD, NE.
  "endangered" means ["CR","EN"]; "threatened" means ["CR","EN","VU"]; "critically endangered" means ["CR"].
- "since 2015" means yearMin 2015; "before 2000" means yearMax 1999; "in 2020" means yearMin and yearMax 2020.
- Use style "hex" for hexagons/grid/bins, "heat" for heatmap/density, otherwise "points".
- Set includeInat true only if the user mentions iNaturalist or citizen-science photos.
- Reply with the JSON object only.

Example request: show endangered amphibians in Costa Rica since 2015 as hexagons
Example reply: {"query":{"taxon":{"q":"Amphibia","rankHint":"class"},"place":{"q":"Costa Rica","kind":"country"},"time":{"yearMin":2015,"yearMax":null},"conservation":{"iucn":["CR","EN"]},"filters":{"hasCoordinate":true,"occurrenceStatus":"PRESENT"},"map":{"mode":"tiles_plus_sample","sampleLimit":300,"style":"hex","includeInat":false}},"notes":["Endangered interpreted as IUCN CR and EN."]}
"""

_REASONING_MODEL = re.compile(r"^(gpt-5|o\d)", re.IGNORECASE)


class LlmError(RuntimeError):
    pass


def _ollama_root(base_url: str) -> str:
    return re.sub(r"/v1/?$", "", base_url.rstrip("/"))


def _ollama_has_model(names: list[str], model: str) -> bool:
    wanted = model if ":" in model else f"{model}:latest"
    return any(name == model or name == wanted or (":" not in model and name.startswith(f"{model}:")) for name in names)


async def planner_status(client: httpx.AsyncClient) -> NlStatusResponse:
    cfg = get_settings().llm()
    status = {"provider": cfg.provider, "model": cfg.model, "baseUrl": cfg.base_url}
    if not cfg.configured:
        return NlStatusResponse(available=False, message=cfg.problem, **status)
    if not cfg.is_local:
        return NlStatusResponse(available=True, message=f"Hosted {cfg.provider} model {cfg.model}.", **status)

    root = _ollama_root(cfg.base_url)
    try:
        response = await client.get(f"{root}/api/tags", timeout=1.5)
        response.raise_for_status()
        names = [str(item.get("name") or item.get("model") or "") for item in response.json().get("models") or []]
    except (httpx.HTTPError, ValueError, AttributeError):
        return NlStatusResponse(
            available=False,
            message=(
                f"Ollama is not reachable at {root}. Start it with `ollama serve`, "
                "or set a hosted key such as GROQ_API_KEY, GEMINI_API_KEY, or OPENAI_API_KEY."
            ),
            **status,
        )
    if not _ollama_has_model(names, cfg.model):
        return NlStatusResponse(
            available=False,
            message=f"Ollama is running but model {cfg.model} is not pulled. Run `ollama pull {cfg.model}`.",
            **status,
        )
    return NlStatusResponse(available=True, message=f"Local Ollama model {cfg.model}.", **status)


def _parse_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    cleaned = re.sub(r"```(?:json)?\s*", "", cleaned)
    cleaned = cleaned.replace("```", "").strip()
    candidates = [cleaned]
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def extract_json_object(text: str) -> dict[str, Any] | None:
    parsed = _parse_json(text)
    if parsed is None:
        return None
    return parsed["query"] if isinstance(parsed.get("query"), dict) else parsed


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif isinstance(item, str):
                parts.append(item)
        if parts:
            return "\n".join(parts)
    reasoning = message.get("reasoning") or message.get("thinking")
    return str(reasoning or "")


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(body, list) and body:
        body = body[0]
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict):
            return str(error.get("message") or error)[:300]
        return str(error)[:300]
    return str(body)[:300]


def _http_error(cfg: LlmConfig, response: httpx.Response) -> LlmError:
    detail = _error_detail(response)
    code = response.status_code
    if code in (401, 403):
        return LlmError(f"{cfg.provider} rejected the API key (HTTP {code}): {detail}")
    if code == 404:
        return LlmError(f"{cfg.provider} model '{cfg.model}' was not found (HTTP 404): {detail}")
    if code == 429:
        return LlmError(f"{cfg.provider} rate limit or quota exceeded (HTTP 429): {detail}")
    return LlmError(f"{cfg.provider} returned HTTP {code}: {detail}")


def _payload(cfg: LlmConfig, messages: list[dict[str, Any]], json_mode: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": cfg.model, "messages": messages}
    if not _REASONING_MODEL.match(cfg.model.split("/")[-1]):
        payload["temperature"] = 0
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if cfg.provider == "ollama":
        payload["think"] = False
    elif cfg.provider == "groq" and "gpt-oss" in cfg.model:
        payload["reasoning_effort"] = "low"
    return payload


async def _chat(client: httpx.AsyncClient, cfg: LlmConfig, messages: list[dict[str, Any]]) -> str:
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    url = f"{cfg.base_url}/chat/completions"
    json_mode = cfg.json_mode
    for _ in range(2):
        await llm_limiter.acquire()
        try:
            response = await client.post(
                url, headers=headers, json=_payload(cfg, messages, json_mode), timeout=cfg.timeout
            )
        except httpx.TimeoutException as exc:
            raise LlmError(f"{cfg.provider} timed out after {cfg.timeout:.0f}s ({cfg.base_url}).") from exc
        except httpx.HTTPError as exc:
            raise LlmError(f"LLM unreachable ({cfg.base_url}): {exc}") from exc
        if response.status_code == 400 and json_mode and re.search(
            r"response_format|json", response.text, re.IGNORECASE
        ):
            json_mode = False
            continue
        if response.status_code >= 400:
            raise _http_error(cfg, response)
        try:
            data = response.json()
        except ValueError as exc:
            raise LlmError(f"{cfg.provider} returned a non-JSON body.") from exc
        choice = (data.get("choices") or [{}])[0]
        return _message_text(choice.get("message") or {})
    raise LlmError(f"{cfg.provider} rejected the request format.")


def _strip_resolved_ids(query: MapQuery) -> MapQuery:
    if query.taxon:
        query.taxon.gbifKey = None
    if query.place:
        query.place.iso2 = None
        query.place.bbox = None
        if query.place.q:
            query.place.kind = "country"
    return query


async def plan_nl(client: httpx.AsyncClient, prompt: str) -> NlPlanResponse:
    cfg = get_settings().llm()
    if not cfg.configured:
        raise LlmError(cfg.problem or "No LLM is configured.")

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": prompt},
    ]
    query: MapQuery | None = None
    notes: list[str] = []
    last_problem = ""
    for attempt in range(2):
        text = await _chat(client, cfg, messages)
        parsed = _parse_json(text)
        if parsed is None:
            last_problem = "The reply was not a JSON object."
        else:
            raw_query = parsed["query"] if isinstance(parsed.get("query"), dict) else parsed
            raw_notes = parsed.get("notes") if isinstance(parsed.get("query"), dict) else None
            try:
                query = MapQuery.model_validate(raw_query)
                notes = [str(note) for note in raw_notes or [] if note]
                break
            except ValidationError as exc:
                last_problem = f"The MapQuery failed validation: {exc.errors(include_url=False)[:5]}"
        if attempt == 0:
            messages.append({"role": "assistant", "content": text or ""})
            messages.append(
                {
                    "role": "user",
                    "content": f"{last_problem} Reply again with only the corrected JSON object in the required shape.",
                }
            )

    if query is None:
        raise LlmError(f"{cfg.provider} model {cfg.model} did not return a usable MapQuery. {last_problem}")
    if not (query.taxon and query.taxon.q) and not (query.place and query.place.q):
        notes.append("No taxon or place was recognised; refine the sentence or fill the form.")

    resolved = await resolve_query(client, _strip_resolved_ids(query))
    return NlPlanResponse(
        query=resolved.query,
        resolve=resolved,
        notes=notes,
        model=cfg.model,
        provider=cfg.provider,
    )
