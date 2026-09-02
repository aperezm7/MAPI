# MAPI

Species APIs compiled into interactive occurrence maps. The form, the shareable URL, and the optional LLM planner all produce the same **MapQuery** object. Coordinates always come from GBIF (or iNaturalist), never from a model.

## What it does

Search a taxon and place, optionally filter by year and IUCN category (via GBIF), and draw:

- GBIF density/adhoc map tiles for overview
- a capped, clustered GeoJSON sample for inspection
- optional iNaturalist research-grade photo overlay
- optional IUCN Red List v4 status on a species card

North-star example from the form: endangered amphibians in Costa Rica since 2015.

## Layout

- `backend/` — FastAPI, Pydantic MapQuery, GBIF/iNat/IUCN adapters, cache, rate limits
- `frontend/` — Vite + React + MapLibre
- `packages/mapquery/mapquery.schema.json` — shared query contract

## Local development

```bash
cp .env.example .env   # optional keys for IUCN / OpenAI / GBIF downloads

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
| `OPENAI_API_KEY` | Natural-language MapQuery planner |
| `GBIF_USERNAME` / `GBIF_PASSWORD` | Async full occurrence download |

Map filters for endangered/threatened taxa use GBIF `iucnRedListCategory` so maps work without an IUCN token.

## Attribution

Occurrence data from [GBIF](https://www.gbif.org). Optional overlay from [iNaturalist](https://www.inaturalist.org). Optional assessments from the [IUCN Red List](https://www.iucnredlist.org).
