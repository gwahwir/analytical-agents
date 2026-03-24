# Task Graph Modal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat `TaskDetailDrawer` with a full-screen modal showing the agent's LangGraph execution graph; clicking a node reveals its actual output, updating live during task execution.

**Architecture:** The executor emits `NODE_OUTPUT::{name}::{json}` and `Running node: {name}` SSE events after each node; the control plane streams these, accumulates `node_outputs` and tracks `running_node` in `TaskRecord`, and publishes updates over the existing WebSocket after each node. Three new React components render the modal: `TaskGraphModal` (shell + WS subscription), `TaskFlowGraph` (ReactFlow with execution-state overlay), and `NodeOutputPanel` (formatted/raw output tabs).

**Tech Stack:** Python / FastAPI / asyncpg (backend), React / ReactFlow (`@xyflow/react`) / Mantine (frontend), pytest / pytest-httpx / pytest-asyncio (tests)

**Spec:** `docs/superpowers/specs/2026-03-23-task-graph-modal-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `control_plane/task_store.py` | Modify | Add `node_outputs` + `running_node` fields to `TaskRecord`; update Postgres `_UPSERT` |
| `control_plane/a2a_client.py` | Modify | Add `baselines`/`key_questions` params + `AsyncGenerator` return type to `stream_message` |
| `agents/base/executor.py` | Modify | Emit `NODE_OUTPUT::` event after each node |
| `control_plane/routes.py` | Modify | Switch `_run_task` to `stream_message`; parse and store node outputs + running_node |
| `tests/conftest.py` | Modify | Replace `a2a_rpc_callback` with SSE-format helpers; all dispatch now uses `stream_message` |
| `tests/test_task_store.py` | Create | Unit tests for `node_outputs`/`running_node` field serialization |
| `tests/test_node_output_stream.py` | Create | Unit tests for `_run_task` streaming + NODE_OUTPUT parsing |
| `dashboard/src/components/TaskGraphModal/NodeOutputPanel.jsx` | Create | Formatted/raw output panel for a selected node |
| `dashboard/src/components/TaskGraphModal/TaskFlowGraph.jsx` | Create | ReactFlow graph with execution-state overlay |
| `dashboard/src/components/TaskGraphModal.jsx` | Create | Full-screen modal shell with WS subscription and layout |
| `dashboard/src/components/TaskDetailDrawer.jsx` | Delete | Replaced by TaskGraphModal |
| `dashboard/src/App.jsx` | Modify | Swap TaskDetailDrawer for TaskGraphModal |

---

## Task 1: Add `node_outputs` and `running_node` to `TaskRecord`

**Files:**
- Modify: `control_plane/task_store.py`
- Create: `tests/test_task_store.py`

- [ ] **Write the failing tests**

```python
# tests/test_task_store.py
from __future__ import annotations
import json
import pytest
from control_plane.task_store import TaskRecord, TaskState


def test_task_record_node_outputs_default():
    r = TaskRecord(task_id="t1", agent_id="echo-agent")
    assert r.node_outputs == {}


def test_task_record_running_node_default():
    r = TaskRecord(task_id="t1", agent_id="echo-agent")
    assert r.running_node == ""


def test_task_record_to_dict_includes_node_outputs_and_running_node():
    r = TaskRecord(task_id="t1", agent_id="echo-agent")
    r.node_outputs["receive"] = '{"input": "hello"}'
    r.running_node = "analyze"
    d = r.to_dict()
    assert d["node_outputs"]["receive"] == '{"input": "hello"}'
    assert d["running_node"] == "analyze"


def test_task_record_from_row_deserializes_node_outputs():
    row = {
        "task_id": "t1", "agent_id": "echo-agent", "instance_url": "",
        "state": "completed", "input_text": "hi", "baselines": "",
        "key_questions": "", "output_text": "HI", "error": "",
        "created_at": 1000.0, "updated_at": 1001.0, "a2a_task": "{}",
        "node_outputs": '{"receive": "{\\"input\\": \\"hi\\"}"}',
        "running_node": "analyze",
    }
    r = TaskRecord.from_row(row)
    assert r.node_outputs == {"receive": '{"input": "hi"}'}
    assert r.running_node == "analyze"


def test_task_record_from_row_missing_fields_use_defaults():
    row = {
        "task_id": "t1", "agent_id": "echo-agent", "instance_url": "",
        "state": "completed", "input_text": "hi", "baselines": "",
        "key_questions": "", "output_text": "", "error": "",
        "created_at": 1000.0, "updated_at": 1001.0, "a2a_task": "{}",
        # node_outputs and running_node intentionally absent
    }
    r = TaskRecord.from_row(row)
    assert r.node_outputs == {}
    assert r.running_node == ""
```

- [ ] **Run tests to confirm they fail**

```bash
pytest tests/test_task_store.py -v
```
Expected: 5 failures

- [ ] **Add `node_outputs` and `running_node` to `TaskRecord` in `control_plane/task_store.py`**

Add two fields after `a2a_task`:
```python
node_outputs: dict[str, str] = field(default_factory=dict)
running_node: str = ""
```

In `to_dict()`, add:
```python
"node_outputs": self.node_outputs,
"running_node": self.running_node,
```

In `from_row()`, add after the `a2a_task` block:
```python
node_outputs_raw = row.get("node_outputs", "{}")
node_outputs = json.loads(node_outputs_raw) if isinstance(node_outputs_raw, str) else (node_outputs_raw or {})
running_node = row.get("running_node", "")
```
Pass both to the constructor: `node_outputs=node_outputs, running_node=running_node`.

- [ ] **Update Postgres migration and `_UPSERT`**

Add after `_ADD_STRUCTURED_INPUT_COLUMNS`:
```python
_ADD_NODE_OUTPUT_COLUMNS = """
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS node_outputs TEXT NOT NULL DEFAULT '{}';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS running_node TEXT NOT NULL DEFAULT '';
"""
```

Update `_UPSERT` to include `node_outputs` (`$13`) and `running_node` (`$14`) in the INSERT list and `ON CONFLICT DO UPDATE SET` clause:
```python
_UPSERT = """
INSERT INTO tasks
    (task_id, agent_id, instance_url, state, input_text, baselines, key_questions,
     output_text, error, created_at, updated_at, a2a_task, node_outputs, running_node)
VALUES
    ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
ON CONFLICT (task_id) DO UPDATE SET
    state        = EXCLUDED.state,
    output_text  = EXCLUDED.output_text,
    error        = EXCLUDED.error,
    updated_at   = EXCLUDED.updated_at,
    a2a_task     = EXCLUDED.a2a_task,
    node_outputs = EXCLUDED.node_outputs,
    running_node = EXCLUDED.running_node;
"""
```

In `PostgresTaskStore.init()`, call `await conn.execute(_ADD_NODE_OUTPUT_COLUMNS)`.

In `PostgresTaskStore.save()`, add `json.dumps(record.node_outputs)` as `$13` and `record.running_node` as `$14`.

- [ ] **Run tests**

```bash
pytest tests/test_task_store.py -v
```
Expected: 5 passed

- [ ] **Commit**

```bash
git add control_plane/task_store.py tests/test_task_store.py
git commit -m "feat: add node_outputs and running_node fields to TaskRecord"
```

---

## Task 2: Add `baselines`/`key_questions` to `stream_message`

**Files:**
- Modify: `control_plane/a2a_client.py`
- Create: `tests/test_a2a_client.py`

> This task must be complete before Task 4 (routes.py depends on the updated signature).

- [ ] **Write the failing tests**

```python
# tests/test_a2a_client.py
from __future__ import annotations
import json
import httpx
import pytest
from control_plane.a2a_client import A2AClient


async def test_stream_message_includes_baselines_in_metadata(httpx_mock):
    captured = {}

    def capture(request: httpx.Request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, content=b"", headers={"content-type": "text/event-stream"})

    httpx_mock.add_callback(capture, url="http://agent:8001/")
    client = A2AClient("http://agent:8001")
    gen = client.stream_message("hello", baselines="some baseline")
    try:
        async for _ in gen:
            pass
    except Exception:
        pass
    finally:
        await gen.aclose()
        await client.close()

    metadata = captured.get("params", {}).get("message", {}).get("metadata", {})
    assert metadata.get("baselines") == "some baseline"


async def test_stream_message_omits_empty_baselines(httpx_mock):
    captured = {}

    def capture(request: httpx.Request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, content=b"", headers={"content-type": "text/event-stream"})

    httpx_mock.add_callback(capture, url="http://agent:8001/")
    client = A2AClient("http://agent:8001")
    gen = client.stream_message("hello", baselines="")
    try:
        async for _ in gen:
            pass
    except Exception:
        pass
    finally:
        await gen.aclose()
        await client.close()

    metadata = captured.get("params", {}).get("message", {}).get("metadata", {})
    assert "baselines" not in metadata


async def test_stream_message_supports_aclose():
    client = A2AClient("http://agent:8001")
    gen = client.stream_message("hello")
    assert hasattr(gen, "aclose"), "must return AsyncGenerator"
    await gen.aclose()
    await client.close()
```

- [ ] **Run tests to confirm they fail**

```bash
pytest tests/test_a2a_client.py -v
```

- [ ] **Update `stream_message` in `control_plane/a2a_client.py`**

Change the return type annotation to `AsyncGenerator[dict[str, Any], None]`. Add `AsyncGenerator` to the `typing` import line.

Add `baselines: str = ""` and `key_questions: str = ""` keyword parameters. Build metadata identically to `send_message` — only include keys when non-empty:

```python
async def stream_message(
    self,
    text: str,
    *,
    task_id: str | None = None,
    context_id: str | None = None,
    parent_span_id: str | None = None,
    baselines: str = "",
    key_questions: str = "",
) -> AsyncGenerator[dict[str, Any], None]:
    metadata: dict[str, Any] = {}
    if parent_span_id:
        metadata["parentSpanId"] = parent_span_id
    if baselines:
        metadata["baselines"] = baselines
    if key_questions:
        metadata["keyQuestions"] = key_questions

    message: dict[str, Any] = {
        "kind": "message",
        "role": "user",
        "messageId": str(uuid.uuid4()),
        "parts": [{"kind": "text", "text": text}],
    }
    if task_id:
        message["taskId"] = task_id
    if context_id:
        message["contextId"] = context_id
    if metadata:
        message["metadata"] = metadata
    # ... rest unchanged
```

- [ ] **Run tests**

```bash
pytest tests/test_a2a_client.py -v
```
Expected: 3 passed

- [ ] **Commit**

```bash
git add control_plane/a2a_client.py tests/test_a2a_client.py
git commit -m "feat: add baselines/key_questions to stream_message, update to AsyncGenerator"
```

---

## Task 3: Emit `NODE_OUTPUT::` events from executor

**Files:**
- Modify: `agents/base/executor.py`

- [ ] **Add `import json` and emit the node output event**

At the top of `agents/base/executor.py`, add `import json` (it's not currently imported).

In the `async for event in self.graph.astream(...)` loop, after the `result.update(update)` line, add one new `_emit_status` call:

```python
node_name = next(iter(event))
await self._emit_status(
    event_queue, task_id, context_id, TaskState.working,
    f"Running node: {node_name}",          # existing line
)
update = event[node_name]
if update:
    result.update(update)
await self._emit_status(                    # NEW
    event_queue, task_id, context_id, TaskState.working,
    f"NODE_OUTPUT::{node_name}::{json.dumps(update or {})}",
)
```

- [ ] **Verify existing tests still pass**

```bash
pytest tests/ -v --ignore=tests/test_task_store.py --ignore=tests/test_a2a_client.py
```
Expected: all previously passing tests still pass

- [ ] **Commit**

```bash
git add agents/base/executor.py
git commit -m "feat: emit NODE_OUTPUT events from executor after each node"
```

---

## Task 4: Update `conftest.py` to SSE format and switch `_run_task` to streaming

**Files:**
- Modify: `control_plane/routes.py`
- Modify: `tests/conftest.py`
- Create: `tests/test_node_output_stream.py`

> **Why conftest must change:** All task dispatch now uses `stream_message` which expects an `text/event-stream` SSE response, not a plain JSON-RPC body. The existing `a2a_rpc_callback` returns JSON — it must be replaced with an SSE equivalent so the existing lifecycle tests continue to pass.

- [ ] **Update `tests/conftest.py` — replace JSON-RPC helpers with SSE helpers**

Replace `a2a_rpc` and `a2a_rpc_callback` with SSE versions. The SSE body format that `stream_message` reads is `data: {json}\n\n`. Keep `a2a_cancel_response` unchanged (cancel still uses `send_message`/JSON-RPC):

```python
# Add to top of conftest.py:
import json  # if not already there

def a2a_sse_event(text: str, state: str = "completed") -> bytes:
    """Single SSE event in the format stream_message expects."""
    event_data = {
        "result": {
            "status": {
                "state": state,
                "message": {"parts": [{"text": text}]},
            }
        }
    }
    return f"data: {json.dumps(event_data)}\n\n".encode()


def a2a_sse_response(text: str, state: str = "completed") -> httpx.Response:
    """SSE httpx.Response that stream_message will parse as one event."""
    return httpx.Response(
        200,
        content=a2a_sse_event(f"ECHO: {text.upper()}", state),
        headers={"content-type": "text/event-stream"},
    )


def a2a_rpc_callback(text: str, state: str = "completed"):
    """SSE callback for httpx_mock — replaces the old JSON-RPC version."""
    def callback(request: httpx.Request) -> httpx.Response:
        return a2a_sse_response(text, state)
    return callback
```

Remove the old `make_a2a_response`, `a2a_rpc`, and `a2a_rpc_callback` functions. Keep `a2a_cancel_response` as-is.

- [ ] **Run the existing lifecycle tests to confirm they still pass** (routes.py not changed yet — this just validates the SSE helper format)

```bash
pytest tests/test_task_lifecycle.py -v
```
Expected: all pass (routes still uses `send_message`, tests pass because `a2a_rpc_callback` format doesn't matter until Task 4b)

- [ ] **Write the failing streaming tests**

```python
# tests/test_node_output_stream.py
from __future__ import annotations
import json
import pytest
from unittest.mock import AsyncMock, patch

from tests.conftest import FAKE_AGENT_ID, wait_for_task


def make_sse_event(state: str, text: str) -> dict:
    return {"result": {"status": {"state": state, "message": {"parts": [{"text": text}]}}}}


async def _gen(*events):
    for e in events:
        yield e


async def test_node_outputs_populated_after_stream(client, task_store):
    node_payload = json.dumps({"output": "HELLO WORLD"})

    async def fake_stream(*args, **kwargs):
        yield make_sse_event("working", "Running node: process")
        yield make_sse_event("working", f"NODE_OUTPUT::process::{node_payload}")
        yield make_sse_event("completed", "HELLO WORLD")

    with patch("control_plane.routes.A2AClient") as MockClient:
        MockClient.return_value.stream_message = fake_stream
        MockClient.return_value.close = AsyncMock()
        resp = await client.post(f"/agents/{FAKE_AGENT_ID}/tasks", json={"text": "hello"})
        task_id = resp.json()["task_id"]
        result = await wait_for_task(client, FAKE_AGENT_ID, task_id)

    assert result["state"] == "completed"
    assert result["node_outputs"]["process"] == node_payload


async def test_running_node_tracked_in_record(client, task_store):
    """running_node in the task dict should reflect the currently-executing node."""
    snapshots = []

    async def fake_stream(*args, **kwargs):
        yield make_sse_event("working", "Running node: process")
        # After this, control plane should publish with running_node="process"
        yield make_sse_event("working", f"NODE_OUTPUT::process::{json.dumps({})}")
        yield make_sse_event("completed", "done")

    with patch("control_plane.routes.A2AClient") as MockClient:
        MockClient.return_value.stream_message = fake_stream
        MockClient.return_value.close = AsyncMock()
        resp = await client.post(f"/agents/{FAKE_AGENT_ID}/tasks", json={"text": "hello"})
        task_id = resp.json()["task_id"]
        result = await wait_for_task(client, FAKE_AGENT_ID, task_id)

    assert result["state"] == "completed"
    # After completion running_node should be cleared
    assert result["running_node"] == ""


async def test_node_output_with_double_colon_in_json(client, task_store):
    payload = json.dumps({"url": "http://example.com::8080/path"})

    async def fake_stream(*args, **kwargs):
        yield make_sse_event("working", f"NODE_OUTPUT::mynode::{payload}")
        yield make_sse_event("completed", "done")

    with patch("control_plane.routes.A2AClient") as MockClient:
        MockClient.return_value.stream_message = fake_stream
        MockClient.return_value.close = AsyncMock()
        resp = await client.post(f"/agents/{FAKE_AGENT_ID}/tasks", json={"text": "hello"})
        task_id = resp.json()["task_id"]
        result = await wait_for_task(client, FAKE_AGENT_ID, task_id)

    stored = json.loads(result["node_outputs"]["mynode"])
    assert stored["url"] == "http://example.com::8080/path"


async def test_stream_ends_without_terminal_marks_failed(client, task_store):
    async def fake_stream(*args, **kwargs):
        yield make_sse_event("working", "Running node: process")
        # stream ends here

    with patch("control_plane.routes.A2AClient") as MockClient:
        MockClient.return_value.stream_message = fake_stream
        MockClient.return_value.close = AsyncMock()
        resp = await client.post(f"/agents/{FAKE_AGENT_ID}/tasks", json={"text": "hello"})
        task_id = resp.json()["task_id"]
        result = await wait_for_task(client, FAKE_AGENT_ID, task_id)

    assert result["state"] == "failed"
    assert "terminal" in result["error"].lower()


async def test_invalid_node_output_json_skipped(client, task_store):
    async def fake_stream(*args, **kwargs):
        yield make_sse_event("working", "NODE_OUTPUT::badnode::NOT_VALID_JSON")
        yield make_sse_event("completed", "fine")

    with patch("control_plane.routes.A2AClient") as MockClient:
        MockClient.return_value.stream_message = fake_stream
        MockClient.return_value.close = AsyncMock()
        resp = await client.post(f"/agents/{FAKE_AGENT_ID}/tasks", json={"text": "hello"})
        task_id = resp.json()["task_id"]
        result = await wait_for_task(client, FAKE_AGENT_ID, task_id)

    assert result["state"] == "completed"
    assert "badnode" not in result["node_outputs"]
```

- [ ] **Run to confirm they fail**

```bash
pytest tests/test_node_output_stream.py -v
```
Expected: failures (routes still uses `send_message`)

- [ ] **Rewrite `_run_task` in `control_plane/routes.py`**

Add `import json` at the top of `routes.py` (it's currently missing).

Replace the block from `result = await client.send_message(...)` through to `record.a2a_task = result` with:

```python
gen = client.stream_message(
    text,
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
                    json.loads(json_payload)  # validate
                    record.node_outputs[node_name] = json_payload
                    record.running_node = ""   # node just completed
                    await _task_store.save(record)
                    await _broker.publish(task_id, record.to_dict())
                except json.JSONDecodeError:
                    logger.warning("node_output_invalid_json", task_id=task_id, node=node_name)
            continue

        # Track currently-running node (non-NODE_OUTPUT working events)
        if state_str == "working" and text_val.startswith("Running node: "):
            node_name = text_val[len("Running node: "):]
            record.running_node = node_name
            await _task_store.save(record)
            await _broker.publish(task_id, record.to_dict())
            continue

        if state_str in ("completed", "failed", "canceled"):
            record.state = TaskState(state_str)
            record.output_text = text_val
            record.running_node = ""
            if record.state == TaskState.FAILED:
                record.error = text_val or "Agent returned failed state with no details"
            break
    else:
        # Only mark failed if the cancel endpoint hasn't already set a terminal state.
        # `_run_task` holds its own in-memory `record` copy; the cancel endpoint writes
        # a fresh copy to the store and sets CANCELED — we must not overwrite it.
        terminal = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED}
        fresh = await _task_store.get(task_id)
        if fresh is None or fresh.state not in terminal:
            record.state = TaskState.FAILED
            record.error = "Stream ended without a terminal status event"
        else:
            record.state = fresh.state
finally:
    await gen.aclose()
```

Keep all five `except` handlers and the `finally` block unchanged. Keep `task_duration`, `tasks_completed`, `tasks_failed` metric recording after the loop. Keep the final `await _task_store.save(record)` and `await _broker.publish(task_id, record.to_dict())` calls.

- [ ] **Update `test_cancel_task` in `tests/test_task_lifecycle.py`**

With streaming, a mock that emits only `state="working"` events and then closes will trigger the `for...else` clause — the task would end as `failed` (or `canceled` if the cancel endpoint raced ahead). The old static `a2a_rpc_callback("to cancel", state="working")` approach no longer works. Replace `test_cancel_task` with a patched version that suspends the stream via `asyncio.Event`:

```python
async def test_cancel_task(client, httpx_mock: HTTPXMock):
    import asyncio
    from unittest.mock import AsyncMock, patch

    hold = asyncio.Event()

    async def fake_stream(*args, **kwargs):
        yield {"result": {"status": {"state": "working", "message": {"parts": [{"text": "Running node: process"}]}}}}
        await hold.wait()  # suspend until cancel fires

    task_id_ref = [None]

    with patch("control_plane.routes.A2AClient") as MockClient:
        # stream_message keeps the task alive until hold is set
        MockClient.return_value.stream_message = fake_stream
        MockClient.return_value.close = AsyncMock()

        # cancel_task is called by the cancel endpoint — mock it to unblock the stream
        async def fake_cancel(*args, **kwargs):
            hold.set()
        MockClient.return_value.cancel_task = AsyncMock(side_effect=fake_cancel)

        resp = await client.post(f"/agents/{FAKE_AGENT_ID}/tasks", json={"text": "to cancel"})
        assert resp.status_code == 202
        task_id_ref[0] = resp.json()["task_id"]
        task_id = task_id_ref[0]

        # Wait until _run_task has processed the "Running node" event (state=working in record)
        deadline = asyncio.get_event_loop().time() + 5.0
        while asyncio.get_event_loop().time() < deadline:
            r = await client.get(f"/agents/{FAKE_AGENT_ID}/tasks/{task_id}")
            if r.status_code == 200 and r.json()["state"] == "working":
                break
            await asyncio.sleep(0.05)
        else:
            pytest.fail("Task did not reach working state within timeout")

        resp = await client.delete(f"/agents/{FAKE_AGENT_ID}/tasks/{task_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    resp = await client.get(f"/agents/{FAKE_AGENT_ID}/tasks/{task_id}")
    assert resp.json()["state"] == "canceled"
```

> **Why the hold pattern works:** The cancel endpoint calls `MockClient.return_value.cancel_task` which sets `hold` and returns, then stores `CANCELED` state. The stream then unblocks and ends (without a terminal SSE event), hitting the `else` guard. The guard re-reads the store, finds `state=canceled` (already terminal), and does NOT overwrite it.

> **Why `state == "working"` is observable:** `_run_task` sets `record.state = TaskState.WORKING` right before entering the streaming loop (this is existing code that is not changed by this plan). The "Running node: process" event updates `running_node` but `state` is already `working`. The polling loop correctly observes `working`.

- [ ] **Run all tests**

```bash
pytest tests/ -v
```
Expected: all tests pass, including all 5 new streaming tests

- [ ] **Commit**

```bash
git add control_plane/routes.py tests/conftest.py tests/test_node_output_stream.py tests/test_task_lifecycle.py
git commit -m "feat: switch _run_task to stream_message, track running_node and node_outputs"
```

---

## Task 5: Create `NodeOutputPanel.jsx`

**Files:**
- Create: `dashboard/src/components/TaskGraphModal/NodeOutputPanel.jsx`

- [ ] **Create directory and file**

```bash
mkdir -p dashboard/src/components/TaskGraphModal
```

```jsx
// dashboard/src/components/TaskGraphModal/NodeOutputPanel.jsx
import { useState } from "react";
import { Tabs, Text, Code, Badge, Group, Stack, List } from "@mantine/core";

function renderValue(value) {
  if (typeof value === "string") {
    return <Text size="sm" style={{ color: "var(--hud-text-primary)", whiteSpace: "pre-wrap" }}>{value}</Text>;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return (
      <Text size="sm" style={{ color: "var(--hud-green)", fontFamily: "monospace" }}>
        {String(value)}
      </Text>
    );
  }
  if (Array.isArray(value)) {
    const allShort = value.every((v) => typeof v === "string" && v.length <= 40);
    if (allShort) {
      return (
        <Group gap="xs" wrap="wrap">
          {value.map((v, i) => (
            <Badge key={i} variant="outline" color="hud-cyan" size="sm">{v}</Badge>
          ))}
        </Group>
      );
    }
    return (
      <List size="sm" style={{ color: "var(--hud-text-primary)" }}>
        {value.map((v, i) => <List.Item key={i}>{String(v)}</List.Item>)}
      </List>
    );
  }
  return (
    <Code block style={{ color: "var(--hud-cyan)", backgroundColor: "var(--hud-bg-surface)", fontSize: 11 }}>
      {JSON.stringify(value, null, 2)}
    </Code>
  );
}

export default function NodeOutputPanel({ nodeId, nodeOutputJson, nodeState, onClose }) {
  const [tab, setTab] = useState("formatted");

  const header = (
    <Group justify="space-between" mb="sm">
      <Text size="xs" fw={600} style={{ color: "var(--hud-cyan)", letterSpacing: "1px", textTransform: "uppercase" }}>
        [ {nodeId} ] OUTPUT
      </Text>
      <Text size="xs" style={{ color: "var(--hud-text-dimmed)", cursor: "pointer" }} onClick={onClose}>
        ✕
      </Text>
    </Group>
  );

  if (nodeOutputJson === undefined && nodeState === "running") {
    return <div style={{ padding: 12 }}>{header}<Text size="sm" style={{ color: "var(--hud-text-dimmed)" }}>Node is running<span style={{ animation: "blink-cursor 1s step-end infinite" }}>_</span></Text></div>;
  }
  if (nodeOutputJson === undefined && nodeState === "pending") {
    return <div style={{ padding: 12 }}>{header}<Text size="sm" style={{ color: "var(--hud-text-dimmed)" }}>Node has not run yet</Text></div>;
  }
  if (nodeOutputJson === undefined) {
    return <div style={{ padding: 12 }}>{header}<Text size="sm" style={{ color: "var(--hud-text-dimmed)" }}>Output not available for this task</Text></div>;
  }
  if (nodeOutputJson === "{}") {
    return <div style={{ padding: 12 }}>{header}<Text size="sm" style={{ color: "var(--hud-text-dimmed)" }}>Node produced no output</Text></div>;
  }

  let parsed;
  try {
    parsed = JSON.parse(nodeOutputJson);
  } catch {
    return (
      <div style={{ padding: 12 }}>
        {header}
        <Badge color="hud-amber" variant="light" mb="xs">Parse error</Badge>
        <Code block style={{ color: "var(--hud-text-primary)", backgroundColor: "var(--hud-bg-surface)", fontSize: 11 }}>
          {nodeOutputJson}
        </Code>
      </div>
    );
  }

  return (
    <div style={{ padding: 12, height: "100%", overflow: "auto" }}>
      {header}
      <Tabs value={tab} onChange={setTab}>
        <Tabs.List mb="sm">
          <Tabs.Tab value="formatted" style={{ fontSize: 11, letterSpacing: "1px" }}>FORMATTED</Tabs.Tab>
          <Tabs.Tab value="raw" style={{ fontSize: 11, letterSpacing: "1px" }}>RAW</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="formatted">
          <Stack gap="sm">
            {Object.entries(parsed).map(([key, value]) => (
              <div key={key}>
                <Text size="xs" mb={4} style={{ color: "var(--hud-text-dimmed)", letterSpacing: "1px", textTransform: "uppercase", fontSize: 11 }}>{key}</Text>
                {renderValue(value)}
              </div>
            ))}
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="raw">
          <Code block style={{ color: "var(--hud-cyan)", backgroundColor: "var(--hud-bg-surface)", fontSize: 11, whiteSpace: "pre-wrap" }}>
            {JSON.stringify(parsed, null, 2)}
          </Code>
        </Tabs.Panel>
      </Tabs>
    </div>
  );
}
```

- [ ] **Verify build**

```bash
cd dashboard && npm run build
```

- [ ] **Commit**

```bash
git add dashboard/src/components/TaskGraphModal/NodeOutputPanel.jsx
git commit -m "feat: add NodeOutputPanel with formatted/raw tabs"
```

---

## Task 6: Create `TaskFlowGraph.jsx`

**Files:**
- Create: `dashboard/src/components/TaskGraphModal/TaskFlowGraph.jsx`

**Key data note:** `taskState.running_node` is the bare node name published by the backend when a `"Running node: X"` event is received. It is `""` (empty string) when no node is currently executing. Read it directly from the task dict — no local state needed.

- [ ] **Create the file**

```jsx
// dashboard/src/components/TaskGraphModal/TaskFlowGraph.jsx
import { useMemo } from "react";
import { ReactFlow, Background, Controls } from "@xyflow/react";
import { Text } from "@mantine/core";
import { computeLayout } from "../graph/layout";

const STATE_STYLES = {
  pending:   { background: "#0d1117", border: "1px solid #374151",  color: "#6b7280", opacity: 0.5, boxShadow: "none" },
  running:   { background: "#1a1200", border: "1px solid #f59e0b",  color: "#fbbf24", opacity: 1,   boxShadow: "0 0 12px rgba(245,158,11,0.5)" },
  completed: { background: "#0a1a0a", border: "1px solid #22c55e",  color: "#4ade80", opacity: 1,   boxShadow: "none" },
  failed:    { background: "#1a0505", border: "1px solid #ef4444",  color: "#f87171", opacity: 1,   boxShadow: "none" },
  selected:  { background: "#001a2a", border: "2px solid #00d4ff",  color: "#00d4ff", opacity: 1,   boxShadow: "0 0 14px rgba(0,212,255,0.3)" },
};

const DOT_COLORS = {
  running: "#f59e0b", completed: "#22c55e", failed: "#ef4444", selected: "#00d4ff",
};

function ExecutionNode({ data }) {
  const style = STATE_STYLES[data.executionState] || STATE_STYLES.pending;
  const dotColor = DOT_COLORS[data.executionState];
  return (
    <div style={{ ...style, borderRadius: 0, minWidth: 140, padding: "6px 12px", fontFamily: "monospace", fontSize: 11, letterSpacing: "0.5px", textTransform: "uppercase", display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
      {dotColor && <span style={{ display: "inline-block", width: 6, height: 6, borderRadius: "50%", backgroundColor: dotColor, flexShrink: 0 }} />}
      {data.label}
    </div>
  );
}

const nodeTypes = { executionNode: ExecutionNode };

function getExecutionState({ bareId, selectedNodeId, runningNode, nodeOutputs, taskFailed }) {
  if (bareId === selectedNodeId) return "selected";
  if (runningNode && bareId === runningNode) return "running";
  if (nodeOutputs && bareId in nodeOutputs) return "completed";
  if (taskFailed && nodeOutputs && !(bareId in nodeOutputs)) return "failed";
  return "pending";
}

export default function TaskFlowGraph({ agentData, taskState, selectedNodeId, onNodeSelect }) {
  if (!agentData) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%" }}>
        <Text size="sm" style={{ color: "var(--hud-text-dimmed)" }}>
          Graph topology unavailable — agent is no longer registered
        </Text>
      </div>
    );
  }

  const nodeOutputs = taskState?.node_outputs;
  const runningNode = taskState?.running_node || null;
  const taskFailed = taskState?.state === "failed";

  const { nodes: rawNodes, edges } = useMemo(
    () => computeLayout({ agents: [agentData], cross_agent_edges: [] }),
    [agentData]
  );

  const nodes = useMemo(() => rawNodes.map((node) => {
    if (node.type !== "graphNode") return node;
    const bareId = node.id.split(":").slice(1).join(":");
    const executionState = getExecutionState({ bareId, selectedNodeId, runningNode, nodeOutputs, taskFailed });
    return { ...node, type: "executionNode", data: { ...node.data, executionState } };
  }), [rawNodes, selectedNodeId, runningNode, nodeOutputs, taskFailed]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.3 }}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={true}
      onNodeClick={(_, node) => {
        if (node.type !== "executionNode") return;
        onNodeSelect(node.id.split(":").slice(1).join(":"));
      }}
      proOptions={{ hideAttribution: true }}
    >
      <Background color="rgba(0, 212, 255, 0.06)" gap={20} />
      <Controls showInteractive={false} style={{ background: "var(--hud-bg-panel)", border: "1px solid var(--hud-border)", borderRadius: 0 }} />
    </ReactFlow>
  );
}
```

**Note on `failed` state:** when `taskState.state === "failed"`, any node that has NO entry in `node_outputs` renders as `"failed"`. This is a conservative heuristic (all unfinished nodes look failed) since the exact failed node cannot be determined from the stored data. Nodes that completed before the failure remain green.

- [ ] **Verify build**

```bash
cd dashboard && npm run build
```

- [ ] **Commit**

```bash
git add dashboard/src/components/TaskGraphModal/TaskFlowGraph.jsx
git commit -m "feat: add TaskFlowGraph with execution-state overlay"
```

---

## Task 7: Create `TaskGraphModal.jsx`

**Files:**
- Create: `dashboard/src/components/TaskGraphModal.jsx`

**Key design note:** `runningNode` is NOT tracked in local state. It comes directly from `taskState.running_node` (populated by the backend via WS). This ensures the amber "running" dot reflects actual backend state.

- [ ] **Create the file**

```jsx
// dashboard/src/components/TaskGraphModal.jsx
import { useState, useEffect } from "react";
import { Modal, Stack, Text, Badge, Code, Button, Group } from "@mantine/core";
import { cancelTask, subscribeToTask } from "../hooks/useApi";
import TaskFlowGraph from "./TaskGraphModal/TaskFlowGraph";
import NodeOutputPanel from "./TaskGraphModal/NodeOutputPanel";

const STATE_COLORS = {
  completed: "hud-green", working: "hud-amber", submitted: "gray",
  canceled: "hud-red", failed: "hud-red", "input-required": "hud-violet",
};

const LIVE_STATES = new Set(["submitted", "working"]);

export default function TaskGraphModal({ task, graphData, onClose, onCancelled }) {
  const [taskState, setTaskState] = useState(task);
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [cancelling, setCancelling] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);

  useEffect(() => {
    setTaskState(task);
    setSelectedNodeId(null);
    setCancelling(false);
    setConfirmCancel(false);
  }, [task?.task_id]);

  useEffect(() => {
    if (!task || !LIVE_STATES.has(task.state)) return;
    const unsub = subscribeToTask(task.task_id, (msg) => setTaskState(msg));
    return unsub;
  }, [task?.task_id, task?.state]);

  if (!task) return null;

  const agentData = graphData?.agents?.find((a) => a.id === taskState?.agent_id) ?? null;
  const canCancel = LIVE_STATES.has(taskState?.state);

  const handleCancel = async () => {
    if (!confirmCancel) { setConfirmCancel(true); return; }
    setCancelling(true);
    try {
      await cancelTask(taskState.agent_id, taskState.task_id);
      onCancelled(taskState.task_id);
    } catch (err) {
      alert("Cancel failed: " + err.message);
    } finally {
      setCancelling(false);
      setConfirmCancel(false);
    }
  };

  // nodeOutputJson: undefined if node_outputs absent (old record), undefined if key missing, else string
  const nodeOutputs = taskState?.node_outputs;
  const nodeOutputJson = selectedNodeId
    ? (nodeOutputs === undefined ? undefined : nodeOutputs?.[selectedNodeId])
    : undefined;

  const nodeState = (() => {
    if (!selectedNodeId) return "pending";
    const runningNode = taskState?.running_node;
    if (taskState?.state === "failed" && nodeOutputs && !(selectedNodeId in nodeOutputs)) return "failed";
    if (nodeOutputs?.[selectedNodeId] !== undefined) return "completed";
    if (runningNode && selectedNodeId === runningNode) return "running";
    return "pending";
  })();

  return (
    <Modal
      opened={!!task}
      onClose={onClose}
      fullScreen
      title={<Text fw={600} style={{ textTransform: "uppercase", letterSpacing: "2px", fontSize: 14 }}>[ TASK GRAPH ]</Text>}
      styles={{ body: { padding: 0, height: "calc(100vh - 60px)", display: "flex" }, content: { display: "flex", flexDirection: "column" } }}
    >
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {/* Graph — 65% */}
        <div style={{ flex: "0 0 65%", borderRight: "1px solid var(--hud-border)" }}>
          <TaskFlowGraph
            agentData={agentData}
            taskState={taskState}
            selectedNodeId={selectedNodeId}
            onNodeSelect={setSelectedNodeId}
          />
        </div>

        {/* Right panel — 35% */}
        <div style={{ flex: "0 0 35%", display: "flex", flexDirection: "column", overflow: "hidden" }}>
          {/* Metadata */}
          <Stack gap="xs" p="md" style={{ borderBottom: "1px solid var(--hud-border)", flexShrink: 0 }}>
            <div>
              <Text size="xs" style={{ color: "var(--hud-text-dimmed)", letterSpacing: "1px" }} tt="uppercase">Task ID</Text>
              <Code style={{ fontSize: 11 }}>{taskState?.task_id}</Code>
            </div>
            <div>
              <Text size="xs" style={{ color: "var(--hud-text-dimmed)", letterSpacing: "1px" }} tt="uppercase">Agent</Text>
              <Text size="sm">{taskState?.agent_id}</Text>
            </div>
            <div>
              <Text size="xs" style={{ color: "var(--hud-text-dimmed)", letterSpacing: "1px" }} tt="uppercase">State</Text>
              <Badge color={STATE_COLORS[taskState?.state] || "gray"} variant="light">{taskState?.state}</Badge>
            </div>
            <div>
              <Text size="xs" style={{ color: "var(--hud-text-dimmed)", letterSpacing: "1px" }} tt="uppercase">Created</Text>
              <Text size="sm">{taskState?.created_at ? new Date(taskState.created_at * 1000).toLocaleString() : "—"}</Text>
            </div>
            {canCancel && (
              <Button
                color="hud-red"
                variant={confirmCancel ? "filled" : "outline"}
                size="xs"
                onClick={handleCancel}
                loading={cancelling}
                style={confirmCancel ? { boxShadow: "0 0 12px rgba(255,61,61,0.3)" } : { borderColor: "var(--hud-red)", color: "var(--hud-red)" }}
              >
                {confirmCancel ? "CLICK AGAIN TO CONFIRM" : "CANCEL TASK"}
              </Button>
            )}
          </Stack>

          {/* Node output */}
          <div style={{ flex: 1, overflow: "auto", backgroundColor: "var(--hud-bg-surface)" }}>
            {selectedNodeId ? (
              <NodeOutputPanel
                nodeId={selectedNodeId}
                nodeOutputJson={nodeOutputJson}
                nodeState={nodeState}
                onClose={() => setSelectedNodeId(null)}
              />
            ) : (
              <div style={{ padding: 12 }}>
                <Text size="xs" style={{ color: "var(--hud-text-dimmed)" }}>
                  Click a node to view its output
                  <span style={{ animation: "blink-cursor 1s step-end infinite" }}>_</span>
                </Text>
              </div>
            )}
          </div>
        </div>
      </div>
    </Modal>
  );
}
```

- [ ] **Verify build**

```bash
cd dashboard && npm run build
```

- [ ] **Commit**

```bash
git add dashboard/src/components/TaskGraphModal.jsx
git commit -m "feat: add TaskGraphModal full-screen modal"
```

---

## Task 8: Wire into `App.jsx`, delete `TaskDetailDrawer`

**Files:**
- Modify: `dashboard/src/App.jsx`
- Delete: `dashboard/src/components/TaskDetailDrawer.jsx`

- [ ] **Update `dashboard/src/App.jsx`**

1. Remove: `import TaskDetailDrawer from "./components/TaskDetailDrawer";`
2. Add: `import TaskGraphModal from "./components/TaskGraphModal";`
3. Replace the `<TaskDetailDrawer ... />` element with:

```jsx
<TaskGraphModal
  task={selectedTask}
  graphData={graphData}
  onClose={() => setSelectedTask(null)}
  onCancelled={handleTaskCancelled}
/>
```

- [ ] **Delete `TaskDetailDrawer.jsx`**

```bash
git rm dashboard/src/components/TaskDetailDrawer.jsx
```

- [ ] **Verify build and tests**

```bash
cd dashboard && npm run build
cd .. && pytest tests/ -v
```
Expected: build succeeds, all tests pass

- [ ] **Commit**

```bash
git add dashboard/src/App.jsx
git commit -m "feat: replace TaskDetailDrawer with TaskGraphModal, wire into App"
```

---

## Manual Testing Checklist

With the full stack running (`bash run-local.sh`):

- [ ] Click a **completed** task → modal opens, completed nodes shown green
- [ ] Click a green node → FORMATTED tab shows structured output
- [ ] Switch to RAW tab → pretty-printed JSON
- [ ] Click an uncompleted node (pending task) → "Node has not run yet"
- [ ] Click ✕ on output panel → panel closes
- [ ] Dispatch a new task → click while running → nodes light up as they complete; currently-running node shown amber
- [ ] Let task fail → failed nodes shown red
- [ ] Cancel a running task → state updates in modal
- [ ] Check **TaskHistory** tab → clicking a task there opens modal (not drawer)
- [ ] Echo agent (2-node) and Lead Analyst (fan-out) both render correctly

---

## Files to Read Before Implementing

- `agents/base/executor.py:150-171` — the `astream` loop insertion point
- `control_plane/routes.py:149-235` — `_run_task` function being replaced
- `control_plane/a2a_client.py:93-130` — existing `stream_message`
- `control_plane/task_store.py:34-84` — `TaskRecord` dataclass + `from_row`
- `dashboard/src/components/graph/layout.js` — `computeLayout` input/output format
- `dashboard/src/hooks/useApi.js:24,70` — `cancelTask` and `subscribeToTask` signatures
