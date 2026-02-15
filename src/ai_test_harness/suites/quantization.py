"""Quantization test suite — quality drop and memory profiling."""

from __future__ import annotations

from typing import Any

import httpx


async def run_quantization_quality_drop(
    client: httpx.AsyncClient,
    model: str,
    prompts: list[str],
    baseline_outputs: list[str],
    max_tokens: int = 256,
) -> dict[str, float]:
    """Compare quantized model outputs against fp16 baseline outputs."""
    matches = 0

    for prompt, expected in zip(prompts, baseline_outputs):
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
            },
        )
        resp.raise_for_status()
        output = resp.json()["choices"][0]["message"]["content"].strip()
        # Simple exact-match comparison; extend with semantic similarity
        if output == expected:
            matches += 1

    total = len(prompts)
    return {"quality_delta_percent": (1 - matches / total) * 100 if total > 0 else 0.0}


async def run_memory_profile(
    client: httpx.AsyncClient,
    model: str,
    prompt: str,
) -> dict[str, Any]:
    """Query the server for memory usage metrics.

    This assumes the inference server exposes a /metrics or /health endpoint.
    Extend as needed for your backend.
    """
    try:
        resp = await client.get("/metrics")
        resp.raise_for_status()
        return {"raw_metrics": resp.text}
    except httpx.HTTPError:
        return {"raw_metrics": None, "note": "Server does not expose /metrics endpoint."}
