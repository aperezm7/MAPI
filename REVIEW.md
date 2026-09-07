# MAPI API and UI audit

**Scope:** `aperezm7/MAPI` as of `cursor/species-occurrence-maps` (open PR #1).  
**`main` has no application code** — only the two-line README from the initial commit. The maps-first app lives entirely on that feature branch.

This document is a static review of backend routes, frontend controls, and how they connect. High-confidence wiring bugs found during the audit were fixed in the same change set (listed under [Fixes in this change](#fixes-in-this-change)). Larger product/security issues are documented, not rewritten.

---

## 1. Overview

MAPI compiles a **MapQuery** (taxon + place + time + IUCN + map options) into an occurrence map. Coordinates always come from GBIF (optional iNaturalist overlay). An optional LLM planner emits the same MapQuery object; it does not invent coordinates.

```text
Browser (Vite/React + MapLibre)
  GET/POST /v1/*  ──proxy──►  FastAPI (backend/app)
                                  │
                                  ├─ GBIF species / occurrence / tiles / downloads
                                  ├─ geoBoundaries ADM0 outlines
                                  ├─ iNaturalist observations (optional)
                                  ├─ IUCN Red List v4 (optional token)
                                  └─ Ollama or OpenAI-compatible planner (optional)
```

| Layer | Stack | Role |
| --- | --- | --- |
| `packages/mapquery/mapquery.schema.json` | JSON Schema | Shared query contract |
| `backend/app/models.py` | Pydantic | Runtime MapQuery + response models |
| `backend/app/routers.py` | FastAPI | HTTP surface |
| `backend/app/services/*` | httpx adapters | GBIF, iNat, IUCN, LLM, QGIS zip, shapes |
| `frontend/src/*` | React 18 + MapLibre 5 | Single-page form + map HUD |
| Vite `/v1` proxy and nginx `/v1/` | reverse proxy | Dev (5173→8000) and Docker (8080→api:8000) |

There is **no user auth**, no cookie session, and no inbound rate limit. CORS is origin-restricted. Secrets (`IUCN_API_TOKEN`, `OPENAI_API_KEY`, `GBIF_PASSWORD`) stay on the server.

**Status legend:** **OK** = wired and looks correct · **issue** = defect or mismatch · **unverified** = needs a running stack / live upstream.

---

## 2. API inventory

Auth for every route: **none**. CORS: `CORS_ORIGINS` (default localhost Vite/nginx ports). Inbound rate limit: **none** (outbound host spacing exists in `rate_limit.py`).

| Method | Path | Request | Response | Handler | Status | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| GET | `/health` | — | `{status, service}` | `health` | **OK** | Liveness only. Proxied in Vite and nginx. |
| GET | `/v1/countries` | — | `{countries: PlaceCandidate[]}` | `countries` | **OK** (UI unused) | GBIF enumeration, 8-country fallback on failure. `fetchCountries()` exists in the client but is never called. |
| GET | `/v1/taxon/suggest` | `q` (required), `limit=12`, `rankHint?` | `{query, candidates, needsDisambiguation, warnings}` | `taxon_suggest` | **OK** after fix | Previously ignored form `rankHint`. Empty `q` → empty candidates. Missing `q` → 422. |
| POST | `/v1/query/resolve` | `MapQuery` JSON | `ResolveResponse` | `query_resolve` | **OK** | Fills `gbifKey` / `iso2`; flags homonyms. |
| POST | `/v1/map` | `MapQuery` JSON | `MapResponse` + candidate flags + `blocked` | `build_map` | **OK** after fix | 200 + `blocked: true` when taxon is ambiguous and no `gbifKey`. Unscoped query returns count 0 + warning (not 4xx). Hex/heat styles now keep GBIF tiles even when the sample is small. |
| POST | `/v1/inat/overlay` | `MapQuery` JSON | GeoJSON + `attribution`, `count`, `sampleTruncated` | `inat_layer` | **OK** | 502 on `InatError`. Place match is name-based, not ISO-strict. |
| GET | `/v1/species/iucn` | `name` | `IucnStatusResponse` | `species_iucn` | **OK** | Always 200. Without token, `available: false` + message. Needs a binomial. |
| GET | `/v1/nl/status` | — | `NlStatusResponse` | `nl_status` | **OK** | `available` is true for Ollama even if the daemon is down. Exposes `baseUrl` to the client. |
| POST | `/v1/nl/plan` | `{prompt: 3–2000 chars}` | `NlPlanResponse` | `nl_plan` | **OK** | 503 on `LlmError` / missing remote key. Strips model-supplied `gbifKey`/`iso2` and re-resolves via GBIF. |
| POST | `/v1/downloads/gbif` | `{query, format: SIMPLE_CSV\|DWCA}` | `DownloadResponse` | `gbif_download` | **OK** (security: **issue**) | 200 with `available: false` if no GBIF account. UI always sends `SIMPLE_CSV`. Uses **server** GBIF credentials. |
| POST | `/v1/export/qgis` | `MapQuery` JSON | `application/zip` | `export_qgis` | **OK** | 409 if taxon still needs a pick. Recompiles the map (not the on-screen sample). |

### Request/response contract (MapQuery)

Shared by resolve/map/inat/downloads/export:

- `taxon`: `q`, `rankHint`, `gbifKey`, names, `rank`
- `place`: `q`, `kind` (`country` \| `bbox` \| `gadm`), `iso2`, `title`, `bbox[4]`
- `time`: `yearMin`/`yearMax` in 1000–2100
- `conservation.iucn`: `EX|EW|CR|EN|VU|NT|LC|DD|NE`
- `filters`: `hasCoordinate`, `occurrenceStatus`, `basisOfRecord`
- `map`: `mode`, `sampleLimit` 1–10000, `style` points/hex/heat, `includeInat`

**Error handling**

- Pydantic 422 for invalid bodies (e.g. year out of range, bad IUCN code).
- `GbifError` → 502 (global handler).
- `InatError` → 502; `LlmError` → 503; QGIS blocked taxon → 409.
- Other exceptions → unhandled 500.
- FastAPI `detail` is a **string** on HTTPException and a **list of objects** on 422. The UI now formats both.

**Wiring:** all routes are registered on the app via `app.include_router(router)` with no extra prefix (paths already include `/v1`). Docker nginx `location /v1/` + `proxy_pass http://api:8000;` preserves the path. Vite proxies `/v1` and `/health`.

---

## 3. UI control inventory

Single page, no client router. Shareable state is `?q=` (base64url MapQuery).

### Query rail

| Control | Intended action | API / client | Status |
| --- | --- | --- | --- |
| NL textarea | Edit planner prompt | local state | **OK** |
| **Plan query** | Call planner, fill form, do **not** draw yet | `POST /v1/nl/plan` | **OK** — disabled + “Planning…” while `loading` |
| **Confirm & map** | Draw map from current form (after a plan) | `POST /v1/query/resolve` + `POST /v1/map` (+ iNat/IUCN) | **OK** after fix — used to compile a stale `nlDraft` if the user edited the form |
| Example: amphibians CR 2015+ | Load `NORTHSTAR` preset | local `setQuery` | **OK** — does not auto-draw (user must Draw map) |
| Example: jaguar in Costa Rica | Load `JAGUAR_PRESET` | local `setQuery` | **OK** — same |
| Taxon name + Rank hint | Edit query | local; clears `gbifKey` on name change | **OK** |
| **Resolve taxon** (form submit) | GBIF suggest | `GET /v1/taxon/suggest?q&rankHint` | **OK** after fix — `rankHint` was dropped |
| Taxon candidate buttons | Pin `gbifKey` + names | local `patch` | **OK** |
| Place country input | Edit place; clears `iso2` | local | **OK** |
| **Resolve place** | Match country list | `POST /v1/query/resolve` | **OK** after fix — previously no place action; candidates only appeared after Draw map |
| Place candidate buttons | Pin `iso2` | local `patch` | **OK** |
| Time From / To | `yearMin` / `yearMax` | local | **issue** (validation) — empty is fine; values outside 1000–2100 422 on compile |
| IUCN chips EX…NE | Toggle `conservation.iucn` | local | **OK** after fix — EX/EW/NE were missing vs schema |
| Style chips points/hex/heat | `map.style` | local until Draw map | **OK** after fix — hex/heat were no-ops on small species counts |
| iNaturalist checkbox | `map.includeInat` | applied on next compile | **OK** — not live; needs Draw map |
| **Draw map** | Full compile | resolve + map + optional iNat/IUCN | **OK** — disabled while loading |

### Map HUD (only after a successful, unblocked compile)

| Control | Intended action | API / client | Status |
| --- | --- | --- | --- |
| Year sliders | Edit `time.yearMin/Max` from histogram range | local | **issue** — histogram is the **sample**, not full GBIF years; sliders can invert min/max (backend swaps) |
| **Apply year window** | Recompile | same as Draw map | **OK** after fix — now disabled while loading |
| **Export sample GeoJSON** | Download on-screen sample | client Blob | **OK** — disabled if no features |
| **Export boundary GeoJSON** | Download outline | client Blob | **OK** — disabled if no outline |
| **Export map PNG** | Screenshot MapLibre canvas | `canvas.toDataURL` | **OK** after fix — tainted-canvas used to throw uncaught; still **unverified** against OSM CORS |
| **Export QGIS package** | Zip of GeoJSON + `.qgs` + loader | `POST /v1/export/qgis` | **OK** after fix — busy/disabled; recompiles **current form**, not HUD map |
| **Request GBIF download** | Async full table | `POST /v1/downloads/gbif` | **OK** after fix — busy/disabled; 200 + message if no credentials |

### Record panel and map gestures

| Control | Intended action | API / client | Status |
| --- | --- | --- | --- |
| Click GBIF / iNat point | Open record card; IUCN lookup if binomial | `GET /v1/species/iucn` | **OK** — IUCN errors swallowed; race with compile lookup |
| Click cluster | Expand zoom | MapLibre `getClusterExpansionZoom` | **OK** (logic) · **unverified** visually |
| MapLibre zoom ± | Navigate | MapLibre `NavigationControl` | **OK** |
| **Close** | Clear selection | local | **OK** |
| Open on GBIF / iNaturalist / Red List | `target=_blank` | outbound links | **OK** |

No dead `onClick` handlers were found. The closest “dead” pieces were: unused `fetchCountries()`, unused `gbif.occurrence_pages()`, and style chips that did not affect the map (fixed).

---

## 4. Prioritized findings

### P1 — production security (documented, not rewritten)

1. **Unauthenticated mutating API.** Anyone who can reach the server can drive GBIF/iNat/IUCN/LLM traffic and, if `GBIF_USERNAME`/`GBIF_PASSWORD` are set, **queue occurrence downloads billed to that GBIF account**. Fine for local research; not fine on a public host.
2. **No inbound rate limiting.** Outbound spacing (GBIF 80ms, iNat 150ms, …) does not stop a client from stacking `/v1/map` and `/v1/nl/plan` (LLM timeout 180s).
3. **Planner status leaks `baseUrl`.** Harmless for local Ollama; slightly useful recon for a remote provider. When Ollama is down, `/v1/nl/plan` now returns **503** (it previously 500'd on `httpx.ConnectError`).

### P2 — bugs fixed in this change

4. **Resolve taxon dropped `rankHint`.** Example “amphibians / class” could resolve the genus *Amphibia* instead of class 131.
5. **Hex/heat style ignored** when `choose_mode` auto-downgraded to `points` (count ≤ 2500, species-level). Tiles were omitted, so style chips did nothing.
6. **Shareable `?q=` used `btoa` on raw JSON.** Non-Latin-1 names (e.g. “São Tomé”) threw and could crash React while writing history.
7. **422 errors rendered as `[object Object]`** because FastAPI `detail` is an array.
8. **Confirm & map compiled `nlDraft`**, ignoring later form edits.
9. **No Resolve place control** — place candidates only after Draw map.
10. **PNG export uncaught `SecurityError`** if the canvas is tainted.
11. **Heat style point visibility** only ran when `mapData` changed, not on zoom.
12. **IUCN chips omitted EX/EW/NE** though the API accepts them.
13. **QGIS / GBIF buttons** had no busy or disabled state (double-submit).
14. **`POST /v1/nl/plan` returned 500** when Ollama was unreachable (`httpx.ConnectError` not mapped to `LlmError`).

### P3 — remaining product / contract issues (documented)

15. **`map.sampleLimit` (up to 10000) is not honored.** Compiler fetches one page of `min(sampleLimit, 300)`. `occurrence_pages()` exists and is unused. Likely intentional (GBIF hang comments) but the schema over-promises.
16. **`place.kind` `gadm` is unimplemented.** Resolve always emits `kind="country"`. `bbox` works in the compiler/shapes but has no UI.
17. **Mode `tiles` / `points` is not in the UI.** Auto-chosen except when hex/heat force tiles.
18. **Year sliders vs histogram.** Histogram is the inspectable sample (warning text exists). Applying a window from sample years can hide the rest of the GBIF series.
19. **Style / iNat / IUCN chips do not recompile** until Draw map — easy to think the map already changed.
20. **QGIS export vs GeoJSON export disagree** after HUD edits: GeoJSON is the last compiled `mapData`; QGIS recompiles the live form `query`.
21. **Place disambiguation does not block mapping** (unlike taxon). “United” can auto-pick the first GBIF hit.
22. **Planner `available: true` for Ollama** even when `ollama serve` is down — failure only on Plan query (503).
23. **In-memory cache** never evicts expired keys until read; unique queries grow RAM.
24. **`GET /v1/countries` unused by UI** after adding Resolve place (resolve loads the same list server-side).
25. **OSM raster tiles** may violate OSM tile usage expectations under load and may taint PNG export — consider a CORS-friendly basemap if PNG is a first-class feature.
26. **No frontend automated tests** (only `tsc --noEmit` + Vite build).

---

## 5. Live verification performed in this audit

Against a local `uvicorn` + Vite stack with live GBIF/geoBoundaries (no Ollama, no IUCN token, no GBIF download account):

| Check | Result |
| --- | --- |
| `GET /health`, Vite `/v1` proxy | 200 |
| `GET /v1/taxon/suggest?q=amphibians&rankHint=class` | CLASS 131 |
| `POST /v1/map` jaguar CR hex, 28 records in 2024 | `tiles_plus_sample` + tile URL (would have been `points` + no tile before the fix) |
| Same query `style: points` | `mode: points`, no tile |
| `POST /v1/nl/plan` with Ollama down | **503** `LLM unreachable…` (was 500) |
| Browser: Plan query | HUD shows the same unreachable message |
| Browser: jaguar example → Resolve taxon/place → Draw map | 5,659 records, clusters, HUD exports |
| Browser: hex chip → Draw map | HUD `tiles_plus_sample · hex` |
| Browser: zoom past clusters → click point | Selected record + Open on GBIF |
| Browser: GeoJSON / PNG / QGIS exports | Files downloaded; QGIS HUD confirmation |
| Browser: Request GBIF download | “Set GBIF_USERNAME and GBIF_PASSWORD…” |
| PNG canvas taint | **Did not reproduce** in this Chrome/MapLibre 5 session (try/catch still in place) |

Point inspect is easy to miss at country zoom: clicks hit **clusters** (expand zoom), not `gbif-points`. That is clustering, not a dead handler.

## 6. What still cannot be verified without extra services

| Need | Why |
| --- | --- |
| iNaturalist overlay | Checkbox not exercised in the browser pass |
| IUCN v4 token | Record card correctly showed “token is not configured” |
| Ollama + `gemma4` (or remote key) | Planner JSON/tool-call success path (failure path **was** tested) |
| Docker compose | nginx `/v1/` proxy, Redis cache, `host.docker.internal` Ollama |
| GBIF account | Successful `available: true` download key |
| Heat style at zoom | Heat chip not clicked in the browser pass (hex was) |

Backend tests (47 passed) mock GBIF/geoBoundaries. Live GBIF map/tiles, geoBoundaries outline, Vite proxy, and the React jaguar flow were exercised separately as in §5.

## 7. Fixes in this change

- Pass `rankHint` through `GET /v1/taxon/suggest` and the Resolve taxon button.
- Keep GBIF tiles when the user picked hex or heat.
- UTF-8-safe `?q=` encoding; never crash on history writes.
- Human-readable FastAPI 422 `detail` in the UI.
- Confirm & map uses the current form query.
- Resolve place button.
- PNG export try/catch; QGIS/GBIF busy state; Apply year window disabled while compiling.
- Heat sample layers follow zoom; IUCN chips include EX/EW/NE.
- Tests for rankHint suggest, hex/heat `choose_mode`, and planner 503 on connection failure.
- Map Ollama/OpenAI connection failures to HTTP 503 instead of an unhandled 500.

---

## 8. Recommended next steps

1. Merge PR #1 (`cursor/species-occurrence-maps`) so `main` actually contains the app; then merge this audit branch into it.
2. Before any public deploy: auth or network isolation for `/v1/nl/plan` and `/v1/downloads/gbif`; inbound rate limits; do not put GBIF passwords on an open origin.
3. Optional: iNaturalist overlay + heat style + a successful Ollama plan (this audit covered jaguar draw/hex/exports/planner-down).
4. Decide whether `sampleLimit` should paginate (use `occurrence_pages`) or the schema should cap at 300.
5. Either implement `gadm`/bbox UI or drop those `kind` values from the public schema.
6. Add a few frontend tests around `urlState` and `errorMessage`.
7. Treat OSM PNG export as best-effort unless the basemap is CORS-enabled.
