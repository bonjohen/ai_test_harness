"""Test runner — orchestrates test suites against models."""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from .logging import log_event
from .models import LLMEntry


class TestRunner:
    """Dispatches test suites and records results."""

    def __init__(self, conn: sqlite3.Connection, base_url: str, backend: str) -> None:
        self.conn = conn
        self.base_url = base_url
        self.backend = backend

    def create_run(
        self,
        model: LLMEntry,
        test_suite: str,
        test_name: str,
        quantization: str | None = None,
    ) -> str:
        run_id = uuid.uuid4().hex[:12]
        self.conn.execute(
            "INSERT INTO test_runs (run_id, model_name, test_suite, test_name, quantization, backend) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, model.name, test_suite, test_name, quantization, self.backend),
        )
        self.conn.commit()
        log_event("run_created", run_id=run_id, model=model.name, test=test_name)
        return run_id

    def record_result(
        self,
        run_id: str,
        model_name: str,
        test_name: str,
        metric_name: str,
        metric_value: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        import json

        self.conn.execute(
            "INSERT INTO test_results (run_id, model_name, test_name, metric_name, metric_value, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, model_name, test_name, metric_name, metric_value, json.dumps(metadata)),
        )
        self.conn.commit()
        log_event(
            "result_recorded",
            run_id=run_id,
            model=model_name,
            metric=metric_name,
            value=metric_value,
        )
