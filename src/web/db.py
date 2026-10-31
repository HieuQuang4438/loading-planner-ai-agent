"""The service's SQLite file (docs/product/architecture.md §6): one connection per request, schema by migration.

`MIGRATIONS[i]` takes the file from `user_version` i to i + 1. A migration is a script; append, never edit one that
has shipped. `migrate` runs at app creation and is a no-op on a current file."""
from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS: list[str] = [
    # 1: accounts, sessions, login failures
    """
    CREATE TABLE users (
      id          INTEGER PRIMARY KEY,
      name        TEXT NOT NULL UNIQUE,
      pw_hash     TEXT NOT NULL,
      active      INTEGER NOT NULL DEFAULT 1,
      created_at  TEXT NOT NULL
    );
    CREATE TABLE sessions (
      token_hash  TEXT PRIMARY KEY,
      user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      expires_at  TEXT NOT NULL
    );
    CREATE TABLE login_failures (
      name        TEXT NOT NULL,
      at          TEXT NOT NULL
    );
    CREATE INDEX login_failures_by_name ON login_failures(name, at);
    """,
    # 2: one row per finished run, owned by a user (architecture.md §6)
    """
    CREATE TABLE runs (
      job_id      TEXT PRIMARY KEY,
      user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      created_at  TEXT NOT NULL,
      lot_name    TEXT NOT NULL,
      status      TEXT NOT NULL,
      code        TEXT,
      cost        REAL,
      settings    TEXT NOT NULL,
      lot         TEXT NOT NULL,
      result      TEXT NOT NULL,
      solution    TEXT,
      diag        TEXT
    );
    CREATE INDEX runs_by_user ON runs(user_id, created_at DESC);
    """,
    # 3: lots, their documents and chat, owned by a user; a run names its lot and mode
    """
    CREATE TABLE lots (
      id          INTEGER PRIMARY KEY,
      user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      parent_id   INTEGER REFERENCES lots(id) ON DELETE CASCADE,
      name        TEXT NOT NULL,
      note        TEXT,
      rev         INTEGER NOT NULL,
      lot         TEXT NOT NULL,
      containers  TEXT,
      created_at  TEXT NOT NULL,
      updated_at  TEXT NOT NULL,
      deleted_at  TEXT
    );
    CREATE INDEX lots_by_user ON lots(user_id, updated_at DESC);
    CREATE TABLE documents (
      id          INTEGER PRIMARY KEY,
      lot_id      INTEGER NOT NULL REFERENCES lots(id) ON DELETE CASCADE,
      name        TEXT NOT NULL,
      mime        TEXT NOT NULL,
      size        INTEGER NOT NULL,
      data        BLOB NOT NULL,
      status      TEXT NOT NULL,
      reading     TEXT,
      error       TEXT,
      created_at  TEXT NOT NULL
    );
    CREATE INDEX documents_by_lot ON documents(lot_id, id);
    CREATE TABLE chat_messages (
      id          INTEGER PRIMARY KEY,
      lot_id      INTEGER NOT NULL REFERENCES lots(id) ON DELETE CASCADE,
      role        TEXT NOT NULL,
      content     TEXT NOT NULL,
      created_at  TEXT NOT NULL
    );
    CREATE INDEX chat_by_lot ON chat_messages(lot_id, id);
    ALTER TABLE runs ADD COLUMN lot_id INTEGER REFERENCES lots(id) ON DELETE SET NULL;
    ALTER TABLE runs ADD COLUMN mode TEXT;
    CREATE INDEX runs_by_lot ON runs(lot_id, created_at DESC);
    """,
]


def connect(path: str | Path) -> sqlite3.Connection:
    """A connection with WAL, foreign keys and a 5 s busy timeout; rows are `sqlite3.Row`."""
    conn = sqlite3.connect(path, timeout=5, isolation_level=None)  # autocommit: transactions are explicit
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """Apply the migrations the file has not seen, each in one transaction together with its `user_version`."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for i in range(version, len(MIGRATIONS)):
        conn.executescript(f"BEGIN;\n{MIGRATIONS[i]}\nPRAGMA user_version = {i + 1};\nCOMMIT;")
