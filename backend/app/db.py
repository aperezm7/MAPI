from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.config import get_settings

_lock = threading.Lock()
_ready = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    key_hash TEXT UNIQUE,
    key_prefix TEXT,
    role TEXT NOT NULL DEFAULT 'client',
    active INTEGER NOT NULL DEFAULT 1,
    budget REAL,
    spent REAL NOT NULL DEFAULT 0,
    spent_month TEXT NOT NULL DEFAULT '',
    maps_per_day INTEGER,
    plans_per_day INTEGER,
    requests_per_minute INTEGER,
    gbif_username TEXT,
    gbif_password TEXT,
    gbif_email TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS queries (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    cost REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (client_id) REFERENCES clients(id)
);

CREATE INDEX IF NOT EXISTS queries_client_created ON queries(client_id, created_at DESC);
"""


def database_path() -> Path:
    return Path(get_settings().database_path)


def connect() -> sqlite3.Connection:
    global _ready
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    if not _ready:
        with _lock:
            conn.executescript(SCHEMA)
            conn.commit()
            _ready = True
    return conn


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reset_db_for_tests() -> None:
    global _ready
    with _lock:
        _ready = False
        path = database_path()
        for suffix in ("", "-wal", "-shm"):
            file = Path(str(path) + suffix)
            if file.exists():
                file.unlink()
