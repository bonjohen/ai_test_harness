# Agent Directives

These directives govern how code is written, reviewed, and maintained in this project. Follow them when writing new code, modifying existing code, or reviewing changes.

---

## 1. Read Before You Write

- Read the project structure, entry points, config files, and dependency manifest before making changes.
- Read all files you intend to modify and their callers before proposing edits.
- Identify the critical paths (data flow, auth flow, API boundaries, state mutations) and understand how your change interacts with them.

## 2. Be Specific, Not General

- When identifying issues, cite the file path and line number. Vague findings like "could be improved" are not acceptable.
- When proposing fixes, state the exact change: which function, which parameter, which line.
- When reporting risk, describe what concretely goes wrong — not hypothetical categories of badness.

## 3. Prioritize by Blast Radius

- Rank issues by `blast radius * likelihood`, not by ease of fix.
- A silent data corruption bug in a billing function outranks a cosmetic naming inconsistency, regardless of how easy the rename is.
- Critical: fix before release. High: fix this sprint. Medium: tech debt backlog. Low: hardening.

## 4. Fail Fast on Invalid State

- Validate configuration at startup. Missing keys, malformed values, and absent environment variables must cause an immediate, clear error — not a runtime `KeyError` on the first request.
- Validate inputs at system boundaries (user input, external APIs, config files). Trust internal code and framework guarantees.
- Do not add defensive validation for scenarios that cannot happen within the application's own logic.

## 5. Never Block the Event Loop

- All synchronous I/O (database queries, file reads, CPU-heavy computation) inside async endpoints must be offloaded via `asyncio.to_thread()` or equivalent.
- HTTP clients must be shared across requests (created once in lifespan, stored in `app.state`). Never create a new client per request.
- Database connections must set `PRAGMA busy_timeout` to avoid immediate failure under contention.

## 6. Close What You Open

- Every resource (DB connection, file handle, HTTP client) must be released in all code paths, including error paths.
- Use `try/finally` or context managers. If the code between `open()` and `close()` can raise, the resource will leak.
- A leaked SQLite connection holds a write lock. Accumulated leaks deadlock the database.

## 7. Secure by Default

- Use parameterized queries for all SQL. Never construct queries via string concatenation or interpolation.
- Use `hmac.compare_digest()` for all secret comparisons. Python `==` short-circuits and leaks timing information.
- Read secrets from environment variables, never from source code or config files committed to the repo.
- Use `yaml.safe_load()`, never `yaml.load()`.
- Enforce `PRAGMA foreign_keys=ON` on every SQLite connection.

## 8. Authenticate and Authorize Completely

- Authentication must verify both the key validity and the agent's status. A disabled agent with a valid key must not pass auth.
- Rate-limit authentication failures. Unlimited attempts enable brute-force attacks.
- Include a `request_id` in every error response so clients and operators can correlate failures.

## 9. Account for Failure

- When a pre-paid resource (wallet deduction) is consumed before an operation, refund it if the operation fails.
- Upstream HTTP errors, timeouts, and connection failures must be caught and converted to structured error responses — not unhandled 500s.
- Logging failures must not crash the request. Wrap non-critical side effects (audit logging, metrics) in `try/except`.

## 10. Log Every Decision

- Use structured JSON logging (`log_event()`) at every significant decision point: auth failure, wallet deduction, routing decision, upstream error, request completion.
- Include `request_id` and `agent_id` in every log event for correlation.
- Never log secrets, API keys, or raw tokens.

## 11. Track Schema and Dependencies

- The database schema must have a `schema_version` table. Check version at startup; apply incremental migrations.
- All dependencies must have version range constraints (lower and upper bounds) in `pyproject.toml`.
- A pinned lockfile (`requirements.txt`) must be committed and kept up to date.

## 12. Test Behavior, Not Implementation

- Tests must verify observable behavior through public interfaces, not internal implementation details.
- Test both the happy path and the error paths: insufficient balance, invalid auth, upstream failure, missing config.
- Critical business flows (authentication, billing, request proxying) must have end-to-end test coverage that verifies side effects (wallet balance adjusted, `request_log` row written).
- Do not write tests that break on refactors because they mock internals.

## 13. No Padding, No Speculation

- Do not add features, abstractions, or "improvements" beyond what was requested.
- Do not suggest refactors unless they are required to fix a real, concrete issue.
- Do not create helpers or utilities for one-time operations. Three similar lines are better than a premature abstraction.
- If a category of analysis has no real findings, skip it entirely.

## 14. Document What the Schema Promises

- If a schema column exists but application code does not enforce it, mark it explicitly as a placeholder (e.g., `-- v2 placeholder`).
- Operators will assume that defined columns (monthly limits, agent policies, status flags) are enforced. False promises are worse than missing features.

## 15. Stress-Test Your Assumptions

When evaluating any module, ask:

- What happens when input volume is 10x current?
- What happens when this operation fails halfway through?
- What does this code assume that isn't enforced by types or contracts?
- What's the blast radius if this component is wrong?
- Is this testable in isolation, or is it tightly coupled?

These questions catch the issues that line-by-line review misses.
