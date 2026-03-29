# Agent Harness Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the 6 agent harness gaps in Mission Control: HITL, retries, rate limiting, pipeline chaining, output schema validation, and token budget management.

**Architecture:** Two parallel tracks — Track 1 modifies the control plane only (`control_plane/`); Track 2 modifies only the agent base executor (`agents/base/executor.py`) and individual agent executors. Tracks share no files and can be executed simultaneously by two engineers.

**Tech Stack:** Python, FastAPI, asyncio, asyncpg, redis.asyncio, jsonschema, tiktoken, pytest-asyncio, pytest-httpx, fakeredis

---

## File Map

### Track 1 — Control Plane
| File | Action | Purpose |
|---|---|---|
| `control_plane/task_store.py` | Modify | Add `resumed_inputs`, `pending_input_prompt`, `retry_count`, `pipeline_id` fields to `TaskRecord` |
| `control_plane/routes.py` | Modify | Handle `input-required`, add resume endpoint, retry loop, 429 enforcement, pipeline endpoints, `_advance_pipeline` |
| `control_plane/registry.py` | Modify | Add `max_concurrent` + `current_tasks` counter to `AgentType` |
| `control_plane/pipeline_store.py` | Create | `PipelineStep`, `PipelineRecord`, `PipelineStore` data model |
| `requirements.txt` | Modify | Add `fakeredis` (test) |
| `.env.template` | Modify | Add `MAX_RETRIES`, `RETRY_DELAY_S` |
| `docker-compose.yml` | Modify | Add new env vars to control-plane service |
| `CLAUDE.md` | Modify | Document new env vars |
| `tests/test_hitl.py` | Create | HITL integration tests |
| `tests/test_retry.py` | Create | Retry policy integration tests |
| `tests/test_rate_limit.py` | Create | Rate limiting integration tests |
| `tests/test_pipeline.py` | Create | Pipeline API integration tests |

### Track 2 — Per-Agent
| File | Action | Purpose |
|---|---|---|
| `agents/base/executor.py` | Modify | Add `output_schema` validation + `max_context_tokens` token budget |
| `agents/relevancy/executor.py` | Modify | Declare `output_schema` |
| `agents/probability_agent/executor.py` | Modify | Declare `output_schema` + `max_context_tokens` |
| `agents/lead_analyst/executor.py` | Modify | Declare `max_context_tokens` |
| `agents/specialist_agent/executor.py` | Modify | Declare `max_context_tokens` |
| `requirements.txt` | Modify | Add `jsonschema`, `tiktoken` |
| `tests/test_output_schema.py` | Create | Output schema validation tests |
| `tests/test_token_budget.py` | Create | Token budget management tests |

---

## TRACK 1 — CONTROL PLANE

---

### Task 1: Extend TaskRecord with HITL, retry, and pipeline fields

**Files:**
- Modify: `control_plane/task_store.py`
- Test: `tests/test_task_record_fields.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_task_record_fields.py
from control_plane.task_store import TaskRecord, TaskState


def test_task_record_new_fields_defaults():
    record = TaskRecord(task_id="t1", agent_id="echo-agent")
    assert record.resumed_inputs == []
    assert record.pending_input_prompt == ""
    assert record.retry_count == 0
    assert record.pipeline_id == ""


def test_task_record_to_dict_includes_new_fields():
    record = TaskRecord(task_id="t1", agent_id="echo-agent")
    record.resumed_inputs = ["yes please"]
    record.pending_input_prompt = "Do you want to continue?"
    record.retry_count = 1
    record.pipeline_id = "pipe-123"
    d = record.to_dict()
    assert d["resumed_inputs"] == ["yes please"]
    assert d["pending_input_prompt"] == "Do you want to continue?"
    assert d["retry_count"] == 1
    assert d["pipeline_id"] == "pipe-123"


def test_task_record_from_row_new_fields():
    row = {
        "task_id": "t1",
        "agent_id": "echo-agent",
        "instance_url": "",
        "state": "submitted",
        "input_text": "",
        "baselines": "",
        "key_questions": "",
        "output_text": "",
        "error": "",
        "created_at": 0.0,
        "updated_at": 0.0,
        "a2a_task": "{}",
        "node_outputs": "{}",
        "running_node": "",
        "resumed_inputs": '["reply text"]',
        "pending_input_prompt": "Continue?",
        "retry_count": 2,
        "pipeline_id": "pipe-abc",
    }
    record = TaskRecord.from_row(row)
    assert record.resumed_inputs == ["reply text"]
    assert record.pending_input_prompt == "Continue?"
    assert record.retry_count == 2
    assert record.pipeline_id == "pipe-abc"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_task_record_fields.py -v
```
Expected: FAIL — `TaskRecord` has no attribute `resumed_inputs`

- [ ] **Step 3: Add new fields to TaskRecord dataclass**

In `control_plane/task_store.py`, add 4 new fields to the `TaskRecord` dataclass after `running_node`:

```python
    running_node: str = ""
    resumed_inputs: list[str] = field(default_factory=list)
    pending_input_prompt: str = ""
    retry_count: int = 0
    pipeline_id: str = ""
```

- [ ] **Step 4: Update `to_dict()` to include new fields**

In `TaskRecord.to_dict()`, add after `"running_node": self.running_node,`:

```python
            "resumed_inputs": self.resumed_inputs,
            "pending_input_prompt": self.pending_input_prompt,
            "retry_count": self.retry_count,
            "pipeline_id": self.pipeline_id,
```

- [ ] **Step 5: Update `from_row()` to parse new fields**

In `TaskRecord.from_row()`, update the `return cls(...)` call — add after `running_node=running_node,`:

```python
            resumed_inputs=json.loads(row["resumed_inputs"]) if isinstance(row.get("resumed_inputs"), str) else (row.get("resumed_inputs") or []),
            pending_input_prompt=row.get("pending_input_prompt", ""),
            retry_count=int(row.get("retry_count", 0)),
            pipeline_id=row.get("pipeline_id", ""),
```

- [ ] **Step 6: Add PostgreSQL migration SQL constants**

In `control_plane/task_store.py`, after `_ADD_NODE_OUTPUT_COLUMNS`, add:

```python
_ADD_HITL_COLUMNS = """
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS resumed_inputs TEXT NOT NULL DEFAULT '[]';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS pending_input_prompt TEXT NOT NULL DEFAULT '';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retry_count INT NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS pipeline_id TEXT NOT NULL DEFAULT '';
"""
```

- [ ] **Step 7: Update `_UPSERT` SQL to include new columns**

Replace the existing `_UPSERT` constant:

```python
_UPSERT = """
INSERT INTO tasks
    (task_id, agent_id, instance_url, state, input_text, baselines, key_questions,
     output_text, error, created_at, updated_at, a2a_task, node_outputs, running_node,
     resumed_inputs, pending_input_prompt, retry_count, pipeline_id)
VALUES
    ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18)
ON CONFLICT (task_id) DO UPDATE SET
    state                = EXCLUDED.state,
    output_text          = EXCLUDED.output_text,
    error                = EXCLUDED.error,
    updated_at           = EXCLUDED.updated_at,
    a2a_task             = EXCLUDED.a2a_task,
    node_outputs         = EXCLUDED.node_outputs,
    running_node         = EXCLUDED.running_node,
    resumed_inputs       = EXCLUDED.resumed_inputs,
    pending_input_prompt = EXCLUDED.pending_input_prompt,
    retry_count          = EXCLUDED.retry_count,
    pipeline_id          = EXCLUDED.pipeline_id;
"""
```

- [ ] **Step 8: Update `PostgresTaskStore.init()` to run new migration**

In `PostgresTaskStore.init()`, add after `await conn.execute(_ADD_NODE_OUTPUT_COLUMNS)`:

```python
            await conn.execute(_ADD_HITL_COLUMNS)
```

- [ ] **Step 9: Update `PostgresTaskStore.save()` to write new fields**

Replace the `await conn.execute(_UPSERT, ...)` call with:

```python
            await conn.execute(
                _UPSERT,
                record.task_id,
                record.agent_id,
                record.instance_url,
                record.state.value,
                record.input_text,
                record.baselines,
                record.key_questions,
                record.output_text,
                record.error,
                record.created_at,
                record.updated_at,
                json.dumps(record.a2a_task),
                json.dumps(record.node_outputs),
                record.running_node,
                json.dumps(record.resumed_inputs),
                record.pending_input_prompt,
                record.retry_count,
                record.pipeline_id,
            )
```

- [ ] **Step 10: Run tests to verify they pass**

```
pytest tests/test_task_record_fields.py -v
```
Expected: PASS (3 tests)

- [ ] **Step 11: Commit**

```bash
git add control_plane/task_store.py tests/test_task_record_fields.py
git commit -m "feat(task-store): add HITL, retry, and pipeline fields to TaskRecord"
```

---

### Task 2: Handle `input-required` in `_run_task`

**Files:**
- Modify: `control_plane/routes.py`
- Test: `tests/test_hitl.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hitl.py
import json
import pytest
import httpx
from pytest_httpx import HTTPXMock
from tests.conftest import FAKE_AGENT_ID, FAKE_AGENT_URL, a2a_sse_event


def input_required_sse(prompt: str) -> bytes:
    """SSE event for input-required state."""
    event_data = {
        "result": {
            "status": {
                "state": "input-required",
                "message": {"parts": [{"text": prompt}]},
            }
        }
    }
    return f"data: {json.dumps(event_data)}\n\n".encode()


async def test_task_pauses_on_input_required(client, httpx_mock: HTTPXMock):
    """When agent emits input-required, task state becomes input-required."""
    httpx_mock.add_response(
        url=f"{FAKE_AGENT_URL}/",
        content=input_required_sse("Do you want to proceed?"),
        headers={"content-type": "text/event-stream"},
    )

    resp = await client.post(f"/agents/{FAKE_AGENT_ID}/tasks", json={"text": "hello"})
    assert resp.status_code == 202
    task_id = resp.json()["task_id"]

    import asyncio
    await asyncio.sleep(0.2)

    task_resp = await client.get(f"/agents/{FAKE_AGENT_ID}/tasks/{task_id}")
    assert task_resp.status_code == 200
    task = task_resp.json()
    assert task["state"] == "input-required"
    assert task["pending_input_prompt"] == "Do you want to proceed?"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_hitl.py::test_task_pauses_on_input_required -v
```
Expected: FAIL — task state is `failed` instead of `input-required`

- [ ] **Step 3: Handle `input-required` in the streaming loop in `_run_task`**

In `control_plane/routes.py`, find the TODO comment at line ~211:
```python
# TODO: handle "input-required" state — currently silently ignored
```

Replace that block with:

```python
                if state_str == "input-required":
                    record.state = TaskState.INPUT_REQUIRED
                    record.pending_input_prompt = text_val
                    record.running_node = ""
                    await _task_store.save(record)
                    await _broker.publish(task_id, record.to_dict())
                    break
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_hitl.py::test_task_pauses_on_input_required -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add control_plane/routes.py tests/test_hitl.py
git commit -m "feat(hitl): handle input-required state in _run_task"
```

---

### Task 3: Add `POST /tasks/{task_id}/resume` endpoint

**Files:**
- Modify: `control_plane/routes.py`
- Test: `tests/test_hitl.py` (extend)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_hitl.py`:

```python
async def test_resume_unblocks_task(client, httpx_mock: HTTPXMock):
    """Resume endpoint re-dispatches task and it completes."""
    # First call: agent asks a question
    httpx_mock.add_response(
        url=f"{FAKE_AGENT_URL}/",
        content=input_required_sse("Confirm?"),
        headers={"content-type": "text/event-stream"},
    )
    resp = await client.post(f"/agents/{FAKE_AGENT_ID}/tasks", json={"text": "start"})
    task_id = resp.json()["task_id"]

    import asyncio
    await asyncio.sleep(0.2)

    # Second call: agent completes after receiving the reply
    from tests.conftest import a2a_sse_event
    httpx_mock.add_response(
        url=f"{FAKE_AGENT_URL}/",
        content=a2a_sse_event("DONE"),
        headers={"content-type": "text/event-stream"},
    )

    resume_resp = await client.post(f"/tasks/{task_id}/resume", json={"text": "yes"})
    assert resume_resp.status_code == 200

    await asyncio.sleep(0.2)

    task_resp = await client.get(f"/agents/{FAKE_AGENT_ID}/tasks/{task_id}")
    assert task_resp.json()["state"] == "completed"
    assert task_resp.json()["pending_input_prompt"] == ""


async def test_resume_returns_409_if_not_input_required(client, httpx_mock: HTTPXMock):
    """Resume on a non-input-required task returns 409."""
    from tests.conftest import a2a_sse_event
    httpx_mock.add_response(
        url=f"{FAKE_AGENT_URL}/",
        content=a2a_sse_event("done"),
        headers={"content-type": "text/event-stream"},
    )
    resp = await client.post(f"/agents/{FAKE_AGENT_ID}/tasks", json={"text": "hello"})
    task_id = resp.json()["task_id"]

    import asyncio
    await asyncio.sleep(0.2)

    resume_resp = await client.post(f"/tasks/{task_id}/resume", json={"text": "extra"})
    assert resume_resp.status_code == 409


async def test_resume_returns_404_for_unknown_task(client):
    """Resume on unknown task returns 404."""
    resp = await client.post("/tasks/nonexistent/resume", json={"text": "hello"})
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_hitl.py -v
```
Expected: 3 new tests FAIL — endpoint doesn't exist yet

- [ ] **Step 3: Add `ResumeRequest` model and `POST /tasks/{task_id}/resume` endpoint to routes.py**

After the `TaskRequest` model definition in `control_plane/routes.py`, add:

```python
class ResumeRequest(BaseModel):
    text: str
```

After the `delete_task` endpoint, add:

```python
@router.post("/tasks/{task_id}/resume")
async def resume_task(task_id: str, req: ResumeRequest) -> dict[str, Any]:
    """Resume a task that is waiting for human input."""
    assert _registry is not None and _task_store is not None

    record = await _task_store.get(task_id)
    if not record:
        raise HTTPException(404, "Task not found")
    if record.state != TaskState.INPUT_REQUIRED:
        raise HTTPException(409, f"Task is in state '{record.state.value}', not 'input-required'")

    agent_type = _registry.get(record.agent_id)
    if not agent_type:
        raise HTTPException(404, f"Agent '{record.agent_id}' no longer registered")

    instance = agent_type.pick()
    if not instance:
        raise HTTPException(503, f"No online instances for agent '{record.agent_id}'")

    # Build combined context so the agent has full conversation history
    combined_text = (
        f"{record.input_text}\n\n"
        f"[Agent asked]: {record.pending_input_prompt}\n\n"
        f"[User replied]: {req.text}"
    )
    record.resumed_inputs.append(req.text)
    record.pending_input_prompt = ""
    record.state = TaskState.SUBMITTED
    await _task_store.save(record)

    asyncio.create_task(_run_task(task_id, record.agent_id, instance, combined_text))
    return {"status": "resumed", "task_id": task_id}
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_hitl.py -v
```
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add control_plane/routes.py tests/test_hitl.py
git commit -m "feat(hitl): add POST /tasks/{task_id}/resume endpoint"
```

---

### Task 4: Add `RetryConfig` and retry loop to `_run_task`

**Files:**
- Modify: `control_plane/routes.py`
- Test: `tests/test_retry.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_retry.py
import json
import os
import pytest
import httpx
from pytest_httpx import HTTPXMock
from tests.conftest import FAKE_AGENT_ID, FAKE_AGENT_URL, a2a_sse_event, wait_for_task


async def test_transient_error_is_retried(client, httpx_mock: HTTPXMock):
    """ConnectError on first attempt retries and eventually completes."""
    # First call raises ConnectError, second succeeds
    httpx_mock.add_exception(httpx.ConnectError("connection refused"))
    httpx_mock.add_response(
        url=f"{FAKE_AGENT_URL}/",
        content=a2a_sse_event("done"),
        headers={"content-type": "text/event-stream"},
    )

    resp = await client.post(f"/agents/{FAKE_AGENT_ID}/tasks", json={"text": "hello"})
    task_id = resp.json()["task_id"]
    task = await wait_for_task(client, FAKE_AGENT_ID, task_id, timeout=5.0)

    assert task["state"] == "completed"
    assert task["retry_count"] == 1


async def test_exhausted_retries_marks_failed(client, httpx_mock: HTTPXMock, monkeypatch):
    """After max retries all fail, task is marked failed."""
    monkeypatch.setenv("MAX_RETRIES", "2")
    monkeypatch.setenv("RETRY_DELAY_S", "0.01")

    httpx_mock.add_exception(httpx.ConnectError("refused"))
    httpx_mock.add_exception(httpx.ConnectError("refused"))
    httpx_mock.add_exception(httpx.ConnectError("refused"))

    resp = await client.post(f"/agents/{FAKE_AGENT_ID}/tasks", json={"text": "hello"})
    task_id = resp.json()["task_id"]
    task = await wait_for_task(client, FAKE_AGENT_ID, task_id, timeout=5.0)

    assert task["state"] == "failed"
    assert "2 retries" in task["error"]
    assert task["retry_count"] == 2


async def test_a2a_error_does_not_retry(client, httpx_mock: HTTPXMock):
    """A2AError fails immediately without retry."""
    error_body = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "bad request"}}
    httpx_mock.add_response(url=f"{FAKE_AGENT_URL}/", json=error_body)

    resp = await client.post(f"/agents/{FAKE_AGENT_ID}/tasks", json={"text": "hello"})
    task_id = resp.json()["task_id"]
    task = await wait_for_task(client, FAKE_AGENT_ID, task_id, timeout=5.0)

    assert task["state"] == "failed"
    assert task["retry_count"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_retry.py -v
```
Expected: 3 tests FAIL — no retry logic exists yet

- [ ] **Step 3: Add `RetryConfig` dataclass to `routes.py`**

At the top of `control_plane/routes.py`, after the imports, add:

```python
import os
from dataclasses import dataclass


@dataclass
class RetryConfig:
    max_retries: int = int(os.getenv("MAX_RETRIES", "2"))
    retry_delay_s: float = float(os.getenv("RETRY_DELAY_S", "1.0"))
```

- [ ] **Step 4: Wrap the transient error branches in `_run_task` with a retry loop**

In `_run_task`, replace the current error handling block that starts with `except A2AError as exc:` with:

```python
    retry_cfg = RetryConfig()
    attempt = 0

    while True:
        try:
            gen = client.stream_message(
                text,
                task_id=task_id,
                baselines=record.baselines,
                key_questions=record.key_questions,
            )
            try:
                async for event in gen:
                    state_str = event.get("result", {}).get("status", {}).get("state", "")
                    msg = event.get("result", {}).get("status", {}).get("message", {})
                    text_val = (msg.get("parts") or [{}])[0].get("text", "")

                    if text_val.startswith("NODE_OUTPUT::"):
                        parts = text_val.split("::", 2)
                        if len(parts) == 3:
                            _, node_name, json_payload = parts
                            try:
                                json.loads(json_payload)
                                out_key = node_name
                                idx = 1
                                while out_key in record.node_outputs:
                                    out_key = f"{node_name}:{idx}"
                                    idx += 1
                                record.node_outputs[out_key] = json_payload
                                record.running_node = ""
                                await _task_store.save(record)
                                await _broker.publish(task_id, record.to_dict())
                            except json.JSONDecodeError:
                                logger.warning("node_output_invalid_json", task_id=task_id, node=node_name)
                        else:
                            logger.warning("node_output_malformed", task_id=task_id, text=text_val[:100])
                        continue

                    if state_str == "working" and text_val.startswith("Running node: "):
                        node_name = text_val[len("Running node: "):]
                        record.running_node = node_name
                        await _task_store.save(record)
                        await _broker.publish(task_id, record.to_dict())
                        continue

                    if state_str == "input-required":
                        record.state = TaskState.INPUT_REQUIRED
                        record.pending_input_prompt = text_val
                        record.running_node = ""
                        await _task_store.save(record)
                        await _broker.publish(task_id, record.to_dict())
                        break

                    if state_str in ("completed", "failed", "canceled"):
                        record.state = TaskState(state_str)
                        record.output_text = text_val
                        record.running_node = ""
                        if record.state == TaskState.FAILED:
                            record.error = text_val or "Agent returned failed state with no details"
                        break
                else:
                    terminal = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED}
                    fresh = await _task_store.get(task_id)
                    if fresh is None or fresh.state not in terminal:
                        record.state = TaskState.FAILED
                        record.error = "Stream ended without a terminal status event"
                    else:
                        record.state = fresh.state
            finally:
                await gen.aclose()

            break  # success — exit retry loop

        except A2AError as exc:
            tasks_failed.labels(agent_id=agent_id).inc()
            logger.error("task_a2a_error", task_id=task_id, error=str(exc))
            record.state = TaskState.FAILED
            record.error = f"A2A protocol error: {exc}"
            break  # do not retry A2A errors

        except httpx.HTTPStatusError as exc:
            tasks_failed.labels(agent_id=agent_id).inc()
            logger.error("task_http_error", task_id=task_id, status=exc.response.status_code, error=str(exc))
            record.state = TaskState.FAILED
            record.error = f"HTTP {exc.response.status_code}: {exc.response.text[:500]}"
            break  # do not retry HTTP errors

        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            if attempt < retry_cfg.max_retries:
                attempt += 1
                record.retry_count = attempt
                await _task_store.save(record)
                logger.warning(
                    "task_transient_error_retrying",
                    task_id=task_id,
                    attempt=attempt,
                    max=retry_cfg.max_retries,
                    error=str(exc),
                )
                await asyncio.sleep(retry_cfg.retry_delay_s * attempt)
                continue
            tasks_failed.labels(agent_id=agent_id).inc()
            logger.error("task_connection_error", task_id=task_id, error=str(exc))
            record.state = TaskState.FAILED
            record.error = f"Failed after {retry_cfg.max_retries} retries: {type(exc).__name__} — {exc}"
            break

        except Exception as exc:
            tasks_failed.labels(agent_id=agent_id).inc()
            logger.error("task_error", task_id=task_id, error=str(exc))
            record.state = TaskState.FAILED
            record.error = f"{type(exc).__name__}: {exc}"
            break
```

Also remove the old `except` blocks that were after the old `gen = client.stream_message(...)` since they are now inside the while loop above. Then keep the rest of `_run_task` (the metrics, logging, finally block) intact after the while loop.

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/test_retry.py -v
```
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add control_plane/routes.py tests/test_retry.py
git commit -m "feat(retry): add configurable retry policy for transient task failures"
```

---

### Task 5: Add rate limiting to `AgentType`

**Files:**
- Modify: `control_plane/registry.py`
- Test: `tests/test_rate_limit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rate_limit.py
import pytest
from control_plane.registry import AgentType, AgentInstance, AgentStatus


def test_try_acquire_succeeds_under_limit():
    at = AgentType(id="echo-agent", max_concurrent=2)
    assert at.try_acquire() is True
    assert at.try_acquire() is True


def test_try_acquire_rejects_at_limit():
    at = AgentType(id="echo-agent", max_concurrent=2)
    at.try_acquire()
    at.try_acquire()
    assert at.try_acquire() is False


def test_release_frees_slot():
    at = AgentType(id="echo-agent", max_concurrent=1)
    at.try_acquire()
    assert at.try_acquire() is False
    at.release()
    assert at.try_acquire() is True


def test_max_concurrent_from_agent_card():
    """max_concurrent is read from agent card capabilities."""
    at = AgentType(id="echo-agent")
    instance = AgentInstance(
        url="http://echo:8001",
        status=AgentStatus.ONLINE,
        card={"capabilities": {"max_concurrent_tasks": 5}},
    )
    at.instances.append(instance)
    at.update_max_concurrent_from_card()
    assert at.max_concurrent == 5
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_rate_limit.py -v
```
Expected: FAIL — `AgentType` has no `max_concurrent`, `try_acquire`, `release`, or `update_max_concurrent_from_card`

- [ ] **Step 3: Add rate limiting fields and methods to `AgentType`**

In `control_plane/registry.py`, update the `AgentType` dataclass:

```python
@dataclass
class AgentType:
    """A logical agent, potentially backed by multiple instances."""

    id: str
    instances: list[AgentInstance] = field(default_factory=list)
    max_concurrent: int = 10
    _current_tasks: int = field(default=0, init=False, repr=False)

    def try_acquire(self) -> bool:
        """Attempt to acquire a task slot. Returns False if at capacity."""
        if self._current_tasks >= self.max_concurrent:
            return False
        self._current_tasks += 1
        return True

    def release(self) -> None:
        """Release a task slot."""
        self._current_tasks = max(0, self._current_tasks - 1)

    def update_max_concurrent_from_card(self) -> None:
        """Read max_concurrent_tasks from the first available agent card."""
        for inst in self.instances:
            if inst.card:
                cap = inst.card.get("capabilities", {})
                if "max_concurrent_tasks" in cap:
                    self.max_concurrent = int(cap["max_concurrent_tasks"])
                return
```

- [ ] **Step 4: Call `update_max_concurrent_from_card` after refreshing an instance**

In `AgentRegistry._refresh_instance`, after `instance.status = AgentStatus.ONLINE`:

```python
            agent_type = self._types.get(type_id)
            if agent_type:
                agent_type.update_max_concurrent_from_card()
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/test_rate_limit.py -v
```
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add control_plane/registry.py tests/test_rate_limit.py
git commit -m "feat(rate-limit): add try_acquire/release slots to AgentType"
```

---

### Task 6: Enforce 429 in `dispatch_task`

**Files:**
- Modify: `control_plane/routes.py`
- Test: `tests/test_rate_limit.py` (extend)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_rate_limit.py`:

```python
import httpx
from pytest_httpx import HTTPXMock
from tests.conftest import FAKE_AGENT_ID, FAKE_AGENT_URL, a2a_sse_event, wait_for_task


async def test_dispatch_returns_429_when_at_capacity(client, registry):
    """When agent is at max_concurrent, dispatch returns 429."""
    registry.agents[FAKE_AGENT_ID].max_concurrent = 1
    registry.agents[FAKE_AGENT_ID]._current_tasks = 1  # already at limit

    resp = await client.post(f"/agents/{FAKE_AGENT_ID}/tasks", json={"text": "hi"})
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


async def test_completed_task_releases_slot(client, registry, httpx_mock: HTTPXMock):
    """After task completes, slot is released."""
    registry.agents[FAKE_AGENT_ID].max_concurrent = 1

    httpx_mock.add_response(
        url=f"{FAKE_AGENT_URL}/",
        content=a2a_sse_event("done"),
        headers={"content-type": "text/event-stream"},
    )

    resp = await client.post(f"/agents/{FAKE_AGENT_ID}/tasks", json={"text": "hi"})
    assert resp.status_code == 202
    task_id = resp.json()["task_id"]
    await wait_for_task(client, FAKE_AGENT_ID, task_id, timeout=5.0)

    # After completion, slot should be free
    assert registry.agents[FAKE_AGENT_ID]._current_tasks == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_rate_limit.py::test_dispatch_returns_429_when_at_capacity tests/test_rate_limit.py::test_completed_task_releases_slot -v
```
Expected: FAIL

- [ ] **Step 3: Enforce rate limit in `dispatch_task`**

In `control_plane/routes.py`, in `dispatch_task`, after `instance = agent_type.pick()` and the 503 check, add:

```python
    if not agent_type.try_acquire():
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=429,
            content={"detail": f"Agent '{agent_id}' is at max concurrent capacity ({agent_type.max_concurrent})"},
            headers={"Retry-After": "5"},
        )
```

- [ ] **Step 4: Release slot in `_run_task` finally block**

In `_run_task`, in the `finally` block, after `instance.active_tasks = max(0, instance.active_tasks - 1)`, add:

```python
        agent_type = _registry.get(agent_id) if _registry else None
        if agent_type:
            agent_type.release()
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/test_rate_limit.py -v
```
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add control_plane/routes.py tests/test_rate_limit.py
git commit -m "feat(rate-limit): enforce 429 in dispatch_task when agent at capacity"
```

---

### Task 7: Create `pipeline_store.py`

**Files:**
- Create: `control_plane/pipeline_store.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline.py
import pytest
from control_plane.pipeline_store import PipelineRecord, PipelineStep, PipelineStore


async def test_pipeline_store_save_and_get():
    store = PipelineStore()
    pipeline = PipelineRecord(
        pipeline_id="pipe-1",
        steps=[
            PipelineStep(agent_id="echo-agent", input_template="start"),
            PipelineStep(agent_id="echo-agent", input_template="then {{output}}"),
        ],
        state="pending",
    )
    await store.save(pipeline)
    retrieved = await store.get("pipe-1")
    assert retrieved is not None
    assert retrieved.pipeline_id == "pipe-1"
    assert len(retrieved.steps) == 2
    assert retrieved.steps[1].input_template == "then {{output}}"


async def test_pipeline_store_list_all():
    store = PipelineStore()
    for i in range(3):
        await store.save(PipelineRecord(
            pipeline_id=f"pipe-{i}",
            steps=[PipelineStep(agent_id="echo-agent", input_template="x")],
            state="pending",
        ))
    all_pipelines = await store.list_all()
    assert len(all_pipelines) == 3


async def test_pipeline_store_get_missing_returns_none():
    store = PipelineStore()
    assert await store.get("nonexistent") is None
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_pipeline.py -v
```
Expected: FAIL — module not found

- [ ] **Step 3: Create `control_plane/pipeline_store.py`**

```python
"""Pipeline store — manages multi-step task pipelines.

A pipeline is an ordered list of steps where each step's input can reference
the previous step's output via the {{output}} placeholder.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PipelineStep:
    agent_id: str
    input_template: str          # supports {{output}} placeholder
    task_id: str = ""            # populated at runtime when dispatched
    state: str = "pending"       # pending / running / completed / failed


@dataclass
class PipelineRecord:
    pipeline_id: str
    steps: list[PipelineStep]
    state: str = "pending"       # pending / running / completed / failed
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_id": self.pipeline_id,
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "steps": [
                {
                    "agent_id": s.agent_id,
                    "input_template": s.input_template,
                    "task_id": s.task_id,
                    "state": s.state,
                }
                for s in self.steps
            ],
        }


class PipelineStore:
    """In-memory pipeline store. State is lost on restart."""

    def __init__(self) -> None:
        self._pipelines: dict[str, PipelineRecord] = {}

    async def save(self, record: PipelineRecord) -> None:
        record.updated_at = time.time()
        self._pipelines[record.pipeline_id] = record

    async def get(self, pipeline_id: str) -> PipelineRecord | None:
        return self._pipelines.get(pipeline_id)

    async def list_all(self) -> list[PipelineRecord]:
        return sorted(self._pipelines.values(), key=lambda p: p.created_at, reverse=True)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_pipeline.py::test_pipeline_store_save_and_get tests/test_pipeline.py::test_pipeline_store_list_all tests/test_pipeline.py::test_pipeline_store_get_missing_returns_none -v
```
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add control_plane/pipeline_store.py tests/test_pipeline.py
git commit -m "feat(pipeline): add PipelineStore data model"
```

---

### Task 8: Add pipeline API endpoints and `_advance_pipeline`

**Files:**
- Modify: `control_plane/routes.py`
- Test: `tests/test_pipeline.py` (extend)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pipeline.py`:

```python
import json
import pytest
import httpx
from pytest_httpx import HTTPXMock
from tests.conftest import FAKE_AGENT_ID, FAKE_AGENT_URL, a2a_sse_event, wait_for_task
from control_plane.pipeline_store import PipelineStore


@pytest.fixture()
def pipeline_store():
    return PipelineStore()


@pytest.fixture()
def app_with_pipeline(registry, task_store, broker, pipeline_store):
    from control_plane.routes import init_routes, router
    init_routes(registry, task_store, broker, pipeline_store=pipeline_store)
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from control_plane.metrics import instrument_app
    test_app = FastAPI()
    test_app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    test_app.include_router(router)
    instrument_app(test_app)
    return test_app


@pytest.fixture()
async def pclient(app_with_pipeline):
    from httpx import AsyncClient, ASGITransport
    async with AsyncClient(transport=ASGITransport(app=app_with_pipeline), base_url="http://test") as ac:
        yield ac


async def test_create_pipeline_returns_202(pclient, httpx_mock: HTTPXMock):
    """POST /pipelines creates a pipeline and dispatches step 0."""
    httpx_mock.add_response(
        url=f"{FAKE_AGENT_URL}/",
        content=a2a_sse_event("step0 output"),
        headers={"content-type": "text/event-stream"},
    )
    resp = await pclient.post("/pipelines", json={
        "steps": [
            {"agent_id": FAKE_AGENT_ID, "input_template": "hello"},
        ]
    })
    assert resp.status_code == 202
    assert "pipeline_id" in resp.json()


async def test_create_pipeline_invalid_agent_returns_400(pclient):
    """POST /pipelines with unknown agent_id returns 400."""
    resp = await pclient.post("/pipelines", json={
        "steps": [{"agent_id": "nonexistent-agent", "input_template": "hi"}]
    })
    assert resp.status_code == 400


async def test_get_pipeline_returns_record(pclient, httpx_mock: HTTPXMock):
    """GET /pipelines/{id} returns pipeline with steps."""
    httpx_mock.add_response(
        url=f"{FAKE_AGENT_URL}/",
        content=a2a_sse_event("out"),
        headers={"content-type": "text/event-stream"},
    )
    create_resp = await pclient.post("/pipelines", json={
        "steps": [{"agent_id": FAKE_AGENT_ID, "input_template": "x"}]
    })
    pipeline_id = create_resp.json()["pipeline_id"]

    get_resp = await pclient.get(f"/pipelines/{pipeline_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["pipeline_id"] == pipeline_id
    assert len(get_resp.json()["steps"]) == 1


async def test_two_step_pipeline_chains_output(pclient, httpx_mock: HTTPXMock):
    """Step 2's input contains {{output}} replaced with step 1's output."""
    httpx_mock.add_response(
        url=f"{FAKE_AGENT_URL}/",
        content=a2a_sse_event("step1-result"),
        headers={"content-type": "text/event-stream"},
    )
    httpx_mock.add_response(
        url=f"{FAKE_AGENT_URL}/",
        content=a2a_sse_event("step2-result"),
        headers={"content-type": "text/event-stream"},
    )

    import asyncio
    resp = await pclient.post("/pipelines", json={
        "steps": [
            {"agent_id": FAKE_AGENT_ID, "input_template": "first step"},
            {"agent_id": FAKE_AGENT_ID, "input_template": "second step with: {{output}}"},
        ]
    })
    pipeline_id = resp.json()["pipeline_id"]

    await asyncio.sleep(0.5)

    get_resp = await pclient.get(f"/pipelines/{pipeline_id}")
    assert get_resp.json()["state"] == "completed"
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_pipeline.py -k "test_create_pipeline or test_get_pipeline or test_two_step" -v
```
Expected: FAIL — endpoints don't exist

- [ ] **Step 3: Wire `_pipeline_store` into `init_routes`**

In `control_plane/routes.py`, add `_pipeline_store` module-level variable and update `init_routes`:

```python
from control_plane.pipeline_store import PipelineRecord, PipelineStep, PipelineStore

_pipeline_store: PipelineStore | None = None


def init_routes(
    registry: AgentRegistry,
    task_store: TaskStore | PostgresTaskStore,
    broker: InMemoryBroker | RedisBroker,
    pipeline_store: PipelineStore | None = None,
) -> None:
    global _registry, _task_store, _broker, _pipeline_store
    _registry = registry
    _task_store = task_store
    _broker = broker
    _pipeline_store = pipeline_store or PipelineStore()
```

- [ ] **Step 4: Add pipeline request model and endpoints**

Add to `control_plane/routes.py`:

```python
class PipelineStepRequest(BaseModel):
    agent_id: str
    input_template: str


class PipelineRequest(BaseModel):
    steps: list[PipelineStepRequest]


@router.post("/pipelines", status_code=202)
async def create_pipeline(req: PipelineRequest) -> dict[str, Any]:
    """Create a pipeline and dispatch the first step immediately."""
    assert _registry is not None and _task_store is not None and _pipeline_store is not None

    for step in req.steps:
        if not _registry.get(step.agent_id):
            raise HTTPException(400, f"Unknown agent_id '{step.agent_id}'")

    pipeline_id = str(uuid.uuid4())
    steps = [
        PipelineStep(agent_id=s.agent_id, input_template=s.input_template)
        for s in req.steps
    ]
    pipeline = PipelineRecord(pipeline_id=pipeline_id, steps=steps, state="running")
    await _pipeline_store.save(pipeline)

    # Dispatch step 0
    first_step = steps[0]
    first_step.state = "running"
    agent_type = _registry.get(first_step.agent_id)
    instance = agent_type.pick()
    if not instance:
        raise HTTPException(503, f"No instances for agent '{first_step.agent_id}'")

    task_id = str(uuid.uuid4())
    record = TaskRecord(
        task_id=task_id,
        agent_id=first_step.agent_id,
        instance_url=instance.url,
        state=TaskState.SUBMITTED,
        input_text=first_step.input_template,
        pipeline_id=pipeline_id,
    )
    first_step.task_id = task_id
    await _task_store.save(record)
    await _pipeline_store.save(pipeline)

    instance.active_tasks += 1
    asyncio.create_task(_run_task(task_id, first_step.agent_id, instance, first_step.input_template))

    return {"pipeline_id": pipeline_id, **pipeline.to_dict()}


@router.get("/pipelines")
async def list_pipelines() -> list[dict[str, Any]]:
    assert _pipeline_store is not None
    return [p.to_dict() for p in await _pipeline_store.list_all()]


@router.get("/pipelines/{pipeline_id}")
async def get_pipeline(pipeline_id: str) -> dict[str, Any]:
    assert _pipeline_store is not None
    pipeline = await _pipeline_store.get(pipeline_id)
    if not pipeline:
        raise HTTPException(404, "Pipeline not found")
    return pipeline.to_dict()
```

- [ ] **Step 5: Add `_advance_pipeline` and call it from `_run_task`**

Add to `control_plane/routes.py` after `_run_task`:

```python
async def _advance_pipeline(pipeline_id: str, completed_task_id: str, state: TaskState, output_text: str) -> None:
    """Advance pipeline to next step or mark complete/failed."""
    assert _pipeline_store is not None and _registry is not None and _task_store is not None

    pipeline = await _pipeline_store.get(pipeline_id)
    if not pipeline:
        return

    # Mark current step
    for step in pipeline.steps:
        if step.task_id == completed_task_id:
            step.state = state.value
            break

    if state == TaskState.FAILED:
        pipeline.state = "failed"
        await _pipeline_store.save(pipeline)
        return

    # Find next pending step
    next_step = next((s for s in pipeline.steps if s.state == "pending"), None)
    if not next_step:
        pipeline.state = "completed"
        await _pipeline_store.save(pipeline)
        return

    # Build input: replace {{output}} with previous step's output
    next_input = next_step.input_template.replace("{{output}}", output_text)

    agent_type = _registry.get(next_step.agent_id)
    if not agent_type:
        pipeline.state = "failed"
        await _pipeline_store.save(pipeline)
        return

    instance = agent_type.pick()
    if not instance:
        pipeline.state = "failed"
        await _pipeline_store.save(pipeline)
        return

    new_task_id = str(uuid.uuid4())
    record = TaskRecord(
        task_id=new_task_id,
        agent_id=next_step.agent_id,
        instance_url=instance.url,
        state=TaskState.SUBMITTED,
        input_text=next_input,
        pipeline_id=pipeline_id,
    )
    next_step.task_id = new_task_id
    next_step.state = "running"
    await _task_store.save(record)
    await _pipeline_store.save(pipeline)

    instance.active_tasks += 1
    asyncio.create_task(_run_task(new_task_id, next_step.agent_id, instance, next_input))
```

In `_run_task`, at the very end just before `await _broker.publish(task_id, record.to_dict())`, add:

```python
    if record.pipeline_id:
        await _advance_pipeline(record.pipeline_id, task_id, record.state, record.output_text)
```

- [ ] **Step 6: Run all pipeline tests**

```
pytest tests/test_pipeline.py -v
```
Expected: PASS (all tests)

- [ ] **Step 7: Commit**

```bash
git add control_plane/routes.py control_plane/pipeline_store.py tests/test_pipeline.py
git commit -m "feat(pipeline): add POST /pipelines, GET /pipelines, and pipeline chaining"
```

---

### Task 9: Update env vars, Docker, and docs

**Files:**
- Modify: `.env.template`
- Modify: `docker-compose.yml`
- Modify: `CLAUDE.md`
- Modify: `control_plane/server.py`

- [ ] **Step 1: Add `fakeredis` to `requirements.txt`**

Open `requirements.txt` and add under the `# Dev / test` section:

```
fakeredis[aioredis]>=22.0.0
```

Install it:
```
pip install "fakeredis[aioredis]>=22.0.0"
```

- [ ] **Step 3: Add new env vars to `.env.template`**

Open `.env.template` and add under the control plane section:

```bash
# Task retry policy
MAX_RETRIES=2
RETRY_DELAY_S=1.0
```

- [ ] **Step 4: Add env vars to `docker-compose.yml`**

Find the control-plane service environment block and add:

```yaml
      - MAX_RETRIES=${MAX_RETRIES:-2}
      - RETRY_DELAY_S=${RETRY_DELAY_S:-1.0}
```

- [ ] **Step 5: Update `CLAUDE.md` environment variable table**

In the Control Plane environment variables table, add two rows:

```markdown
| `MAX_RETRIES` | `2` | Max retry attempts for transient task failures |
| `RETRY_DELAY_S` | `1.0` | Base delay in seconds between retries (linear backoff) |
```

- [ ] **Step 6: Run full Track 1 test suite**

```
pytest tests/test_task_record_fields.py tests/test_hitl.py tests/test_retry.py tests/test_rate_limit.py tests/test_pipeline.py -v
```
Expected: PASS (all tests)

- [ ] **Step 7: Commit**

```bash
git add .env.template docker-compose.yml CLAUDE.md requirements.txt
git commit -m "docs: add MAX_RETRIES, RETRY_DELAY_S env vars; add fakeredis test dep"
```

---

## TRACK 2 — PER-AGENT

---

### Task 10: Add output schema validation to `LangGraphA2AExecutor`

**Files:**
- Modify: `agents/base/executor.py`
- Modify: `requirements.txt`
- Test: `tests/test_output_schema.py`

- [ ] **Step 1: Add `jsonschema` to requirements.txt**

Open `requirements.txt` and add:

```
jsonschema>=4.0.0
```

Install it:
```
pip install jsonschema>=4.0.0
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_output_schema.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agents.base.executor import LangGraphA2AExecutor
from langgraph.graph.state import CompiledStateGraph


class EchoExecutor(LangGraphA2AExecutor):
    """Minimal executor with no schema — plain text output."""
    def build_graph(self) -> CompiledStateGraph:
        raise NotImplementedError


class JsonExecutor(LangGraphA2AExecutor):
    """Executor that declares a JSON output schema."""
    output_schema = {
        "type": "object",
        "required": ["verdict", "score"],
        "properties": {
            "verdict": {"type": "string"},
            "score": {"type": "number"},
        },
    }
    def build_graph(self) -> CompiledStateGraph:
        raise NotImplementedError


def test_no_schema_passes_any_output():
    """When output_schema is None, format_output returns the value unchanged."""
    executor = EchoExecutor()
    result = executor.format_output({"output": "hello world"})
    assert result == "hello world"


def test_valid_json_passes_schema():
    """Valid JSON matching the schema is returned without error."""
    executor = JsonExecutor()
    valid = json.dumps({"verdict": "relevant", "score": 0.9})
    result = executor.validate_output(valid)
    assert result == valid


def test_invalid_json_raises_validation_error():
    """Non-JSON output raises ValueError with OutputValidationError prefix."""
    executor = JsonExecutor()
    with pytest.raises(ValueError, match="OutputValidationError"):
        executor.validate_output("not json at all")


def test_missing_required_field_raises_validation_error():
    """JSON missing a required field raises ValueError."""
    executor = JsonExecutor()
    bad = json.dumps({"verdict": "relevant"})  # missing "score"
    with pytest.raises(ValueError, match="OutputValidationError"):
        executor.validate_output(bad)
```

- [ ] **Step 3: Run tests to verify they fail**

```
pytest tests/test_output_schema.py -v
```
Expected: FAIL — `LangGraphA2AExecutor` has no `output_schema` or `validate_output`

- [ ] **Step 4: Add `output_schema` and `validate_output` to `LangGraphA2AExecutor`**

In `agents/base/executor.py`, add after the class definition opens (after `def __init__`):

```python
    # Subclasses may set this to a JSON Schema dict to enable output validation.
    # Leave as None to skip validation (default — all text-output agents).
    output_schema: dict | None = None
```

Add the `validate_output` method after `format_output`:

```python
    def validate_output(self, output_text: str) -> str:
        """Validate output_text against output_schema if declared.

        Returns output_text unchanged if valid or if no schema is set.
        Raises ValueError with 'OutputValidationError: ...' prefix on failure.
        """
        if self.output_schema is None:
            return output_text
        import json
        import jsonschema
        try:
            parsed = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"OutputValidationError: output is not valid JSON — {exc}") from exc
        try:
            jsonschema.validate(parsed, self.output_schema)
        except jsonschema.ValidationError as exc:
            raise ValueError(f"OutputValidationError: {exc.message}") from exc
        return output_text
```

- [ ] **Step 5: Call `validate_output` inside `execute()` after `format_output()`**

In `agents/base/executor.py`, in the `execute` method, find:

```python
            output_text = self.format_output(result)
```

Replace with:

```python
            output_text = self.format_output(result)
            try:
                output_text = self.validate_output(output_text)
            except ValueError as exc:
                await self._emit_status(
                    event_queue, task_id, context_id, TaskState.failed, str(exc), final=True
                )
                return
```

- [ ] **Step 6: Run tests to verify they pass**

```
pytest tests/test_output_schema.py -v
```
Expected: PASS (4 tests)

- [ ] **Step 7: Commit**

```bash
git add agents/base/executor.py requirements.txt tests/test_output_schema.py
git commit -m "feat(output-schema): add output_schema validation to LangGraphA2AExecutor"
```

---

### Task 11: Declare output schemas on Relevancy and Probability executors

**Files:**
- Modify: `agents/relevancy/executor.py`
- Modify: `agents/probability_agent/executor.py`
- Test: `tests/test_output_schema.py` (extend)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_output_schema.py`:

```python
import json
from agents.relevancy.executor import RelevancyExecutor
from agents.probability_agent.executor import ProbabilityExecutor


def test_relevancy_executor_has_schema():
    ex = RelevancyExecutor()
    assert ex.output_schema is not None
    assert "relevant" in ex.output_schema["properties"]
    assert "confidence" in ex.output_schema["properties"]
    assert "reasoning" in ex.output_schema["properties"]


def test_relevancy_valid_output_passes():
    ex = RelevancyExecutor()
    valid = json.dumps({"relevant": True, "confidence": 0.9, "reasoning": "matches topic"})
    assert ex.validate_output(valid) == valid


def test_relevancy_missing_field_fails():
    ex = RelevancyExecutor()
    bad = json.dumps({"relevant": True})  # missing confidence + reasoning
    with pytest.raises(ValueError, match="OutputValidationError"):
        ex.validate_output(bad)


def test_probability_executor_has_schema():
    ex = ProbabilityExecutor()
    assert ex.output_schema is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_output_schema.py -k "relevancy or probability" -v
```
Expected: FAIL — executors have no `output_schema`

- [ ] **Step 3: Add `output_schema` to `RelevancyExecutor`**

Replace the entire content of `agents/relevancy/executor.py` with:

```python
"""Executor that bridges A2A requests to the Relevancy LangGraph."""

from __future__ import annotations

from langgraph.graph.state import CompiledStateGraph

from agents.base.executor import LangGraphA2AExecutor
from agents.relevancy.graph import build_relevancy_graph


class RelevancyExecutor(LangGraphA2AExecutor):
    """Runs the relevancy graph: parse input → LLM check → JSON output."""

    output_schema = {
        "type": "object",
        "required": ["relevant", "confidence", "reasoning"],
        "properties": {
            "relevant": {"type": "boolean"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "reasoning": {"type": "string"},
        },
    }

    def build_graph(self) -> CompiledStateGraph:
        return build_relevancy_graph()
```

- [ ] **Step 4: Add `output_schema` to `ProbabilityExecutor`**

Replace the entire content of `agents/probability_agent/executor.py` with:

```python
"""A2A executor for the Probability Forecasting agent."""

from __future__ import annotations

from langgraph.graph.state import CompiledStateGraph

from agents.base import LangGraphA2AExecutor
from agents.probability_agent.graph import build_probability_graph


class ProbabilityExecutor(LangGraphA2AExecutor):
    """Wraps the probability forecasting LangGraph in an A2A-compatible executor."""

    output_schema = {
        "type": "object",
        "required": ["probability", "confidence_interval", "disagreements"],
        "properties": {
            "probability": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "confidence_interval": {
                "type": "object",
                "required": ["low", "high"],
                "properties": {
                    "low": {"type": "number"},
                    "high": {"type": "number"},
                },
            },
            "disagreements": {"type": "array"},
        },
    }

    def build_graph(self) -> CompiledStateGraph:
        return build_probability_graph()
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/test_output_schema.py -v
```
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add agents/relevancy/executor.py agents/probability_agent/executor.py tests/test_output_schema.py
git commit -m "feat(output-schema): declare schemas on Relevancy and Probability executors"
```

---

### Task 12: Add token budget management to `LangGraphA2AExecutor`

**Files:**
- Modify: `agents/base/executor.py`
- Modify: `requirements.txt`
- Test: `tests/test_token_budget.py`

- [ ] **Step 1: Add `tiktoken` to requirements.txt**

Open `requirements.txt` and add:

```
tiktoken>=0.7.0
```

Install it:
```
pip install tiktoken>=0.7.0
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_token_budget.py
import json
import pytest
from agents.base.executor import LangGraphA2AExecutor
from langgraph.graph.state import CompiledStateGraph


class NoBudgetExecutor(LangGraphA2AExecutor):
    def build_graph(self) -> CompiledStateGraph:
        raise NotImplementedError


class SmallBudgetExecutor(LangGraphA2AExecutor):
    max_context_tokens = 50  # tiny limit for testing
    def build_graph(self) -> CompiledStateGraph:
        raise NotImplementedError


def test_no_limit_count_returns_zero():
    """Without max_context_tokens, _count_tokens returns 0 (skipped)."""
    ex = NoBudgetExecutor()
    assert ex._count_tokens({"output": "hello world"}) == 0


def test_count_tokens_returns_positive_for_large_state():
    """_count_tokens returns a positive number for non-trivial state."""
    ex = SmallBudgetExecutor()
    state = {"output": "word " * 100}
    count = ex._count_tokens(state)
    assert count > 0


def test_is_over_budget_false_under_threshold():
    ex = SmallBudgetExecutor()
    small_state = {"output": "hi"}
    assert ex._is_over_budget(small_state) is False


def test_is_over_budget_true_over_threshold():
    ex = SmallBudgetExecutor()
    big_state = {"output": "word " * 200}  # definitely > 50 tokens * 0.85
    assert ex._is_over_budget(big_state) is True


def test_no_budget_never_over():
    ex = NoBudgetExecutor()
    big_state = {"output": "word " * 1000}
    assert ex._is_over_budget(big_state) is False
```

- [ ] **Step 3: Run tests to verify they fail**

```
pytest tests/test_token_budget.py -v
```
Expected: FAIL — `LangGraphA2AExecutor` has no `max_context_tokens`, `_count_tokens`, or `_is_over_budget`

- [ ] **Step 4: Add token budget attributes and helpers to `LangGraphA2AExecutor`**

In `agents/base/executor.py`, add after `output_schema`:

```python
    # Set to a positive int to enable token budget management.
    # When accumulated state exceeds 85% of this limit, a summarization step
    # is injected before the next node. Leave None to disable (default).
    max_context_tokens: int | None = None
```

Add these methods after `validate_output`:

```python
    def _count_tokens(self, state: dict) -> int:
        """Count tokens in state dict. Returns 0 if max_context_tokens is not set."""
        if self.max_context_tokens is None:
            return 0
        text = str(state)
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except Exception:
            # Fallback: rough approximation (4 chars per token)
            return len(text) // 4

    def _is_over_budget(self, state: dict) -> bool:
        """Return True if state token count exceeds 85% of max_context_tokens."""
        if self.max_context_tokens is None:
            return False
        return self._count_tokens(state) > int(self.max_context_tokens * 0.85)
```

- [ ] **Step 5: Inject summarization in the `astream` event loop when over budget**

In `agents/base/executor.py`, inside the `execute` method, find the line:

```python
            async for event in self.graph.astream(
```

Replace the entire `async for event in self.graph.astream(...)` block with:

```python
            accumulated_state: dict[str, Any] = {}
            async for event in self.graph.astream(
                graph_input,
                config={
                    "configurable": {"executor": self, "task_id": task_id, "context_id": context_id},
                    "callbacks": callbacks,
                },
                stream_mode="updates",
            ):
                # Each event is {node_name: state_update}
                self.check_cancelled(task_id)

                node_name = next(iter(event))
                await self._emit_status(
                    event_queue,
                    task_id,
                    context_id,
                    TaskState.working,
                    f"Running node: {node_name}",
                )
                update = event[node_name]
                if update:
                    result.update(update)
                    accumulated_state.update(update)

                # Token budget check: summarize if over threshold
                if self._is_over_budget(accumulated_state):
                    summary = await self._summarize_state(accumulated_state)
                    accumulated_state = {"summary": summary}
                    result["_context_summary"] = summary

                await self._emit_status(
                    event_queue, task_id, context_id, TaskState.working,
                    f"NODE_OUTPUT::{node_name}::{json.dumps(update or {})}",
                )
```

Add the `_summarize_state` method after `_is_over_budget`:

```python
    async def _summarize_state(self, state: dict) -> str:
        """Call the LLM to compress accumulated state when over token budget."""
        import os
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL") or None,
        )
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        prompt = (
            "Summarize the following analysis concisely, preserving all key findings, "
            f"entities, and conclusions:\n\n{state}"
        )
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=1024,
                temperature=0.0,
            )
            return resp.choices[0].message.content or str(state)
        except Exception:
            # If summarization fails, return a truncated string representation
            return str(state)[:2000]
```

- [ ] **Step 6: Run tests to verify they pass**

```
pytest tests/test_token_budget.py -v
```
Expected: PASS (5 tests)

- [ ] **Step 7: Commit**

```bash
git add agents/base/executor.py requirements.txt tests/test_token_budget.py
git commit -m "feat(token-budget): add token counting and summarization to LangGraphA2AExecutor"
```

---

### Task 13: Set `max_context_tokens` on heavy agents

**Files:**
- Modify: `agents/lead_analyst/executor.py`
- Modify: `agents/specialist_agent/executor.py`
- Modify: `agents/probability_agent/executor.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_token_budget.py`:

```python
from agents.lead_analyst.executor import LeadAnalystExecutor
from agents.specialist_agent.executor import SpecialistExecutor
from agents.probability_agent.executor import ProbabilityExecutor


def test_lead_analyst_has_token_budget():
    assert LeadAnalystExecutor.max_context_tokens == 80000


def test_specialist_has_token_budget():
    assert SpecialistExecutor.max_context_tokens == 60000


def test_probability_has_token_budget():
    assert ProbabilityExecutor.max_context_tokens == 40000
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_token_budget.py -k "test_lead_analyst or test_specialist or test_probability" -v
```
Expected: FAIL — all three are `None`

- [ ] **Step 3: Add `max_context_tokens` to `LeadAnalystExecutor`**

In `agents/lead_analyst/executor.py`, add the class attribute after the class declaration line:

```python
class LeadAnalystExecutor(LangGraphA2AExecutor):
    """Wraps the lead analyst LangGraph in an A2A-compatible executor."""

    max_context_tokens = 80000
```

- [ ] **Step 4: Add `max_context_tokens` to `SpecialistExecutor`**

In `agents/specialist_agent/executor.py`, add the class attribute after the class declaration line:

```python
class SpecialistExecutor(LangGraphA2AExecutor):
    """Runs a specialist graph parameterized by a YAML config."""

    max_context_tokens = 60000
```

- [ ] **Step 5: Add `max_context_tokens` to `ProbabilityExecutor`**

`ProbabilityExecutor` already has `output_schema`. Add `max_context_tokens` below it:

Replace the full file content of `agents/probability_agent/executor.py`:

```python
"""A2A executor for the Probability Forecasting agent."""

from __future__ import annotations

from langgraph.graph.state import CompiledStateGraph

from agents.base import LangGraphA2AExecutor
from agents.probability_agent.graph import build_probability_graph


class ProbabilityExecutor(LangGraphA2AExecutor):
    """Wraps the probability forecasting LangGraph in an A2A-compatible executor."""

    output_schema = {
        "type": "object",
        "required": ["probability", "confidence_interval", "disagreements"],
        "properties": {
            "probability": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "confidence_interval": {
                "type": "object",
                "required": ["low", "high"],
                "properties": {
                    "low": {"type": "number"},
                    "high": {"type": "number"},
                },
            },
            "disagreements": {"type": "array"},
        },
    }

    max_context_tokens = 40000

    def build_graph(self) -> CompiledStateGraph:
        return build_probability_graph()
```

- [ ] **Step 6: Run full Track 2 test suite**

```
pytest tests/test_output_schema.py tests/test_token_budget.py -v
```
Expected: PASS (all tests)

- [ ] **Step 7: Run full test suite to check no regressions**

```
pytest -v
```
Expected: PASS (all existing tests + new tests)

- [ ] **Step 8: Commit**

```bash
git add agents/lead_analyst/executor.py agents/specialist_agent/executor.py agents/probability_agent/executor.py tests/test_token_budget.py
git commit -m "feat(token-budget): set max_context_tokens on Lead Analyst, Specialist, Probability"
```

---

## Final verification

- [ ] **Run the complete test suite one last time**

```
pytest -v
```
Expected: All tests pass, no warnings about missing fixtures or imports.

- [ ] **Verify requirements install cleanly**

```
pip install -r requirements.txt
```
Expected: Clean install, no conflicts.

- [ ] **Final commit**

```bash
git add requirements.txt
git commit -m "chore: add jsonschema, tiktoken to requirements.txt"
```
