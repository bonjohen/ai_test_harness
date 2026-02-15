"""Tests for the model registry."""

from __future__ import annotations

from ai_test_harness.models import ModelRegistry


def test_registry_loads_all_models(registry: ModelRegistry) -> None:
    assert len(registry.models) == 3


def test_by_name_found(registry: ModelRegistry) -> None:
    model = registry.by_name("llama3:latest")
    assert model is not None
    assert model.size_b == 8.0


def test_by_name_not_found(registry: ModelRegistry) -> None:
    assert registry.by_name("nonexistent") is None


def test_by_role(registry: ModelRegistry) -> None:
    routers = registry.by_role("routing")
    assert len(routers) >= 1
    for m in routers:
        assert "routing" in m.primary_role


def test_by_max_size(registry: ModelRegistry) -> None:
    small = registry.by_max_size(10)
    assert all(m.size_b <= 10 for m in small)
