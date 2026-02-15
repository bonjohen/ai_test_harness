"""Code test suite — generate, compile, and run code snippets."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

import httpx


async def run_compile_and_run(
    client: httpx.AsyncClient,
    model: str,
    prompts: list[dict[str, Any]],
    timeout_seconds: int = 30,
) -> dict[str, float]:
    """Generate code and attempt compilation/execution.

    Each prompt dict should have 'text' and 'language' keys.
    Supported languages: python.
    """
    success = 0
    total = len(prompts)

    for prompt in prompts:
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt["text"]}],
                "max_tokens": 1024,
            },
        )
        resp.raise_for_status()
        code = resp.json()["choices"][0]["message"]["content"]

        # Strip markdown fences if present
        if "```" in code:
            lines = code.split("\n")
            in_block = False
            filtered = []
            for line in lines:
                if line.strip().startswith("```"):
                    in_block = not in_block
                    continue
                if in_block:
                    filtered.append(line)
            code = "\n".join(filtered)

        if prompt.get("language", "python") == "python":
            if await _try_run_python(code, timeout_seconds):
                success += 1

    return {"code_compilation_success_percent": (success / total * 100) if total > 0 else 0.0}


async def _try_run_python(code: str, timeout: int) -> bool:
    """Write code to a temp file and execute it."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        tmp_path = Path(f.name)
    try:
        proc = await asyncio.create_subprocess_exec(
            "python", str(tmp_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode == 0
    except (asyncio.TimeoutError, OSError):
        return False
    finally:
        tmp_path.unlink(missing_ok=True)
