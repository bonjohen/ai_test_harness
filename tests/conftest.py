"""Shared test fixtures."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ai_test_harness.config import load_source
from ai_test_harness.db import init_db
from ai_test_harness.models import ModelRegistry


@pytest.fixture()
def source_data() -> dict:
    return load_source(Path("docs/source.json"))


@pytest.fixture()
def registry(source_data: dict) -> ModelRegistry:
    return ModelRegistry(source_data["LLMS"])


@pytest.fixture()
def db_conn(tmp_path: Path) -> sqlite3.Connection:
    conn = init_db(tmp_path / "test.db")
    yield conn
    conn.close()
