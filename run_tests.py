"""Run all test suites against models via Ollama with a configuration matrix."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "http://127.0.0.1:11434"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ModelConfig:
    name: str          # e.g. "llama3:latest"
    label: str         # e.g. "llama3 | temp=0 ctx=4096 precise"
    temperature: float
    top_p: float
    num_ctx: int
    system_style: str  # "minimal", "detailed", "none"
    max_context: int   # model's max context window


def build_configs(model_name: str, max_context: int = 8192) -> list[ModelConfig]:
    """Return the 5 standard configs for a given model."""
    configs = [
        ("precise",        0.0, 1.0, 4096, "detailed"),
        ("creative",       0.7, 0.9, 4096, "detailed"),
        ("minimal-prompt", 0.0, 1.0, 4096, "minimal"),
        ("small-context",  0.0, 1.0, 2048, "detailed"),
        ("large-context",  0.0, 1.0, 8192, "detailed"),
    ]
    return [
        ModelConfig(
            name=model_name,
            label=f"{model_name} | {tag}",
            temperature=temp,
            top_p=tp,
            num_ctx=ctx,
            system_style=style,
            max_context=max_context,
        )
        for tag, temp, tp, ctx, style in configs
    ]


MODELS: list[str] = [
    "llama3:latest",
    "deepseek-r1:latest",
    "qwen3:latest",
]

# ---------------------------------------------------------------------------
# System prompts per style
# ---------------------------------------------------------------------------

SYSTEM_PROMPTS: dict[str, dict[str, str]] = {
    "intent": {
        "detailed": (
            "You are a routing classifier. Classify the user query into exactly one "
            "category. Reply with ONLY the category name, nothing else.\n"
            "Categories: search, tool_call, answer, escalate"
        ),
        "minimal": "Classify into: search, tool_call, answer, escalate",
        "none": "",
    },
    "json": {
        "detailed": (
            "You are a JSON generator. Reply with ONLY valid JSON, no explanation, "
            "no markdown fences."
        ),
        "minimal": "Reply with valid JSON only.",
        "none": "",
    },
    "code": {
        "detailed": (
            "You are a Python code generator. Reply with ONLY executable Python code, "
            "no explanation, no markdown fences."
        ),
        "minimal": "Reply with executable Python code only.",
        "none": "",
    },
    "function": {
        "detailed": (
            "You are a function-calling assistant. Given a user query and a list of "
            "available tools, reply with ONLY the name of the single most appropriate "
            "tool. No explanation."
        ),
        "minimal": "Pick the best tool name from the list. Reply with the name only.",
        "none": "",
    },
    "argument": {
        "detailed": (
            "You are a function-calling assistant. Given a user query and a tool "
            "signature, extract the arguments and reply with ONLY a JSON object of "
            "argument values. No explanation, no markdown fences."
        ),
        "minimal": "Extract tool arguments as JSON only.",
        "none": "",
    },
    "reasoning": {
        "detailed": (
            "You are a precise math and logic solver. Show your reasoning step by step, "
            "then give the final answer on a new line prefixed with 'ANSWER: '."
        ),
        "minimal": "Solve and reply with 'ANSWER: <value>'.",
        "none": "",
    },
    "instruction": {
        "detailed": (
            "You are an instruction-following assistant. Follow the user's formatting "
            "instructions EXACTLY. Do not add extra text."
        ),
        "minimal": "Follow formatting instructions exactly.",
        "none": "",
    },
}


def get_system_prompt(suite: str, config: ModelConfig) -> str | None:
    """Return the system prompt for a suite based on config's system_style."""
    prompts = SYSTEM_PROMPTS.get(suite, {})
    text = prompts.get(config.system_style, prompts.get("detailed", ""))
    if config.system_style == "none" or not text:
        return None
    return text

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks (deepseek-r1 chain-of-thought)."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def strip_markdown_fences(text: str) -> str:
    """Remove ```...``` markdown code fences."""
    lines = text.split("\n")
    out: list[str] = []
    in_fence = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        out.append(line)
    return "\n".join(out).strip()


async def chat(
    client: httpx.AsyncClient,
    config: ModelConfig,
    messages: list[dict[str, str]],
    max_tokens: int = 256,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Send a chat completion request using config params, return parsed response."""
    payload: dict[str, Any] = {
        "model": config.name,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": config.temperature,
        "top_p": config.top_p,
        "options": {"num_ctx": config.num_ctx},
    }
    resp = await client.post(
        "/v1/chat/completions",
        json=payload,
        timeout=httpx.Timeout(timeout, connect=10.0),
    )
    resp.raise_for_status()
    data = resp.json()
    # Strip think tags from content
    content = data["choices"][0]["message"]["content"]
    data["choices"][0]["message"]["content"] = strip_think_tags(content)
    return data


def extract_content(data: dict[str, Any]) -> str:
    """Pull the assistant message content from a chat response."""
    return data["choices"][0]["message"]["content"].strip()


def build_messages(
    system_prompt: str | None,
    user_content: str,
    style: str = "detailed",
    instruction_prefix: str = "",
) -> list[dict[str, str]]:
    """Build the messages list, folding system into user message for 'none' style."""
    msgs: list[dict[str, str]] = []
    if system_prompt:
        msgs.append({"role": "system", "content": system_prompt})
        msgs.append({"role": "user", "content": user_content})
    elif style == "none" and instruction_prefix:
        msgs.append({"role": "user", "content": f"{instruction_prefix}\n\n{user_content}"})
    else:
        msgs.append({"role": "user", "content": user_content})
    return msgs


# ---------------------------------------------------------------------------
# Suite 1: Latency
# ---------------------------------------------------------------------------

async def run_latency_suite(
    client: httpx.AsyncClient, config: ModelConfig
) -> dict[str, Any]:
    print("\n=== Latency Test ===")
    prompts = [
        ("short", "Say hello.", 32),
        ("medium", "Explain what a hash table is in two sentences.", 128),
        ("long", "Write a detailed paragraph about the history of the internet.", 300),
    ]
    results: list[dict[str, Any]] = []

    # Cold start: first request after potential idle
    start = time.perf_counter()
    sys_prompt = get_system_prompt("intent", config)  # light prompt
    msgs = build_messages(sys_prompt, "ping", config.system_style, "Reply with pong.")
    await chat(client, config, msgs, max_tokens=8)
    cold_start = time.perf_counter() - start
    print(f"  Cold-start latency: {cold_start:.3f}s")

    for label, prompt, max_tok in prompts:
        msgs = build_messages(None, prompt)
        start = time.perf_counter()
        data = await chat(client, config, msgs, max_tokens=max_tok)
        elapsed = time.perf_counter() - start
        usage = data.get("usage", {})
        comp_tok = usage.get("completion_tokens", 0)
        prompt_tok = usage.get("prompt_tokens", 0)
        tps = (comp_tok / elapsed) if elapsed > 0 else 0
        results.append({
            "label": label,
            "total_time_s": round(elapsed, 3),
            "prompt_tokens": prompt_tok,
            "completion_tokens": comp_tok,
            "tokens_per_second": round(tps, 1),
        })
        print(f"  [{label}] {elapsed:.3f}s | {comp_tok} tokens | {tps:.1f} tok/s")

    return {
        "cold_start_s": round(cold_start, 3),
        "prompts": results,
        "avg_tps": round(
            sum(r["tokens_per_second"] for r in results) / len(results), 1
        ),
    }


# ---------------------------------------------------------------------------
# Suite 2: Intent Classification
# ---------------------------------------------------------------------------

INTENT_PROMPTS = [
    # search (7)
    {"text": "What is the weather in Tokyo?", "expected": "search"},
    {"text": "Find me flights to Paris next week", "expected": "search"},
    {"text": "What are the latest news headlines?", "expected": "search"},
    {"text": "Look up the population of Canada", "expected": "search"},
    {"text": "Search for vegan restaurants near me", "expected": "search"},
    {"text": "Who won the 2024 Super Bowl?", "expected": "search"},
    {"text": "Find reviews for the iPhone 15", "expected": "search"},
    # tool_call (7)
    {"text": "Send an email to Bob saying hello", "expected": "tool_call"},
    {"text": "Set a reminder for 3pm tomorrow", "expected": "tool_call"},
    {"text": "Create a new calendar event for Monday at 10am", "expected": "tool_call"},
    {"text": "Turn off the living room lights", "expected": "tool_call"},
    {"text": "Add milk to my shopping list", "expected": "tool_call"},
    {"text": "Play my workout playlist on Spotify", "expected": "tool_call"},
    {"text": "Schedule a meeting with Alice for Friday", "expected": "tool_call"},
    # answer (7)
    {"text": "What is 2 + 2?", "expected": "answer"},
    {"text": "Summarize the theory of relativity", "expected": "answer"},
    {"text": "Calculate the square root of 144", "expected": "answer"},
    {"text": "What is the capital of France?", "expected": "answer"},
    {"text": "Explain photosynthesis in simple terms", "expected": "answer"},
    {"text": "How many ounces are in a pound?", "expected": "answer"},
    {"text": "Define the word 'ubiquitous'", "expected": "answer"},
    # escalate (4)
    {"text": "I need to speak to a human agent", "expected": "escalate"},
    {"text": "This is urgent, connect me to support", "expected": "escalate"},
    {"text": "I want to file a formal complaint", "expected": "escalate"},
    {"text": "Transfer me to a live representative now", "expected": "escalate"},
]


async def run_intent_suite(
    client: httpx.AsyncClient, config: ModelConfig
) -> dict[str, Any]:
    print("\n=== Intent Classification ===")
    sys_prompt = get_system_prompt("intent", config)
    correct = 0
    details: list[dict[str, Any]] = []

    for p in INTENT_PROMPTS:
        user_content = p["text"]
        if config.system_style == "none":
            user_content = (
                "Classify into: search, tool_call, answer, escalate. "
                "Reply with the category only.\n\n" + p["text"]
            )
        msgs = build_messages(sys_prompt, user_content)
        data = await chat(client, config, msgs, max_tokens=16)
        raw = extract_content(data).lower()
        # Strict match: exact word
        strict = raw.strip() == p["expected"]
        # Loose match: expected appears anywhere in response
        loose = p["expected"] in raw
        matched = loose
        if matched:
            correct += 1
        status = "OK" if matched else "MISS"
        details.append({
            "text": p["text"],
            "expected": p["expected"],
            "got": raw,
            "strict": strict,
            "loose": loose,
        })
        print(f"  [{status}] \"{p['text'][:50]}\" -> \"{raw}\" (exp: {p['expected']})")

    acc = correct / len(INTENT_PROMPTS) * 100
    strict_count = sum(1 for d in details if d["strict"])
    print(f"  Accuracy (loose): {correct}/{len(INTENT_PROMPTS)} ({acc:.1f}%)")
    print(f"  Accuracy (strict): {strict_count}/{len(INTENT_PROMPTS)} "
          f"({strict_count / len(INTENT_PROMPTS) * 100:.1f}%)")
    return {
        "correct_loose": correct,
        "correct_strict": strict_count,
        "total": len(INTENT_PROMPTS),
        "accuracy_percent": round(acc, 1),
    }


# ---------------------------------------------------------------------------
# Suite 3: JSON Conformance
# ---------------------------------------------------------------------------

JSON_PROMPTS = [
    {
        "prompt": "Return a JSON object with keys 'name' (string) and 'age' (integer).",
        "validate": lambda d: isinstance(d, dict) and "name" in d and "age" in d
            and isinstance(d["name"], str) and isinstance(d["age"], int),
    },
    {
        "prompt": "Return a JSON array of 3 objects each with 'city' (string) and 'population' (integer).",
        "validate": lambda d: isinstance(d, list) and len(d) == 3
            and all(isinstance(o, dict) and "city" in o and "population" in o for o in d),
    },
    {
        "prompt": "Return a JSON object with 'status' (one of 'ok' or 'error') and 'code' (integer).",
        "validate": lambda d: isinstance(d, dict) and d.get("status") in ("ok", "error")
            and isinstance(d.get("code"), int),
    },
    {
        "prompt": "Return a JSON object with 'items' (array of strings) containing 3 fruit names.",
        "validate": lambda d: isinstance(d, dict) and isinstance(d.get("items"), list)
            and len(d["items"]) == 3 and all(isinstance(i, str) for i in d["items"]),
    },
    {
        "prompt": "Return a JSON object with 'x' (number) and 'y' (number) for a coordinate.",
        "validate": lambda d: isinstance(d, dict) and isinstance(d.get("x"), (int, float))
            and isinstance(d.get("y"), (int, float)),
    },
    {
        "prompt": "Return a JSON object with 'active' (boolean) and 'count' (integer).",
        "validate": lambda d: isinstance(d, dict) and isinstance(d.get("active"), bool)
            and isinstance(d.get("count"), int),
    },
    {
        "prompt": "Return a JSON object with 'value' set to null.",
        "validate": lambda d: isinstance(d, dict) and "value" in d and d["value"] is None,
    },
    {
        "prompt": ("Return a JSON object with 'user' containing a nested object with "
                   "'first_name' (string), 'last_name' (string), and 'email' (string)."),
        "validate": lambda d: isinstance(d, dict) and isinstance(d.get("user"), dict)
            and all(k in d["user"] for k in ("first_name", "last_name", "email")),
    },
    {
        "prompt": ("Return a JSON object with 'matrix' containing a 2D array "
                   "(array of arrays of integers), 2 rows and 3 columns."),
        "validate": lambda d: isinstance(d, dict) and isinstance(d.get("matrix"), list)
            and len(d["matrix"]) == 2
            and all(isinstance(row, list) and len(row) == 3 for row in d["matrix"]),
    },
    {
        "prompt": ("Return a JSON object with 'type' (one of 'A', 'B', or 'C') "
                   "and 'tags' (array of strings)."),
        "validate": lambda d: isinstance(d, dict) and d.get("type") in ("A", "B", "C")
            and isinstance(d.get("tags"), list),
    },
    {
        "prompt": "Return a JSON array of 5 integers in ascending order.",
        "validate": lambda d: isinstance(d, list) and len(d) == 5
            and all(isinstance(v, int) for v in d) and d == sorted(d),
    },
    {
        "prompt": ("Return a JSON object with 'config' containing 'debug' (boolean), "
                   "'level' (integer), and 'name' (string)."),
        "validate": lambda d: isinstance(d, dict) and isinstance(d.get("config"), dict)
            and isinstance(d["config"].get("debug"), bool)
            and isinstance(d["config"].get("level"), int)
            and isinstance(d["config"].get("name"), str),
    },
]


async def run_json_suite(
    client: httpx.AsyncClient, config: ModelConfig
) -> dict[str, Any]:
    print("\n=== JSON Schema Conformance ===")
    sys_prompt = get_system_prompt("json", config)
    valid_count = 0
    struct_valid = 0

    for jp in JSON_PROMPTS:
        prompt_text = jp["prompt"]
        if config.system_style == "none":
            prompt_text = "Reply with ONLY valid JSON, no explanation.\n\n" + prompt_text
        msgs = build_messages(sys_prompt, prompt_text)
        data = await chat(client, config, msgs, max_tokens=300)
        content = strip_markdown_fences(extract_content(data))
        try:
            parsed = json.loads(content)
            valid_count += 1
            if jp["validate"](parsed):
                struct_valid += 1
                print(f"  [VALID+STRUCT] {prompt_text[:55]}...")
            else:
                print(f"  [VALID]        {prompt_text[:55]}...")
        except (json.JSONDecodeError, Exception):
            print(f"  [INVALID]      {prompt_text[:55]}...")
            print(f"                 Got: {content[:120]}")

    total = len(JSON_PROMPTS)
    pct_valid = valid_count / total * 100
    pct_struct = struct_valid / total * 100
    print(f"  Valid JSON: {valid_count}/{total} ({pct_valid:.1f}%)")
    print(f"  Structurally correct: {struct_valid}/{total} ({pct_struct:.1f}%)")
    return {
        "valid": valid_count,
        "structurally_correct": struct_valid,
        "total": total,
        "json_validity_percent": round(pct_valid, 1),
        "structural_accuracy_percent": round(pct_struct, 1),
    }


# ---------------------------------------------------------------------------
# Suite 4: Needle in Haystack
# ---------------------------------------------------------------------------

NEEDLES = [
    {"fact": "The secret launch code is AURORA-7749.", "query": "What is the secret launch code?", "answer": "aurora-7749"},
    {"fact": "The password for the vault is DIAMOND-3821.", "query": "What is the vault password?", "answer": "diamond-3821"},
    {"fact": "Project Chimera will launch on March 15th, 2025.", "query": "When will Project Chimera launch?", "answer": "march 15"},
    {"fact": "The contact email is ops-team@example.org.", "query": "What is the contact email?", "answer": "ops-team@example.org"},
    {"fact": "The emergency shutdown phrase is 'blue harvest moon'.", "query": "What is the emergency shutdown phrase?", "answer": "blue harvest moon"},
]

NEEDLE_POSITIONS = [
    ("beginning", 0.05),
    ("quarter", 0.25),
    ("middle", 0.50),
    ("three-quarter", 0.75),
    ("end", 0.95),
]


def build_haystack(needle: str, position_frac: float, num_ctx: int) -> str:
    """Build a filler text with a needle inserted at the given fractional position."""
    filler_sentences = [
        "The quick brown fox jumps over the lazy dog.",
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        "Pack my box with five dozen liquor jugs.",
        "How vexingly quick daft zebras jump.",
        "The five boxing wizards jump quickly.",
        "Bright vixens jump; dozy fowl quack.",
    ]
    # Aim for ~60% of num_ctx in words (rough heuristic: 1 token ~ 0.75 words)
    target_words = int(num_ctx * 0.6 * 0.75)
    # Build filler by cycling through sentences
    filler_words: list[str] = []
    i = 0
    while len(filler_words) < target_words:
        filler_words.extend(filler_sentences[i % len(filler_sentences)].split())
        i += 1
    filler_words = filler_words[:target_words]
    insert_pos = int(len(filler_words) * position_frac)
    needle_words = needle.split()
    final = filler_words[:insert_pos] + needle_words + filler_words[insert_pos:]
    return " ".join(final)


async def run_needle_suite(
    client: httpx.AsyncClient, config: ModelConfig
) -> dict[str, Any]:
    print("\n=== Needle in Haystack ===")
    recalled = 0
    total = 0
    details: list[dict[str, Any]] = []

    for needle_info in NEEDLES:
        for pos_label, pos_frac in NEEDLE_POSITIONS:
            total += 1
            haystack = build_haystack(needle_info["fact"], pos_frac, config.num_ctx)
            msgs: list[dict[str, str]] = [
                {"role": "system", "content": haystack},
                {"role": "user", "content": needle_info["query"]},
            ]
            data = await chat(client, config, msgs, max_tokens=64)
            answer = extract_content(data).lower()
            found = needle_info["answer"].lower() in answer
            if found:
                recalled += 1
            status = "OK" if found else "MISS"
            details.append({
                "needle": needle_info["fact"][:40],
                "position": pos_label,
                "found": found,
            })
            print(f"  [{status}] needle@{pos_label}: {needle_info['fact'][:40]}...")

    pct = recalled / total * 100
    print(f"  Recalled: {recalled}/{total} ({pct:.1f}%)")
    return {
        "recalled": recalled,
        "total": total,
        "recall_percent": round(pct, 1),
        "details": details,
    }


# ---------------------------------------------------------------------------
# Suite 5: Code Generation
# ---------------------------------------------------------------------------

CODE_PROMPTS = [
    {
        "prompt": "Write a Python function called 'fibonacci' that returns the nth Fibonacci number. Then print fibonacci(10).",
        "expected_output": "55",
    },
    {
        "prompt": "Write a Python function that checks if a string is a palindrome. Then print the result for 'racecar'.",
        "expected_output": "True",
    },
    {
        "prompt": "Write a Python function that flattens a nested list. Then print the result for [[1,2],[3,[4,5]]].",
        "expected_output": "[1, 2, 3, 4, 5]",
    },
    {
        "prompt": "Write a Python function 'is_prime(n)' that returns True if n is prime. Print is_prime(17).",
        "expected_output": "True",
    },
    {
        "prompt": "Write a Python function 'factorial(n)' using recursion. Print factorial(6).",
        "expected_output": "720",
    },
    {
        "prompt": "Write a Python function 'reverse_string(s)' that reverses a string without slicing. Print reverse_string('hello').",
        "expected_output": "olleh",
    },
    {
        "prompt": "Write a Python function 'count_vowels(s)' that returns the number of vowels. Print count_vowels('education').",
        "expected_output": "5",
    },
    {
        "prompt": "Write a Python function 'merge_sorted(a, b)' that merges two sorted lists. Print merge_sorted([1,3,5],[2,4,6]).",
        "expected_output": "[1, 2, 3, 4, 5, 6]",
    },
]


async def run_code_suite(
    client: httpx.AsyncClient, config: ModelConfig
) -> dict[str, Any]:
    print("\n=== Code Generation ===")
    sys_prompt = get_system_prompt("code", config)
    run_success = 0
    output_correct = 0

    for cp in CODE_PROMPTS:
        prompt_text = cp["prompt"]
        if config.system_style == "none":
            prompt_text = "Reply with ONLY executable Python code, no explanation.\n\n" + prompt_text
        msgs = build_messages(sys_prompt, prompt_text)
        data = await chat(client, config, msgs, max_tokens=512)
        code = strip_markdown_fences(extract_content(data))

        tmp = Path(tempfile.mktemp(suffix=".py"))
        tmp.write_text(code, encoding="utf-8")
        try:
            proc = subprocess.run(
                ["python", str(tmp)],
                capture_output=True, text=True, timeout=15,
            )
            if proc.returncode == 0:
                run_success += 1
                stdout = proc.stdout.strip()
                if cp["expected_output"] in stdout:
                    output_correct += 1
                    print(f"  [PASS] {cp['prompt'][:55]}...")
                else:
                    print(f"  [RUN_OK] {cp['prompt'][:55]}...")
                    print(f"           Expected '{cp['expected_output']}', got '{stdout[:80]}'")
            else:
                print(f"  [FAIL] {cp['prompt'][:55]}...")
                print(f"         Error: {proc.stderr.strip()[:120]}")
        except subprocess.TimeoutExpired:
            print(f"  [TIMEOUT] {cp['prompt'][:55]}...")
        finally:
            tmp.unlink(missing_ok=True)

    total = len(CODE_PROMPTS)
    pct_run = run_success / total * 100
    pct_correct = output_correct / total * 100
    print(f"  Runs OK: {run_success}/{total} ({pct_run:.1f}%)")
    print(f"  Output correct: {output_correct}/{total} ({pct_correct:.1f}%)")
    return {
        "run_success": run_success,
        "output_correct": output_correct,
        "total": total,
        "run_percent": round(pct_run, 1),
        "correctness_percent": round(pct_correct, 1),
    }


# ---------------------------------------------------------------------------
# Suite 6: Function Selection
# ---------------------------------------------------------------------------

AVAILABLE_TOOLS = [
    "get_weather", "send_email", "search_web", "create_calendar_event",
    "set_reminder", "get_stock_price", "translate_text", "get_directions",
    "play_music", "set_alarm",
]

FUNCTION_SELECTION_CASES = [
    {"query": "What's the weather like in New York?", "expected": "get_weather"},
    {"query": "Send a message to alice@example.com about the meeting", "expected": "send_email"},
    {"query": "Find information about quantum computing", "expected": "search_web"},
    {"query": "Book a meeting with Bob on Tuesday at 2pm", "expected": "create_calendar_event"},
    {"query": "Remind me to buy groceries at 5pm", "expected": "set_reminder"},
    {"query": "How is Apple stock doing today?", "expected": "get_stock_price"},
    {"query": "How do you say 'hello' in Japanese?", "expected": "translate_text"},
    {"query": "How do I get from Boston to New York by car?", "expected": "get_directions"},
    {"query": "Play some jazz music", "expected": "play_music"},
    {"query": "Wake me up at 7am tomorrow", "expected": "set_alarm"},
    {"query": "What's the temperature in London right now?", "expected": "get_weather"},
    {"query": "Email the report to the team", "expected": "send_email"},
    {"query": "Look up the latest research on AI safety", "expected": "search_web"},
    {"query": "Schedule a dentist appointment for next Monday", "expected": "create_calendar_event"},
    {"query": "What is Tesla's current share price?", "expected": "get_stock_price"},
]


async def run_function_selection_suite(
    client: httpx.AsyncClient, config: ModelConfig
) -> dict[str, Any]:
    print("\n=== Function Selection ===")
    sys_prompt = get_system_prompt("function", config)
    tools_list = ", ".join(AVAILABLE_TOOLS)
    correct = 0

    for case in FUNCTION_SELECTION_CASES:
        user_text = f"Available tools: [{tools_list}]\n\nUser query: {case['query']}"
        if config.system_style == "none":
            user_text = (
                "Pick the best tool name from the list. Reply with the name only.\n\n"
                + user_text
            )
        msgs = build_messages(sys_prompt, user_text)
        data = await chat(client, config, msgs, max_tokens=32)
        raw = extract_content(data).lower().strip()
        expected = case["expected"].lower()
        matched = expected in raw
        if matched:
            correct += 1
        status = "OK" if matched else "MISS"
        print(f"  [{status}] \"{case['query'][:45]}\" -> \"{raw}\" (exp: {expected})")

    total = len(FUNCTION_SELECTION_CASES)
    pct = correct / total * 100
    print(f"  Accuracy: {correct}/{total} ({pct:.1f}%)")
    return {
        "correct": correct,
        "total": total,
        "accuracy_percent": round(pct, 1),
    }


# ---------------------------------------------------------------------------
# Suite 7: Argument Accuracy
# ---------------------------------------------------------------------------

ARGUMENT_CASES = [
    {
        "query": "Send an email to bob@example.com with subject 'Meeting' and body 'See you at 3pm'",
        "tool": "send_email(to: str, subject: str, body: str)",
        "expected": {"to": "bob@example.com", "subject": "Meeting", "body": "See you at 3pm"},
    },
    {
        "query": "Set a reminder for 'Buy milk' at 5:30 PM",
        "tool": "set_reminder(text: str, time: str)",
        "expected": {"text": "Buy milk", "time": "5:30 PM"},
    },
    {
        "query": "Get weather for latitude 40.7128 and longitude -74.0060",
        "tool": "get_weather(lat: float, lon: float)",
        "expected": {"lat": 40.7128, "lon": -74.006},
    },
    {
        "query": "Translate 'Good morning' from English to Spanish",
        "tool": "translate_text(text: str, source_lang: str, target_lang: str)",
        "expected": {"text": "Good morning", "source_lang": "English", "target_lang": "Spanish"},
    },
    {
        "query": "Search the web for 'best python frameworks' with max 5 results",
        "tool": "search_web(query: str, max_results: int)",
        "expected": {"query": "best python frameworks", "max_results": 5},
    },
    {
        "query": "Create a calendar event 'Team Standup' on 2025-03-01 at 09:00 for 30 minutes",
        "tool": "create_event(title: str, date: str, time: str, duration_minutes: int)",
        "expected": {"title": "Team Standup", "date": "2025-03-01", "time": "09:00", "duration_minutes": 30},
    },
    {
        "query": "Get directions from 'San Francisco' to 'Los Angeles' by car",
        "tool": "get_directions(origin: str, destination: str, mode: str)",
        "expected": {"origin": "San Francisco", "destination": "Los Angeles", "mode": "car"},
    },
    {
        "query": "Set alarm for 7:00 AM with label 'Wake up' repeating on weekdays",
        "tool": "set_alarm(time: str, label: str, repeat: str)",
        "expected": {"time": "7:00 AM", "label": "Wake up"},
    },
]


async def run_argument_suite(
    client: httpx.AsyncClient, config: ModelConfig
) -> dict[str, Any]:
    print("\n=== Argument Accuracy ===")
    sys_prompt = get_system_prompt("argument", config)
    correct = 0

    for case in ARGUMENT_CASES:
        user_text = f"Tool signature: {case['tool']}\n\nUser query: {case['query']}"
        if config.system_style == "none":
            user_text = (
                "Extract tool arguments as a JSON object. No explanation.\n\n"
                + user_text
            )
        msgs = build_messages(sys_prompt, user_text)
        data = await chat(client, config, msgs, max_tokens=200)
        raw = strip_markdown_fences(extract_content(data))
        try:
            parsed = json.loads(raw)
            # Check that all expected keys are present with correct values
            all_match = True
            for key, val in case["expected"].items():
                got = parsed.get(key)
                if isinstance(val, float):
                    all_match = all_match and isinstance(got, (int, float)) and abs(got - val) < 0.01
                elif isinstance(val, int):
                    all_match = all_match and got == val
                else:
                    all_match = all_match and isinstance(got, str) and val.lower() in got.lower()
            if all_match:
                correct += 1
                print(f"  [OK] {case['query'][:55]}...")
            else:
                print(f"  [MISS] {case['query'][:55]}...")
                print(f"         Expected: {case['expected']}")
                print(f"         Got:      {parsed}")
        except (json.JSONDecodeError, Exception):
            print(f"  [FAIL] {case['query'][:55]}...")
            print(f"         Raw: {raw[:120]}")

    total = len(ARGUMENT_CASES)
    pct = correct / total * 100
    print(f"  Accuracy: {correct}/{total} ({pct:.1f}%)")
    return {
        "correct": correct,
        "total": total,
        "accuracy_percent": round(pct, 1),
    }


# ---------------------------------------------------------------------------
# Suite 8: Context Scaling
# ---------------------------------------------------------------------------

async def run_context_scaling_suite(
    client: httpx.AsyncClient, config: ModelConfig
) -> dict[str, Any]:
    print("\n=== Context Scaling ===")
    checkpoints = [0.25, 0.50, 0.75, 1.00]
    secret = "The project codename is FALCON-ECHO-42."
    query = "What is the project codename?"
    answer_key = "falcon-echo-42"
    results: list[dict[str, Any]] = []

    for frac in checkpoints:
        target_ctx = int(config.num_ctx * frac)
        haystack = build_haystack(secret, 0.5, target_ctx)
        msgs: list[dict[str, str]] = [
            {"role": "system", "content": haystack},
            {"role": "user", "content": query},
        ]
        try:
            data = await chat(client, config, msgs, max_tokens=64, timeout=120.0)
            content = extract_content(data).lower()
            found = answer_key in content
            status = "OK" if found else "MISS"
            results.append({"fraction": frac, "ctx_tokens": target_ctx, "recalled": found})
            print(f"  [{status}] {int(frac*100)}% of num_ctx ({target_ctx} tokens)")
        except Exception as e:
            results.append({"fraction": frac, "ctx_tokens": target_ctx, "recalled": False, "error": str(e)})
            print(f"  [ERR] {int(frac*100)}% of num_ctx ({target_ctx} tokens): {e}")

    recalled = sum(1 for r in results if r["recalled"])
    total = len(results)
    pct = recalled / total * 100
    print(f"  Recalled: {recalled}/{total} ({pct:.1f}%)")
    return {
        "recalled": recalled,
        "total": total,
        "recall_percent": round(pct, 1),
        "checkpoints": results,
    }


# ---------------------------------------------------------------------------
# Suite 9: Reasoning / Math
# ---------------------------------------------------------------------------

REASONING_PROBLEMS = [
    # Arithmetic (3)
    {"question": "What is 247 + 389?", "answer": "636"},
    {"question": "What is 15 * 23?", "answer": "345"},
    {"question": "What is 1000 - 437?", "answer": "563"},
    # Word problems (3)
    {"question": "A store sells apples for $2 each and oranges for $3 each. If I buy 4 apples and 5 oranges, how much do I pay?", "answer": "23"},
    {"question": "A train travels at 60 mph. How far does it go in 2.5 hours?", "answer": "150"},
    {"question": "If 3 workers can paint a house in 6 days, how many days would it take 6 workers?", "answer": "3"},
    # Logic (3)
    {"question": "All cats are animals. Some animals are pets. Can we conclude that all cats are pets? Answer yes or no.", "answer": "no"},
    {"question": "If it is raining, the ground is wet. The ground is wet. Is it necessarily raining? Answer yes or no.", "answer": "no"},
    {"question": "A is taller than B. B is taller than C. Who is the shortest?", "answer": "c"},
    # Sequences (2)
    {"question": "What is the next number in the sequence: 2, 6, 12, 20, 30, ?", "answer": "42"},
    {"question": "What is the next number: 1, 1, 2, 3, 5, 8, ?", "answer": "13"},
    # Comparisons (2)
    {"question": "Which is larger: 3/7 or 5/12? Reply with just the fraction.", "answer": "3/7"},
    {"question": "Sort these numbers from smallest to largest: 0.5, 0.05, 0.55, 0.005", "answer": "0.005"},
]


async def run_reasoning_suite(
    client: httpx.AsyncClient, config: ModelConfig
) -> dict[str, Any]:
    print("\n=== Reasoning / Math ===")
    sys_prompt = get_system_prompt("reasoning", config)
    correct = 0

    for prob in REASONING_PROBLEMS:
        user_text = prob["question"]
        if config.system_style == "none":
            user_text = "Solve and give the final answer after 'ANSWER: '.\n\n" + user_text
        msgs = build_messages(sys_prompt, user_text)
        data = await chat(client, config, msgs, max_tokens=300)
        raw = extract_content(data).lower()
        # Try to extract answer after "ANSWER:" prefix
        answer_match = re.search(r"answer:\s*(.+)", raw)
        check_text = answer_match.group(1).strip() if answer_match else raw
        expected = prob["answer"].lower()
        found = expected in check_text or expected in raw
        if found:
            correct += 1
        status = "OK" if found else "MISS"
        short_answer = check_text[:60] if answer_match else raw[-60:]
        print(f"  [{status}] \"{prob['question'][:45]}\" -> \"{short_answer}\" (exp: {expected})")

    total = len(REASONING_PROBLEMS)
    pct = correct / total * 100
    print(f"  Accuracy: {correct}/{total} ({pct:.1f}%)")
    return {
        "correct": correct,
        "total": total,
        "accuracy_percent": round(pct, 1),
    }


# ---------------------------------------------------------------------------
# Suite 10: Instruction Following
# ---------------------------------------------------------------------------

INSTRUCTION_CASES = [
    {
        "instruction": "Reply with exactly 3 words.",
        "validate": lambda r: len(r.split()) == 3,
        "desc": "exactly 3 words",
    },
    {
        "instruction": "Reply with your answer in ALL UPPERCASE letters.",
        "validate": lambda r: r == r.upper() and len(r) > 2,
        "desc": "all uppercase",
    },
    {
        "instruction": "List 3 colors, each on a new line. No numbering, no bullets.",
        "validate": lambda r: len([l for l in r.strip().split("\n") if l.strip()]) == 3,
        "desc": "3 colors on separate lines",
    },
    {
        "instruction": "Reply with a numbered list of 5 items (fruits). Use the format '1. item'.",
        "validate": lambda r: all(f"{i}." in r for i in range(1, 6)),
        "desc": "numbered list 1-5",
    },
    {
        "instruction": "Reply with exactly one sentence that ends with a period.",
        "validate": lambda r: r.count(".") == 1 and r.strip().endswith("."),
        "desc": "one sentence ending with period",
    },
    {
        "instruction": "Reply with 'YES' and nothing else.",
        "validate": lambda r: r.strip().upper() == "YES",
        "desc": "just YES",
    },
    {
        "instruction": "Reply with a single integer between 1 and 10.",
        "validate": lambda r: r.strip().isdigit() and 1 <= int(r.strip()) <= 10,
        "desc": "single integer 1-10",
    },
    {
        "instruction": "Reply with exactly 2 sentences. The first must start with 'The' and the second with 'It'.",
        "validate": lambda r: r.strip().startswith("The") and "It " in r or "It'" in r,
        "desc": "2 sentences starting with The/It",
    },
    {
        "instruction": "Reply with a comma-separated list of exactly 4 animals.",
        "validate": lambda r: len([x for x in r.split(",") if x.strip()]) == 4,
        "desc": "4 comma-separated animals",
    },
    {
        "instruction": "Reply with the word 'hello' repeated exactly 3 times, separated by spaces.",
        "validate": lambda r: r.strip().lower() == "hello hello hello",
        "desc": "hello hello hello",
    },
]


async def run_instruction_suite(
    client: httpx.AsyncClient, config: ModelConfig
) -> dict[str, Any]:
    print("\n=== Instruction Following ===")
    sys_prompt = get_system_prompt("instruction", config)
    correct = 0

    for case in INSTRUCTION_CASES:
        user_text = case["instruction"]
        if config.system_style == "none":
            user_text = "Follow these instructions exactly.\n\n" + user_text
        msgs = build_messages(sys_prompt, user_text)
        data = await chat(client, config, msgs, max_tokens=128)
        raw = extract_content(data)
        passed = case["validate"](raw)
        if passed:
            correct += 1
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {case['desc']}: \"{raw[:60]}\"")

    total = len(INSTRUCTION_CASES)
    pct = correct / total * 100
    print(f"  Passed: {correct}/{total} ({pct:.1f}%)")
    return {
        "correct": correct,
        "total": total,
        "accuracy_percent": round(pct, 1),
    }


# ---------------------------------------------------------------------------
# Suite 11: Multi-Turn Coherence
# ---------------------------------------------------------------------------

MULTI_TURN_CASES = [
    {
        "desc": "Name recall",
        "turns": [
            {"role": "user", "content": "My name is Alice."},
            {"role": "assistant", "content": "Nice to meet you, Alice!"},
            {"role": "user", "content": "What is my name?"},
        ],
        "validate": lambda r: "alice" in r.lower(),
    },
    {
        "desc": "Fact tracking",
        "turns": [
            {"role": "user", "content": "I have a dog named Max."},
            {"role": "assistant", "content": "That's a great name for a dog!"},
            {"role": "user", "content": "I also have a cat named Luna."},
            {"role": "assistant", "content": "Max and Luna, lovely pets!"},
            {"role": "user", "content": "What are my pets' names?"},
        ],
        "validate": lambda r: "max" in r.lower() and "luna" in r.lower(),
    },
    {
        "desc": "Instruction persistence",
        "turns": [
            {"role": "user", "content": "From now on, end every reply with '-- AI'."},
            {"role": "assistant", "content": "Understood, I will do that. -- AI"},
            {"role": "user", "content": "What is 2 + 2?"},
        ],
        "validate": lambda r: "-- ai" in r.lower() or "--ai" in r.lower(),
    },
    {
        "desc": "Context accumulation",
        "turns": [
            {"role": "user", "content": "Remember: the sky is green in my world."},
            {"role": "assistant", "content": "Got it, the sky is green in your world."},
            {"role": "user", "content": "What color is the sky in my world?"},
        ],
        "validate": lambda r: "green" in r.lower(),
    },
    {
        "desc": "Number tracking",
        "turns": [
            {"role": "user", "content": "I'm thinking of the number 42."},
            {"role": "assistant", "content": "Noted, your number is 42."},
            {"role": "user", "content": "Now multiply my number by 2."},
            {"role": "assistant", "content": "42 times 2 is 84."},
            {"role": "user", "content": "What was my original number?"},
        ],
        "validate": lambda r: "42" in r,
    },
    {
        "desc": "Preference recall",
        "turns": [
            {"role": "user", "content": "My favorite color is blue and my favorite food is pizza."},
            {"role": "assistant", "content": "Blue and pizza, noted!"},
            {"role": "user", "content": "What is my favorite color?"},
        ],
        "validate": lambda r: "blue" in r.lower(),
    },
]


async def run_multi_turn_suite(
    client: httpx.AsyncClient, config: ModelConfig
) -> dict[str, Any]:
    print("\n=== Multi-Turn Coherence ===")
    correct = 0

    for case in MULTI_TURN_CASES:
        msgs = list(case["turns"])
        data = await chat(client, config, msgs, max_tokens=128)
        raw = extract_content(data)
        passed = case["validate"](raw)
        if passed:
            correct += 1
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {case['desc']}: \"{raw[:60]}\"")

    total = len(MULTI_TURN_CASES)
    pct = correct / total * 100
    print(f"  Passed: {correct}/{total} ({pct:.1f}%)")
    return {
        "correct": correct,
        "total": total,
        "accuracy_percent": round(pct, 1),
    }


# ---------------------------------------------------------------------------
# Suite registry
# ---------------------------------------------------------------------------

SUITES: dict[str, Any] = {
    "latency": run_latency_suite,
    "intent_classification": run_intent_suite,
    "json_conformance": run_json_suite,
    "needle_in_haystack": run_needle_suite,
    "code_generation": run_code_suite,
    "function_selection": run_function_selection_suite,
    "argument_accuracy": run_argument_suite,
    "context_scaling": run_context_scaling_suite,
    "reasoning_math": run_reasoning_suite,
    "instruction_following": run_instruction_suite,
    "multi_turn_coherence": run_multi_turn_suite,
}


# ---------------------------------------------------------------------------
# Summary Table
# ---------------------------------------------------------------------------

def get_suite_score(suite_name: str, result: dict[str, Any]) -> str:
    """Extract a display score from a suite result dict."""
    if "error" in result:
        return "ERR"
    if suite_name == "latency":
        return f"{result.get('avg_tps', '?')} tok/s"
    for key in ("accuracy_percent", "recall_percent", "correctness_percent",
                "json_validity_percent", "run_percent"):
        if key in result:
            return f"{result[key]}%"
    return "?"


def print_summary_table(all_results: dict[str, dict[str, Any]]) -> None:
    """Print a cross-config comparison table."""
    if not all_results:
        return

    suite_names = list(SUITES.keys())
    config_labels = list(all_results.keys())

    # Column widths
    suite_col_w = max(len(s) for s in suite_names) + 2
    data_col_w = max(16, *(len(lbl) for lbl in config_labels)) + 2

    # Header
    print("\n" + "=" * 80)
    print("SUMMARY TABLE")
    print("=" * 80)
    header = "Suite".ljust(suite_col_w)
    for lbl in config_labels:
        header += lbl[:data_col_w - 1].center(data_col_w)
    print(header)
    print("-" * (suite_col_w + data_col_w * len(config_labels)))

    # Rows
    for suite in suite_names:
        row = suite.ljust(suite_col_w)
        for lbl in config_labels:
            suite_result = all_results[lbl].get(suite, {})
            score = get_suite_score(suite, suite_result)
            row += score.center(data_col_w)
        print(row)

    print("=" * (suite_col_w + data_col_w * len(config_labels)))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_config(
    client: httpx.AsyncClient,
    config: ModelConfig,
    suite_filter: list[str] | None = None,
) -> dict[str, Any]:
    """Run all (or filtered) suites for a single config."""
    results: dict[str, Any] = {}
    suites_to_run = suite_filter if suite_filter else list(SUITES.keys())

    print(f"\n{'#' * 70}")
    print(f"# CONFIG: {config.label}")
    print(f"#   temperature={config.temperature}  top_p={config.top_p}  "
          f"num_ctx={config.num_ctx}  system_style={config.system_style}")
    print(f"{'#' * 70}")

    for suite_name in suites_to_run:
        if suite_name not in SUITES:
            print(f"\n  [WARN] Unknown suite: {suite_name}, skipping")
            continue
        try:
            result = await SUITES[suite_name](client, config)
            results[suite_name] = result
        except Exception as e:
            print(f"\n  [ERROR] Suite '{suite_name}' failed: {e}")
            results[suite_name] = {"error": str(e)}

    return results


async def run_all(
    model_filter: list[str] | None = None,
    config_filter: list[str] | None = None,
    suite_filter: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Run the full configuration matrix."""
    all_results: dict[str, dict[str, Any]] = {}
    timeout = httpx.Timeout(120.0, connect=10.0)

    # Build all configs
    models_to_test = model_filter if model_filter else MODELS
    all_configs: list[ModelConfig] = []
    for model_name in models_to_test:
        configs = build_configs(model_name)
        if config_filter:
            configs = [c for c in configs if any(f in c.label for f in config_filter)]
        all_configs.extend(configs)

    if not all_configs:
        print("No matching configs found. Available models:", MODELS)
        print("Config tags: precise, creative, minimal-prompt, small-context, large-context")
        return {}

    print(f"\nWill run {len(all_configs)} config(s), "
          f"{len(suite_filter) if suite_filter else len(SUITES)} suite(s) each.")
    print(f"Configs: {[c.label for c in all_configs]}")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=timeout) as client:
        for config in all_configs:
            results = await run_config(client, config, suite_filter)
            all_results[config.label] = results

    # Summary
    print_summary_table(all_results)
    return all_results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Test Harness — run LLM test suites with a configuration matrix"
    )
    parser.add_argument(
        "--model", "-m",
        nargs="*",
        default=None,
        help="Model(s) to test (e.g. llama3:latest). Defaults to all.",
    )
    parser.add_argument(
        "--config", "-c",
        nargs="*",
        default=None,
        help="Config filter(s) — substring match on config label "
             "(e.g. 'precise', 'creative'). Defaults to all.",
    )
    parser.add_argument(
        "--suite", "-s",
        nargs="*",
        default=None,
        help="Suite(s) to run (e.g. latency intent_classification). Defaults to all.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(run_all(
        model_filter=args.model,
        config_filter=args.config,
        suite_filter=args.suite,
    ))
