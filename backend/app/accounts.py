"""System clients: API keys, budgets, and an optional GBIF download account."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from base64 import urlsafe_b64encode
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Request

from app.config import get_settings
from app.db import session

ANONYMOUS_ID = "anonymous"


@dataclass
class Client:
    id: str
    name: str
    role: str
    active: bool
    budget: float | None
    spent: float
    spent_month: str
    maps_per_day: int | None
    plans_per_day: int | None
    requests_per_minute: int | None
    gbif_username: str | None
    gbif_email: str | None
    gbif_password: str | None
    key_prefix: str | None
    created_at: str

    @property
    def unlimited(self) -> bool:
        return self.id == ANONYMOUS_ID

    def public(self) -> dict:
        month = _month()
        spent = 0.0 if self.spent_month != month else self.spent
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "active": self.active,
            "unlimited": self.unlimited,
            "budget": self.budget,
            "spent": round(spent, 4),
            "month": month,
            "mapsPerDay": self.maps_per_day,
            "plansPerDay": self.plans_per_day,
            "requestsPerMinute": self.requests_per_minute,
            "keyPrefix": self.key_prefix,
            "gbif": {
                "connected": bool(self.gbif_username and self.gbif_password),
                "username": self.gbif_username,
                "email": self.gbif_email,
            },
            "createdAt": self.created_at,
        }


def _month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _row(row: sqlite3.Row) -> Client:
    return Client(
        id=row["id"],
        name=row["name"],
        role=row["role"],
        active=bool(row["active"]),
        budget=row["budget"],
        spent=float(row["spent"] or 0),
        spent_month=row["spent_month"] or "",
        maps_per_day=row["maps_per_day"],
        plans_per_day=row["plans_per_day"],
        requests_per_minute=row["requests_per_minute"],
        gbif_username=row["gbif_username"],
        gbif_email=row["gbif_email"],
        gbif_password=_decrypt(row["gbif_password"]) if row["gbif_password"] else None,
        key_prefix=row["key_prefix"],
        created_at=row["created_at"],
    )


def _fernet() -> Fernet:
    secret = (get_settings().mapi_secret_key or get_settings().mapi_admin_token or "").strip()
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Set MAPI_SECRET_KEY before storing a GBIF password.",
        )
    digest = hashlib.sha256(secret.encode()).digest()
    return Fernet(urlsafe_b64encode(digest))


def _encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def _decrypt(value: str) -> str | None:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, HTTPException):
        return None


def ensure_anonymous() -> Client:
    with session() as conn:
        existing = conn.execute("SELECT * FROM clients WHERE id = ?", (ANONYMOUS_ID,)).fetchone()
        if existing:
            return _row(existing)
        conn.execute(
            """
            INSERT INTO clients (id, name, role, active, budget, spent, spent_month, created_at)
            VALUES (?, 'Open access', 'anonymous', 1, NULL, 0, ?, ?)
            """,
            (ANONYMOUS_ID, _month(), _now()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM clients WHERE id = ?", (ANONYMOUS_ID,)).fetchone()
        return _row(row)


def hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def create_client(
    name: str,
    *,
    budget: float | None = None,
    maps_per_day: int | None = None,
    plans_per_day: int | None = None,
    requests_per_minute: int | None = None,
) -> tuple[Client, str]:
    settings = get_settings()
    api_key = "mapi_" + secrets.token_urlsafe(24)
    client_id = "cli_" + secrets.token_hex(8)
    with session() as conn:
        conn.execute(
            """
            INSERT INTO clients (
                id, name, key_hash, key_prefix, role, active, budget, spent, spent_month,
                maps_per_day, plans_per_day, requests_per_minute, created_at
            ) VALUES (?, ?, ?, ?, 'client', 1, ?, 0, ?, ?, ?, ?, ?)
            """,
            (
                client_id,
                name.strip(),
                hash_key(api_key),
                api_key[:12],
                settings.default_budget if budget is None else budget,
                _month(),
                settings.quota_maps_per_day if maps_per_day is None else maps_per_day,
                settings.quota_plans_per_day if plans_per_day is None else plans_per_day,
                settings.quota_requests_per_minute if requests_per_minute is None else requests_per_minute,
                _now(),
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    return _row(row), api_key


def list_clients() -> list[Client]:
    ensure_anonymous()
    with session() as conn:
        rows = conn.execute("SELECT * FROM clients ORDER BY created_at").fetchall()
    return [_row(row) for row in rows]


def get_client(client_id: str) -> Client | None:
    with session() as conn:
        row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    return _row(row) if row else None


def get_by_key(api_key: str) -> Client | None:
    with session() as conn:
        row = conn.execute("SELECT * FROM clients WHERE key_hash = ?", (hash_key(api_key),)).fetchone()
    return _row(row) if row else None


def update_client(client_id: str, fields: dict) -> Client | None:
    if client_id == ANONYMOUS_ID:
        return None
    allowed = {
        "name": "name",
        "active": "active",
        "budget": "budget",
        "maps_per_day": "maps_per_day",
        "plans_per_day": "plans_per_day",
        "requests_per_minute": "requests_per_minute",
    }
    sets: list[str] = []
    values: list = []
    for key, column in allowed.items():
        if key in fields:
            sets.append(f"{column} = ?")
            value = fields[key]
            if key == "active":
                value = 1 if value else 0
            values.append(value)
    if not sets:
        return get_client(client_id)
    values.append(client_id)
    with session() as conn:
        conn.execute(f"UPDATE clients SET {', '.join(sets)} WHERE id = ? AND id != ?", (*values, ANONYMOUS_ID))
        conn.commit()
        row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    return _row(row) if row else None


def set_gbif(client_id: str, username: str, password: str, email: str | None) -> Client:
    encrypted = _encrypt(password)
    with session() as conn:
        conn.execute(
            "UPDATE clients SET gbif_username = ?, gbif_password = ?, gbif_email = ? WHERE id = ?",
            (username.strip(), encrypted, (email or "").strip() or None, client_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    return _row(row)


def clear_gbif(client_id: str) -> Client | None:
    with session() as conn:
        conn.execute(
            "UPDATE clients SET gbif_username = NULL, gbif_password = NULL, gbif_email = NULL WHERE id = ?",
            (client_id,),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    return _row(row) if row else None


def add_spent(client_id: str, cost: float) -> None:
    if cost <= 0 or client_id == ANONYMOUS_ID:
        return
    month = _month()
    with session() as conn:
        row = conn.execute("SELECT spent, spent_month FROM clients WHERE id = ?", (client_id,)).fetchone()
        if not row:
            return
        spent = 0.0 if row["spent_month"] != month else float(row["spent"] or 0)
        conn.execute(
            "UPDATE clients SET spent = ?, spent_month = ? WHERE id = ?",
            (spent + cost, month, client_id),
        )
        conn.commit()


def current_spent(client: Client) -> float:
    if client.spent_month != _month():
        return 0.0
    return client.spent


def record_query(client_id: str, kind: str, summary: str, body: str, cost: float, status: str) -> None:
    with session() as conn:
        conn.execute(
            """
            INSERT INTO queries (id, client_id, kind, summary, body, cost, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("qry_" + secrets.token_hex(8), client_id, kind, summary[:240], body[:4000], cost, status, _now()),
        )
        conn.execute(
            """
            DELETE FROM queries WHERE client_id = ? AND id NOT IN (
                SELECT id FROM queries WHERE client_id = ? ORDER BY created_at DESC LIMIT 500
            )
            """,
            (client_id, client_id),
        )
        conn.commit()


def recent_queries(client_id: str, limit: int = 30) -> list[dict]:
    with session() as conn:
        rows = conn.execute(
            """
            SELECT id, kind, summary, cost, status, created_at
            FROM queries WHERE client_id = ? ORDER BY created_at DESC LIMIT ?
            """,
            (client_id, limit),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "kind": row["kind"],
            "summary": row["summary"],
            "cost": row["cost"],
            "status": row["status"],
            "createdAt": row["created_at"],
        }
        for row in rows
    ]


def resolve_request(request: Request) -> Client:
    settings = get_settings()
    header = request.headers.get("authorization") or ""
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if token:
        client = get_by_key(token)
        if client is None or not client.active:
            raise HTTPException(status_code=401, detail="Unknown or inactive API key.")
        return client
    if not settings.auth_required:
        return ensure_anonymous()
    raise HTTPException(
        status_code=401,
        detail="Send Authorization: Bearer <api key>. An administrator creates keys with MAPI_ADMIN_TOKEN.",
    )


def require_admin(request: Request) -> None:
    expected = (get_settings().mapi_admin_token or "").strip()
    provided = (request.headers.get("x-admin-token") or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Set MAPI_ADMIN_TOKEN to manage clients.")
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Admin token rejected.")
