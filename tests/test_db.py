"""Tests for database initialization."""

from __future__ import annotations

import sqlite3


def test_schema_version_exists(db_conn: sqlite3.Connection) -> None:
    row = db_conn.execute("SELECT version FROM schema_version").fetchone()
    assert row is not None
    assert row[0] == 1


def test_tables_created(db_conn: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "test_runs" in tables
    assert "test_results" in tables


def test_foreign_keys_enabled(db_conn: sqlite3.Connection) -> None:
    row = db_conn.execute("PRAGMA foreign_keys").fetchone()
    assert row[0] == 1
