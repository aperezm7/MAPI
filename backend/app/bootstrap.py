"""First-boot secrets and the single team client used by Docker Compose."""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

from app.accounts import ANONYMOUS_ID, create_client, ensure_anonymous
from app.config import get_settings
from app.db import database_path, session

log = logging.getLogger("mapi.bootstrap")


def _secret_file() -> Path:
    return database_path().parent / "secrets.env"


def _read_secret_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    found: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        found[key.strip()] = value.strip()
    return found


def prepare_runtime() -> None:
    """When auth is required, persist an admin token and encryption key if either is missing."""
    settings = get_settings()
    if not settings.auth_required:
        return
    path = _secret_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    stored = _read_secret_file(path)
    admin = (os.environ.get("MAPI_ADMIN_TOKEN") or stored.get("MAPI_ADMIN_TOKEN") or "").strip()
    secret = (os.environ.get("MAPI_SECRET_KEY") or stored.get("MAPI_SECRET_KEY") or "").strip()
    if not admin:
        admin = secrets.token_urlsafe(32)
    if not secret:
        secret = secrets.token_urlsafe(32)
    body = f"MAPI_ADMIN_TOKEN={admin}\nMAPI_SECRET_KEY={secret}\n"
    if not path.exists() or path.read_text() != body:
        path.write_text(body)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        log.warning("Admin token and encryption key are in %s.", path)
    os.environ["MAPI_ADMIN_TOKEN"] = admin
    os.environ["MAPI_SECRET_KEY"] = secret
    get_settings.cache_clear()


def bootstrap_team_client() -> None:
    """Create one client named team when auth is on and no named client exists yet."""
    settings = get_settings()
    if not settings.auth_required:
        return
    ensure_anonymous()
    with session() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM clients WHERE id != ?",
            (ANONYMOUS_ID,),
        ).fetchone()["n"]
    if count:
        return
    client, api_key = create_client("team")
    path = database_path().parent / "team-api-key.txt"
    path.write_text(api_key + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    log.warning("Created team client %s. API key written to %s.", client.id, path)
