"""Structured JSON logging."""

from __future__ import annotations

import json
import sys
import time
from typing import Any


def log_event(
    event: str,
    *,
    run_id: str | None = None,
    model: str | None = None,
    level: str = "info",
    **extra: Any,
) -> None:
    """Write a structured JSON log line to stderr."""
    record: dict[str, Any] = {
        "ts": time.time(),
        "level": level,
        "event": event,
    }
    if run_id is not None:
        record["run_id"] = run_id
    if model is not None:
        record["model"] = model
    record.update(extra)
    try:
        print(json.dumps(record), file=sys.stderr)
    except Exception:
        pass  # logging failures must not crash the request
