from app.services.llm import extract_json_object


def test_extract_plain_json():
    parsed = extract_json_object('{"taxon": {"q": "jaguars"}, "place": {"q": "Costa Rica"}}')
    assert parsed is not None
    assert parsed["taxon"]["q"] == "jaguars"


def test_extract_fenced_and_think_blocks():
    text = """<think>planning</think>
```json
{"query": {"taxon": {"q": "amphibians", "rankHint": "class"}, "place": {"q": "Costa Rica"}}}
```
"""
    parsed = extract_json_object(text)
    assert parsed is not None
    assert parsed["taxon"]["q"] == "amphibians"
    assert parsed["place"]["q"] == "Costa Rica"


def test_extract_embedded_object():
    parsed = extract_json_object('Here you go: {"taxon": {"q": "Panthera onca"}} thanks')
    assert parsed is not None
    assert parsed["taxon"]["q"] == "Panthera onca"


def test_extract_rejects_empty():
    assert extract_json_object("") is None
    assert extract_json_object("no json here") is None


import json

import httpx
import pytest
import respx
from httpx import Response

from app.config import Settings
from app.services.llm import LlmError, plan_nl

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

PLAN = {
    "query": {
        "taxon": {"q": "Panthera onca", "rankHint": "species", "gbifKey": 999},
        "place": {"q": "Costa Rica", "kind": "country", "iso2": "XX"},
        "time": {"yearMin": 2015, "yearMax": None},
        "map": {"mode": "tiles_plus_sample", "sampleLimit": 300, "style": "hex"},
    },
    "notes": ["Jaguar is Panthera onca."],
}


def completion(content: str) -> Response:
    return Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})


def mock_gbif_jaguar_costa_rica() -> None:
    respx.get("https://api.gbif.org/v1/species/match").mock(
        return_value=Response(
            200,
            json={
                "usageKey": 5219426,
                "scientificName": "Panthera onca (Linnaeus, 1758)",
                "canonicalName": "Panthera onca",
                "rank": "SPECIES",
                "confidence": 98,
                "matchType": "EXACT",
                "status": "ACCEPTED",
            },
        )
    )
    respx.get("https://api.gbif.org/v1/species/suggest").mock(return_value=Response(200, json=[]))
    respx.get("https://api.gbif.org/v1/enumeration/country").mock(
        return_value=Response(200, json=[{"iso2": "CR", "iso3": "CRI", "title": "Costa Rica"}])
    )


def test_default_provider_is_local_ollama():
    cfg = Settings().llm()
    assert cfg.provider == "ollama"
    assert cfg.base_url == "http://127.0.0.1:11434/v1"
    assert cfg.model == "gemma4"
    assert cfg.configured


@pytest.mark.parametrize(
    ("env", "provider", "base_url", "model"),
    [
        ({"GROQ_API_KEY": "g"}, "groq", "https://api.groq.com/openai/v1", "openai/gpt-oss-20b"),
        ({"GEMINI_API_KEY": "k"}, "gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.8-flash"),
        ({"GOOGLE_API_KEY": "k"}, "gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.8-flash"),
        ({"OPENAI_API_KEY": "sk"}, "openai", "https://api.openai.com/v1", "gpt-4o-mini"),
        ({"OPENROUTER_API_KEY": "or"}, "openrouter", "https://openrouter.ai/api/v1", "openai/gpt-oss-20b"),
        ({"OPENAI_API_KEY": "ollama"}, "ollama", "http://127.0.0.1:11434/v1", "gemma4"),
    ],
)
def test_auto_detects_provider_from_key(monkeypatch, env, provider, base_url, model):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    cfg = Settings().llm()
    assert (cfg.provider, cfg.base_url, cfg.model) == (provider, base_url, model)
    assert cfg.configured


def test_explicit_provider_and_overrides(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL", "llama-3.3-70b-versatile")
    cfg = Settings().llm()
    assert cfg.provider == "groq"
    assert cfg.api_key == "g"
    assert cfg.model == "llama-3.3-70b-versatile"
    assert cfg.timeout == 60.0


def test_legacy_ollama_env_still_works(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://host.docker.internal:11434/v1")
    monkeypatch.setenv("OPENAI_MODEL", "gemma4:e2b")
    cfg = Settings().llm()
    assert cfg.base_url == "http://host.docker.internal:11434/v1"
    assert cfg.model == "gemma4:e2b"
    assert cfg.timeout == 180.0


def test_openai_compatible_requires_base_url_and_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    cfg = Settings().llm()
    assert not cfg.configured
    assert "LLM_BASE_URL" in (cfg.problem or "")

    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example.test/v1/")
    monkeypatch.setenv("LLM_MODEL", "my-model")
    cfg = Settings().llm()
    assert cfg.configured
    assert cfg.base_url == "https://llm.example.test/v1"


def test_unknown_provider_is_reported(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    cfg = Settings().llm()
    assert not cfg.configured
    assert "Unknown LLM_PROVIDER" in (cfg.problem or "")


@respx.mock
@pytest.mark.asyncio
async def test_plan_nl_with_hosted_provider(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq")
    mock_gbif_jaguar_costa_rica()
    route = respx.post(GROQ_URL).mock(return_value=completion(json.dumps(PLAN)))

    async with httpx.AsyncClient() as client:
        result = await plan_nl(client, "jaguars in Costa Rica since 2015 as hexagons")

    sent = json.loads(route.calls[0].request.content)
    assert route.calls[0].request.headers["Authorization"] == "Bearer test-groq"
    assert sent["model"] == "openai/gpt-oss-20b"
    assert sent["response_format"] == {"type": "json_object"}
    assert result.provider == "groq"
    assert result.query.taxon and result.query.taxon.gbifKey == 5219426
    assert result.query.place and result.query.place.iso2 == "CR"
    assert result.query.time and result.query.time.yearMin == 2015
    assert result.query.map.style == "hex"
    assert result.notes == ["Jaguar is Panthera onca."]


@respx.mock
@pytest.mark.asyncio
async def test_plan_nl_retries_without_json_mode(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("LLM_MODEL", "m")
    mock_gbif_jaguar_costa_rica()
    route = respx.post("https://llm.example.test/v1/chat/completions").mock(
        side_effect=[
            Response(400, json={"error": {"message": "response_format is not supported"}}),
            completion("```json\n" + json.dumps(PLAN) + "\n```"),
        ]
    )

    async with httpx.AsyncClient() as client:
        result = await plan_nl(client, "jaguars in Costa Rica")

    assert "response_format" in json.loads(route.calls[0].request.content)
    assert "response_format" not in json.loads(route.calls[1].request.content)
    assert "Authorization" not in route.calls[0].request.headers
    assert result.query.taxon and result.query.taxon.gbifKey == 5219426


@respx.mock
@pytest.mark.asyncio
async def test_plan_nl_repairs_invalid_json(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    mock_gbif_jaguar_costa_rica()
    bad = {"query": {"conservation": {"iucn": ["ENDANGERED"]}, "taxon": {"q": "Panthera onca"}}}
    route = respx.post(GROQ_URL).mock(side_effect=[completion(json.dumps(bad)), completion(json.dumps(PLAN))])

    async with httpx.AsyncClient() as client:
        result = await plan_nl(client, "endangered jaguars in Costa Rica")

    repair = json.loads(route.calls[1].request.content)["messages"][-1]["content"]
    assert "failed validation" in repair
    assert result.query.taxon and result.query.taxon.gbifKey == 5219426


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "fragment"),
    [(401, "rejected the API key"), (404, "was not found"), (429, "rate limit"), (500, "HTTP 500")],
)
async def test_plan_nl_maps_provider_errors(monkeypatch, status, fragment):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    respx.post(GROQ_URL).mock(return_value=Response(status, json={"error": {"message": "nope"}}))
    async with httpx.AsyncClient() as client:
        with pytest.raises(LlmError, match=fragment):
            await plan_nl(client, "jaguars in Costa Rica")


@respx.mock
@pytest.mark.asyncio
async def test_plan_nl_gives_up_after_one_repair(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    respx.post(GROQ_URL).mock(return_value=completion("I cannot help with that."))
    async with httpx.AsyncClient() as client:
        with pytest.raises(LlmError, match="did not return a usable MapQuery"):
            await plan_nl(client, "jaguars in Costa Rica")
