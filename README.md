# AI Test Harness

Benchmark and evaluate local LLMs across routing accuracy, tool-call quality, context handling, code generation, reasoning, and instruction following — with a configuration matrix that varies inference parameters and system prompt styles.

## Model Catalog

The catalog (`docs/source.json`) tracks the locally available Ollama models:

| Model | Size | Quant | Type | Primary Role | Context |
|---|---|---|---|---|---|
| llama3:latest | 8.0B | Q4_0 | dense | routing, tool calls | 8K |
| deepseek-r1:latest | — | — | dense | reasoning | 64K |
| qwen3:latest | — | — | dense | routing, structured output, tool calls | 32K |

## Configuration Matrix

Each model is tested under 5 configurations that vary inference parameters and system prompt styles:

| Config | temperature | top_p | num_ctx | system_style |
|---|---|---|---|---|
| **precise** | 0 | 1.0 | 4096 | detailed |
| **creative** | 0.7 | 0.9 | 4096 | detailed |
| **minimal-prompt** | 0 | 1.0 | 4096 | minimal |
| **small-context** | 0 | 1.0 | 2048 | detailed |
| **large-context** | 0 | 1.0 | 8192 | detailed |

System prompt styles:
- **detailed** — verbose system prompts (e.g. "You are a routing classifier...")
- **minimal** — single-sentence system prompts (e.g. "Classify into: search, tool_call, answer, escalate")
- **none** — no system prompt; instruction embedded in user message

3 models x 5 configs = **15 runs**. Each run executes all 11 test suites (~130 test cases).

## Test Suites

| # | Suite | Cases | What It Tests |
|---|---|---|---|
| 1 | **Latency** | 3 prompts + cold start | Short/medium/long generation speed (tok/s), cold-start latency |
| 2 | **Intent Classification** | 25 prompts | Routing into search/tool_call/answer/escalate; strict + loose match |
| 3 | **JSON Conformance** | 12 prompts | Valid JSON output + structural validation (nested objects, arrays, booleans, nulls, enums) |
| 4 | **Needle in Haystack** | 25 (5 needles x 5 positions) | Context recall at 5%, 25%, 50%, 75%, 95% of context window |
| 5 | **Code Generation** | 8 prompts | Python code execution + output correctness validation |
| 6 | **Function Selection** | 15 queries | Pick the correct tool from 10 available tools |
| 7 | **Argument Accuracy** | 8 queries | Extract correct JSON arguments for a given tool signature |
| 8 | **Context Scaling** | 4 checkpoints | Recall at 25/50/75/100% of num_ctx |
| 9 | **Reasoning / Math** | 13 problems | Arithmetic, word problems, logic, sequences, comparisons |
| 10 | **Instruction Following** | 10 tasks | Exact formatting compliance (word count, uppercase, numbered lists) |
| 11 | **Multi-Turn Coherence** | 6 conversations | Name recall, fact tracking, instruction persistence across turns |

## Project Structure

```
ai_test_harness/
├── docs/
│   ├── directives.md          # Coding standards and agent directives
│   └── source.json            # Model catalog and test definitions
├── src/ai_test_harness/
│   ├── __init__.py
│   ├── cli.py                 # CLI entry point (click)
│   ├── config.py              # Configuration and startup validation
│   ├── db.py                  # SQLite with schema versioning
│   ├── logging.py             # Structured JSON logging
│   ├── models.py              # Model registry
│   ├── runner.py              # Test orchestration and result recording
│   └── suites/
│       ├── routing.py         # Intent classification, latency tests
│       ├── tool_calls.py      # JSON conformance, function selection
│       ├── context.py         # Needle-in-haystack, context scaling
│       ├── quantization.py    # Quality drop, memory profiling
│       └── code.py            # Code generation and execution
├── tests/
│   ├── conftest.py
│   ├── test_models.py
│   └── test_db.py
├── run_tests.py               # Self-contained benchmark script
├── pyproject.toml
└── .gitignore
```

## Setup

Requires Python 3.11+ and a running [Ollama](https://ollama.com) server on `http://localhost:11434`.

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
.venv\Scripts\activate      # Windows

# Install in development mode
pip install -e ".[dev]"
```

## Running Benchmarks

```bash
# Run all models, all configs, all suites (~15 runs, ~45-60 min)
python run_tests.py

# Single model, single config
python run_tests.py --model llama3:latest --config precise

# All configs for one model
python run_tests.py --model llama3:latest

# Specific suites only
python run_tests.py --suite latency reasoning_math intent_classification

# Combine filters
python run_tests.py -m llama3:latest -c precise creative -s latency code_generation
```

### CLI Arguments

| Argument | Short | Description |
|---|---|---|
| `--model` | `-m` | Model(s) to test. Defaults to all 3. |
| `--config` | `-c` | Config filter(s) — substring match (e.g. `precise`, `creative`). Defaults to all 5. |
| `--suite` | `-s` | Suite(s) to run (e.g. `latency`, `reasoning_math`). Defaults to all 11. |

### Output

- Per-test-case results printed during execution: `[OK]` / `[MISS]` / `[PASS]` / `[FAIL]`
- Final summary table comparing all configs side-by-side with scores per suite

## Running Unit Tests

```bash
pytest
```
