"""Tool-call test suite — JSON conformance, function selection, argument accuracy."""

from __future__ import annotations

import json
from typing import Any

import httpx


async def run_json_schema_conformance(
    client: httpx.AsyncClient,
    model: str,
    schema: dict[str, Any],
    prompts: list[str],
) -> dict[str, float]:
    """Test whether model outputs valid JSON matching a provided schema."""
    from pydantic import TypeAdapter

    adapter = TypeAdapter(dict)  # basic dict validation; extend with schema
    valid = 0

    for prompt in prompts:
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 512,
            },
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        try:
            parsed = json.loads(content)
            adapter.validate_python(parsed)
            valid += 1
        except (json.JSONDecodeError, Exception):
            pass

    total = len(prompts)
    return {"json_validity_percent": (valid / total * 100) if total > 0 else 0.0}


async def run_function_selection(
    client: httpx.AsyncClient,
    model: str,
    tools: list[dict[str, Any]],
    test_cases: list[dict[str, Any]],
) -> dict[str, float]:
    """Test correct tool selection from a list of tools.

    Each test case should have 'prompt' and 'expected_tool' keys.
    """
    correct = 0

    for case in test_cases:
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": case["prompt"]}],
                "tools": tools,
                "max_tokens": 256,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        tool_calls = data["choices"][0]["message"].get("tool_calls", [])
        if tool_calls and tool_calls[0]["function"]["name"] == case["expected_tool"]:
            correct += 1

    total = len(test_cases)
    return {"function_selection_accuracy_percent": (correct / total * 100) if total > 0 else 0.0}
