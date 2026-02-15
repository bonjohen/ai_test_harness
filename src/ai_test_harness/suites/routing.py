"""Routing test suite — intent classification and latency."""

from __future__ import annotations

import time
from typing import Any

import httpx


async def run_intent_classification(
    client: httpx.AsyncClient,
    model: str,
    prompts: list[dict[str, Any]],
) -> dict[str, float]:
    """Classify user queries and measure accuracy against ground truth.

    Each prompt dict should have 'text' and 'expected_route' keys.
    """
    correct = 0
    total = len(prompts)

    for prompt in prompts:
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt["text"]}],
                "max_tokens": 32,
            },
        )
        resp.raise_for_status()
        result = resp.json()["choices"][0]["message"]["content"].strip().lower()
        if result == prompt["expected_route"].lower():
            correct += 1

    return {"accuracy_percent": (correct / total * 100) if total > 0 else 0.0}


async def run_latency_test(
    client: httpx.AsyncClient,
    model: str,
    prompt: str,
    max_tokens: int = 128,
) -> dict[str, float]:
    """Measure first-token latency and generation throughput."""
    start = time.perf_counter()
    resp = await client.post(
        "/v1/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "stream": False,
        },
    )
    resp.raise_for_status()
    elapsed = time.perf_counter() - start
    data = resp.json()
    completion_tokens = data.get("usage", {}).get("completion_tokens", 0)

    return {
        "first_token_latency_ms": elapsed * 1000,
        "tokens_per_second_generation": (completion_tokens / elapsed) if elapsed > 0 else 0.0,
    }
