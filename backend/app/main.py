from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routers import router
from app.services.gbif import GbifError


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.http = httpx.AsyncClient(
        headers={"User-Agent": settings.gbif_user_agent},
        follow_redirects=True,
        timeout=httpx.Timeout(20.0, connect=10.0),
    )
    yield
    await app.state.http.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="MAPI",
        description="Species occurrence MapQuery API. Coordinates come from GBIF, never from the LLM.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.exception_handler(GbifError)
    async def gbif_error_handler(_request: Request, exc: GbifError):
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    return app


app = create_app()
