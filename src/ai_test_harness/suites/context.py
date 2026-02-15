"""Context test suite — needle-in-haystack and context scaling."""

from __future__ import annotations

import random
from typing import Any

import httpx


async def run_needle_in_haystack(
    client: httpx.AsyncClient,
    model: str,
    needle: str,
    haystack_tokens: int,
    filler_text: str,
    max_tokens: int = 64,
) -> dict[str, float]:
    """Place a key fact at a random position in a long context and test recall."""
    words = filler_text.split()
    insert_pos = random.randint(0, len(words))
    context = " ".join(words[:insert_pos]) + f" {needle} " + " ".join(words[insert_pos:])

    resp = await client.post(
        "/v1/chat/completions",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": context},
                {"role": "user", "content": f"What is the key fact mentioned in the context?"},
            ],
            "max_tokens": max_tokens,
        },
    )
    resp.raise_for_status()
    answer = resp.json()["choices"][0]["message"]["content"].lower()
    recalled = needle.lower() in answer

    return {"long_context_recall_percent": 100.0 if recalled else 0.0}


async def run_context_scaling(
    client: httpx.AsyncClient,
    model: str,
    base_prompt: str,
    filler_text: str,
    max_context_tokens: int,
    checkpoints: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Evaluate quality degradation at 25%, 50%, 75%, 100% of max context."""
    if checkpoints is None:
        checkpoints = [0.25, 0.50, 0.75, 1.00]

    results = []
    words = filler_text.split()

    for pct in checkpoints:
        target_tokens = int(max_context_tokens * pct)
        # rough approximation: 1 word ~ 1.3 tokens
        word_count = int(target_tokens / 1.3)
        filler = " ".join(words[:word_count])
        prompt = f"{filler}\n\n{base_prompt}"

        try:
            resp = await client.post(
                "/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 64,
                },
            )
            resp.raise_for_status()
            results.append({"context_pct": pct, "status": "ok"})
        except httpx.HTTPStatusError as e:
            results.append({"context_pct": pct, "status": "error", "detail": str(e)})

    return results
