# Agent Harness Gaps — Design Spec

**Date:** 2026-03-29
**Scope:** Close the 4 identified agent harness gaps in Mission Control
**Constraint:** A2A protocol layer (agent cards, JSON-RPC interface) must not change in breaking ways
**Deployment targets:** Local dev, Docker Compose, cloud
**Testing:** Integration tests using pytest-asyncio + pytest-httpx pattern

---

## Overview

Mission Control is substantially built with agent harness principles in mind but has 4 gaps:

1. Human-in-the-loop (HITL) — `input-required` state is silently ignored
2. No retry logic for failed tasks
3. No output validation or guardrails on agent responses
4. No token budget management for long-running agents
5. No rate limiting on task dispatch
6. No declarative pipeline chaining between agents

These are addressed in two parallel tracks:

- **Track 1 — Control Plane:** HITL, retries, rate limiting, pipeline API
- **Track 2 — Per-Agent:** Output schema validation, token budget management

---

## Track 1 — Control Plane

### Phase 1A: HITL + Retries

**Files affected:** `control_plane/routes.py`, `control_plane/task_store.py`

#### HITL (Human-in-the-Loop)

The `input-required` A2A task state allows an agent to pause mid-execution and request additional input from the user. Currently this state is silently ignored in `_run_task` (`routes.py:211`).

**Changes:**

- Handle `input-required` in `_run_task`: when the agent emits this state, stop streaming, save the pending agent prompt to the task record, and exit the background coroutine cleanly
- Add `resumed_inputs: list[str]` field to `TaskRecord` to track all human replies across turns
- Add `pending_input_prompt: str` field to `TaskRecord` to expose the agent's question to the caller
- Add `POST /tasks/{task_id}/resume` endpoint:
  - Accepts `{"text": "..."}` body
  - Validates task is in `input-required` state; returns `409` otherwise
  - Appends text to `resumed_inputs`, clears `pending_input_prompt`
  - Re-dispatches to the same `instance_url` that owns the task, passing full conversation history
  - Resumes streaming via `_run_task`

**State machine addition:**
```
submitted → working → input-required → working → completed/failed/canceled
```

**Task record additions:**
```python
resumed_inputs: list[str] = []
pending_input_prompt: str = ""
```

#### Retry Policies

On transient failures (`ConnectError`, `TimeoutException`), the control plane currently marks the task `FAILED` immediately. Add configurable retry logic.

**Changes:**

- Add `RetryConfig` dataclass:
  ```python
  @dataclass
  class RetryConfig:
      max_retries: int = 2        # from env MAX_RETRIES, default 2
      retry_delay_s: float = 1.0  # from env RETRY_DELAY_S, default 1.0
  ```
- Wrap `ConnectError` and `TimeoutException` branches in `_run_task` with a retry loop using `asyncio.sleep(retry_delay_s * attempt)`
- Track `retry_count: int` on `TaskRecord` for observability
- Only retry transient errors — `A2AError` and `HTTPStatusError` fail immediately (these indicate agent-side problems, not connectivity)
- After exhausting retries, mark `FAILED` with `f"Failed after {max_retries} retries: {error}"`

**New env vars:**
| Variable | Default | Description |
|---|---|---|
| `MAX_RETRIES` | `2` | Max retry attempts for transient task failures |
| `RETRY_DELAY_S` | `1.0` | Base delay in seconds between retries (linear backoff) |

---

### Phase 2A: Rate Limiting

**Files affected:** `control_plane/registry.py`, `control_plane/routes.py`

Prevent a single agent type from being overwhelmed by concurrent task submissions.

**Changes:**

- Add `max_concurrent: int = 10` to `AgentType`, populated from agent card metadata on registration (agents declare it in their card's `capabilities` or `extensions` field; defaults to `10` if absent)
- Add `asyncio.Semaphore` per `AgentType` in the registry, keyed to `max_concurrent`
- In `dispatch_task`: attempt non-blocking semaphore acquire (`acquire()` with `asyncio.wait_for(..., timeout=0)`)
  - If acquired: proceed, release in `_run_task` finally block
  - If not acquired: return `HTTP 429` with `Retry-After: 5` header
- For Redis-scaled deployments: use a Redis counter with TTL as a distributed rate limiter (increment on dispatch, decrement on task completion; reject if counter ≥ `max_concurrent`)
  - Falls back to in-memory semaphore when `REDIS_URL` is not set

**New agent card field (optional, non-breaking):**
```json
{
  "capabilities": {
    "max_concurrent_tasks": 10
  }
}
```

---

### Phase 3A: Pipeline API

**Files affected:** `control_plane/routes.py`, `control_plane/task_store.py` (new `pipeline_store.py`)

A declarative way to chain tasks: task A's output automatically becomes task B's input.

**Data model:**

```python
@dataclass
class PipelineStep:
    agent_id: str
    input_template: str   # supports {{output}} placeholder
    task_id: str = ""     # populated at runtime
    state: str = "pending"

@dataclass
class PipelineRecord:
    pipeline_id: str
    steps: list[PipelineStep]
    state: str            # pending / running / completed / failed
    created_at: float
```

**Endpoints:**

- `POST /pipelines` — accepts `{"steps": [{"agent_id": "...", "input_template": "..."}]}`
  - Validates all `agent_id`s exist in registry
  - Creates `PipelineRecord`, dispatches step 0 immediately
  - Returns `202` with `pipeline_id`
- `GET /pipelines/{pipeline_id}` — returns pipeline record with all step states
- `GET /pipelines` — lists all pipelines

**Execution:**

- After each step's task reaches `completed`, the pipeline runner substitutes `{{output}}` in the next step's `input_template` with `output_text`, then dispatches the next task
- On any step `failed`, the pipeline is marked `failed` and remaining steps are not dispatched
- Pipeline runner is an `asyncio.Task` that polls via the pub/sub broker (reuses existing infrastructure — no new polling loop needed)

**Storage:** In-memory by default (same pattern as `TaskStore`). PostgreSQL backend added if `DATABASE_URL` is set.

---

### Phase 4A: Integration + Polish

**Files affected:** `dashboard/`, `control_plane/routes.py`, `docker-compose.yml`, `CLAUDE.md`

- Dashboard: resume button on tasks in `input-required` state, pipeline status panel showing step-by-step progress
- Add `MAX_RETRIES`, `RETRY_DELAY_S` to `docker-compose.yml` env blocks and `.env.template`
- Integration tests for all new endpoints: HITL resume flow, retry exhaustion, 429 rate limit response, pipeline chaining
- Update `CLAUDE.md` environment variable table with new vars

---

## Track 2 — Per-Agent

### Phase 1B: Output Schema Validation

**Files affected:** `agents/base/executor.py`, structured agents (Relevancy, Extraction, Probability)

Agents that return structured JSON can declare a schema; the base executor enforces it automatically.

**Changes to `LangGraphA2AExecutor`:**

- Add optional class attribute: `output_schema: dict | None = None`
- After `format_output()` resolves the output string, if `output_schema` is set:
  - Attempt `json.loads(output_text)` — if it fails, emit `failed` with `OutputValidationError: output is not valid JSON`
  - Run `jsonschema.validate(parsed, self.output_schema)` — if it fails, emit `failed` with `OutputValidationError: {validation_message}`
- If `output_schema` is `None` (default), skip validation entirely — zero behavior change for text-output agents

**Agents that declare schemas:**

| Agent | Schema covers |
|---|---|
| Relevancy | `verdict`, `score`, `reasoning` fields |
| Extraction | `entities`, `events`, `relationships` arrays |
| Probability | `probability`, `confidence_interval`, `disagreements` fields |

**New dependency:** `jsonschema` (add to `requirements.txt`)

---

### Phase 2B: Token Budget Management

**Files affected:** `agents/base/executor.py`, LLM-heavy agents (Lead Analyst, Specialist, Probability)

Prevent silent LLM degradation or hard failures when graph state grows too large for the context window.

**Changes to `LangGraphA2AExecutor`:**

- Add optional class attribute: `max_context_tokens: int | None = None`
- Add `_count_tokens(state: dict) -> int` helper using `tiktoken` (falls back to `len(str(state)) // 4` if tiktoken unavailable for a given model)
- In the `astream` event loop, after each node emits an update, check accumulated token count:
  - If count > `max_context_tokens * 0.85`: inject a summarization call before the next node
  - Summarization prompt: `"Summarize the following analysis concisely, preserving all key findings, entities, and conclusions: {state}"`
  - Replace verbose state fields with the summary string; preserve structured fields (IDs, scores)
- If `max_context_tokens` is `None`, skip all token counting — zero overhead

**Agents that set limits:**

| Agent | `max_context_tokens` |
|---|---|
| Lead Analyst | `80000` |
| Specialist | `60000` |
| Probability | `40000` |

**New dependency:** `tiktoken` (add to `requirements.txt`)

---

## Testing Strategy

All tests follow the existing `pytest-asyncio` + `pytest-httpx` pattern in `tests/`.

| Phase | Test file | Key scenarios |
|---|---|---|
| 1A (HITL) | `tests/test_hitl.py` | Task pauses on `input-required`, resume endpoint unblocks it, invalid resume state returns 409 |
| 1A (Retry) | `tests/test_retry.py` | Transient error retries N times, exhausted retries mark FAILED, A2AError fails immediately |
| 2A (Rate limit) | `tests/test_rate_limit.py` | N+1th request returns 429, completed task releases slot, Redis path tested with fakeredis |
| 3A (Pipeline) | `tests/test_pipeline.py` | 2-step pipeline chains output, step failure halts pipeline, GET pipeline returns correct states |
| 1B (Schema) | `tests/test_output_schema.py` | Valid output passes, missing field fails with OutputValidationError, no schema = no validation |
| 2B (Token) | `tests/test_token_budget.py` | State under threshold passes unchanged, state over threshold is summarized, no limit = no counting |

---

## Dependency Summary

| New dependency | Used by | Phase |
|---|---|---|
| `jsonschema` | Output schema validation | 1B |
| `tiktoken` | Token budget management | 2B |
| `fakeredis` (test only) | Rate limiting Redis path tests | 2A |

---

## Environment Variables Added

| Variable | Default | Description |
|---|---|---|
| `MAX_RETRIES` | `2` | Max retry attempts for transient task failures |
| `RETRY_DELAY_S` | `1.0` | Base delay between retries (seconds) |

All other configuration (rate limit, token budgets, output schemas) is declared in agent code, not env vars.
