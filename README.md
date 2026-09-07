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
cp .env.example .env   # Ollama is the default planner; add remote keys only if needed

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

Default planner is **local Ollama + Gemma 4** (`gemma4`). Pull and serve it, then **Plan query** in the UI:

```bash
ollama pull gemma4
ollama serve   # if it is not already running
```

To switch to a remote OpenAI-compatible API (OpenAI, Groq, …), set:

```bash
export LLM_PROVIDER=openai
export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_MODEL=gpt-4o-mini
export OPENAI_API_KEY=...
```

The model only emits a MapQuery. Taxon keys and ISO codes are resolved through GBIF after the LLM returns.

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
| `LLM_PROVIDER` | `ollama` (default, local Gemma 4) or `openai` for a remote OpenAI-compatible API |
| `OPENAI_BASE_URL` / `OPENAI_MODEL` | Planner endpoint and model (`http://127.0.0.1:11434/v1` + `gemma4` by default) |
| `OPENAI_API_KEY` | Required only for remote providers |
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
