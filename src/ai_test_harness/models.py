"""Model registry — loads the LLM catalog from source.json."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class LLMEntry(BaseModel):
    name: str
    size_b: float
    type: str
    primary_role: list[str]
    recommended_quantizations: list[str]
    context_window_tokens: int
    notes: str = ""


class ModelRegistry:
    """In-memory registry of models loaded from source.json."""

    def __init__(self, raw_llms: list[dict[str, Any]]) -> None:
        self.models: list[LLMEntry] = [LLMEntry.model_validate(m) for m in raw_llms]

    def by_name(self, name: str) -> LLMEntry | None:
        for m in self.models:
            if m.name == name:
                return m
        return None

    def by_role(self, role: str) -> list[LLMEntry]:
        return [m for m in self.models if role in m.primary_role]

    def by_max_size(self, max_b: float) -> list[LLMEntry]:
        return [m for m in self.models if m.size_b <= max_b]

    def names(self) -> list[str]:
        return [m.name for m in self.models]
