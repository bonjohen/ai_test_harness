"""SQLite database management with schema versioning."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS test_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT    NOT NULL,
    model_name  TEXT    NOT NULL,
    test_suite  TEXT    NOT NULL,
    test_name   TEXT    NOT NULL,
    quantization TEXT,
    backend     TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(run_id, model_name, test_name)
);

CREATE TABLE IF NOT EXISTS test_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT    NOT NULL,
    model_name  TEXT    NOT NULL,
    test_name   TEXT    NOT NULL,
    metric_name TEXT    NOT NULL,
    metric_value REAL,
    metadata    TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_id, model_name, test_name)
        REFERENCES test_runs(run_id, model_name, test_name)
);
"""


def init_db(db_path: Path) -> sqlite3.Connection:
    """Open database, enforce pragmas, apply schema if needed."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")

    existing = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()

    if existing is None:
        conn.executescript(SCHEMA_SQL)
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()
    else:
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        if row is None or row[0] != SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema version mismatch: expected {SCHEMA_VERSION}, "
                f"got {row[0] if row else 'NULL'}. Run migrations."
            )
    return conn
