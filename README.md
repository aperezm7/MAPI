# MAPI

Species APIs compiled into interactive occurrence maps. The form, the shareable URL, and the optional LLM planner all produce the same **MapQuery** object. Coordinates always come from GBIF (or iNaturalist), never from a model.

## What it does

Search a taxon and place, optionally filter by year and IUCN category (via GBIF), and draw:

- GBIF density/adhoc map tiles for overview
- a capped, clustered GeoJSON sample for inspection
- country (or bbox) outline on the map
- PNG, GeoJSON, and QGIS Desktop export
- optional iNaturalist research-grade photo overlay
- optional IUCN Red List v4 status on a species card

North-star example from the form: endangered amphibians in Costa Rica since 2015.

## Layout

- `backend/` — FastAPI, Pydantic MapQuery, GBIF/iNat/IUCN adapters, cache, rate limits
- `frontend/` — Vite + React + MapLibre
- `packages/mapquery/mapquery.schema.json` — shared query contract

## Local development

```bash
cp .env.example .env   # add GROQ_API_KEY / GEMINI_API_KEY / OPENAI_API_KEY for a hosted planner

# API
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000

# UI (another terminal)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 — Vite proxies `/v1` to the API (`MAPI_API` overrides the proxy target if port 8000 is taken).

```bash
cd backend && pytest -q
```

## Natural-language planner

**Plan query** sends the sentence to an LLM, which returns a MapQuery (names, years, IUCN codes, map style). MAPI then resolves taxon keys and ISO codes through GBIF, so the model never supplies IDs or coordinates. Review the form, then **Confirm & map**.

Any OpenAI-compatible chat-completions API works. Set one key and leave `LLM_PROVIDER` unset; MAPI picks the provider automatically:

| Provider | Key | Default model | Notes |
| --- | --- | --- | --- |
| Groq | `GROQ_API_KEY` | `openai/gpt-oss-20b` | Fast, free tier |
| Google Gemini | `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) | `gemini-3.8-flash` | Free tier via AI Studio |
| OpenAI | `OPENAI_API_KEY` | `gpt-4o-mini` | |
| OpenRouter | `OPENROUTER_API_KEY` | `openai/gpt-oss-20b` | Any OpenRouter model via `LLM_MODEL` |
| Ollama (local) | none | `gemma4` | Used when no key is set |
| Anything else | `LLM_API_KEY` (optional) | `LLM_MODEL` | `LLM_PROVIDER=openai_compatible` + `LLM_BASE_URL` |

If several keys are set, the order is OpenAI, Gemini, Groq, OpenRouter; set `LLM_PROVIDER` to choose explicitly. `LLM_MODEL` overrides the model for any provider.

```bash
export GROQ_API_KEY=gsk_...                 # hosted
# or, fully local:
ollama pull gemma4 && ollama serve
```

`GET /v1/nl/status` reports the active provider and model, and whether it is ready (key present, or Ollama reachable with the model pulled). Keys never leave the server. Bad keys, unknown models, rate limits, and unreachable endpoints come back from `POST /v1/nl/plan` as HTTP 503 with a readable message.

## Docker

```bash
docker compose up --build
```

UI at http://localhost:8080, API at http://localhost:8000.

## Optional environment

| Variable | Purpose |
| --- | --- |
| `GBIF_USER_AGENT` | Required courtesy identification to GBIF |
| `REDIS_URL` | Shared cache; otherwise in-memory TTL |
| `IUCN_API_TOKEN` | Red List v4 species-page status only |
| `LLM_PROVIDER` | `auto` (default), `groq`, `gemini`, `openai`, `openrouter`, `ollama`, or `openai_compatible` |
| `GROQ_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` / `OPENROUTER_API_KEY` | Hosted planner keys (see above) |
| `LLM_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_TIMEOUT_SECONDS` | Planner overrides for any provider |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | Local planner (`http://127.0.0.1:11434/v1` + `gemma4` by default) |
| `GBIF_USERNAME` / `GBIF_PASSWORD` | Async full occurrence download |

Map filters for endangered/threatened taxa use GBIF `iucnRedListCategory` so maps work without an IUCN token.

## Shapes and QGIS export

QGIS Desktop has a Python API (PyQGIS) and optional self-hosted **QGIS Server** (WMS/WFS). It does not publish a cloud REST API we can call like GBIF, so MAPI does not depend on a QGIS install.

Country outlines come from [geoBoundaries](https://www.geoboundaries.org) (ADM0 GeoJSON). The map HUD can export:

- the inspectable occurrence sample as GeoJSON
- the place outline as GeoJSON
- a PNG of the current MapLibre view
- a **QGIS package** (`POST /v1/export/qgis`): zip with GeoJSON layers, `mapi.qgs`, and `load_in_qgis.py` to add OSM + GBIF XYZ tiles in QGIS Desktop

For a full occurrence table, use **Request GBIF download** rather than the capped sample.

## Attribution

Occurrence data from [GBIF](https://www.gbif.org). Country outlines from [geoBoundaries](https://www.geoboundaries.org). Optional overlay from [iNaturalist](https://www.inaturalist.org). Optional assessments from the [IUCN Red List](https://www.iucnredlist.org). Basemap © OpenStreetMap contributors.
