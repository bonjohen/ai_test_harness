"""Configuration loading and startup validation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings


class HardwareProfile(BaseSettings):
    gpu_vram_gb: float | None = None
    system_ram_gb: float | None = None
    cpu_cores: int | None = None
    gpu_type: str | None = None


class Settings(BaseSettings):
    model_config = {"env_prefix": "HARNESS_"}

    source_path: Path = Field(
        default=Path("docs/source.json"),
        description="Path to model catalog JSON.",
    )
    db_path: Path = Field(
        default=Path("harness.db"),
        description="Path to SQLite results database.",
    )
    backend: str = Field(
        default="ollama",
        description="Inference backend (ollama | llama.cpp | vllm | exllamav2 | tensorrt_llm).",
    )
    base_url: str = Field(
        default="http://localhost:11434",
        description="Base URL of the running inference server.",
    )
    hardware: HardwareProfile = Field(default_factory=HardwareProfile)


def load_source(path: Path) -> dict[str, Any]:
    """Load and validate the model catalog from source.json."""
    if not path.exists():
        print(f"FATAL: source file not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        data = json.load(f)
    for required_key in ("LLMS", "MODEL_CHARACTERISTIC", "TEST"):
        if required_key not in data:
            print(f"FATAL: missing required key '{required_key}' in {path}", file=sys.stderr)
            sys.exit(1)
    return data


def get_settings() -> Settings:
    """Create and validate settings. Fails fast on invalid state."""
    return Settings()
