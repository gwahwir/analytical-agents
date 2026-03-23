# Task Graph Modal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat `TaskDetailDrawer` with a full-screen modal showing the agent's LangGraph execution graph; clicking a node reveals its actual output, updating live during task execution.

**Architecture:** The executor emits a `NODE_OUTPUT::{name}::{json}` SSE event after each node runs; the control plane streams these via `stream_message`, accumulates them in a new `node_outputs` field on `TaskRecord`, and pushes updates over the existing WebSocket. Three new React components render the modal: `TaskGraphModal` (shell + WS subscription), `TaskFlowGraph` (ReactFlow with execution-state overlay), and `NodeOutputPanel` (formatted/raw output tabs).

**Tech Stack:** Python / FastAPI / asyncpg (backend), React / ReactFlow (`@xyflow/react`) / Mantine (frontend), pytest / pytest-httpx / pytest-asyncio (tests)

**Spec:** `docs/superpowers/specs/2026-03-23-task-graph-modal-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `control_plane/task_store.py` | Modify | Add `node_outputs` field to `TaskRecord`; update Postgres `_UPSERT` |
| `control_plane/a2a_client.py` | Modify | Add `baselines`/`key_questions` params + `AsyncGenerator` return type to `stream_message` |
| `agents/base/executor.py` | Modify | Emit `NODE_OUTPUT::` event after each node |
| `control_plane/routes.py` | Modify | Switch `_run_task` to `stream_message`; parse and store node outputs |
| `tests/test_task_store.py` | Create | Unit tests for `node_outputs` field serialization |
| `tests/test_node_output_stream.py` | Create | Unit tests for `_run_task` streaming + NODE_OUTPUT parsing |
| `dashboard/src/components/TaskGraphModal/NodeOutputPanel.jsx` | Create | Formatted/raw output panel for a selected node |
| `dashboard/src/components/TaskGraphModal/TaskFlowGraph.jsx` | Create | ReactFlow graph with execution-state overlay |
| `dashboard/src/components/TaskGraphModal.jsx` | Create | Full-screen modal shell with WS subscription and layout |
| `dashboard/src/components/TaskDetailDrawer.jsx` | Delete | Replaced by TaskGraphModal |
| `dashboard/src/App.jsx` | Modify | Swap TaskDetailDrawer for TaskGraphModal |

---

## Task 1: Add `node_outputs` to `TaskRecord`

**Files:**
- Modify: `control_plane/task_store.py`
- Create: `tests/test_task_store.py`

- [ ] **Write the failing test**

```python
# tests/test_task_store.py
from __future__ import annotations
import pytest
from control_plane.task_store import TaskRecord, TaskState


def test_task_record_node_outputs_default():
    r = TaskRecord(task_id="t1", agent_id="echo-agent")
    assert r.node_outputs == {}


def test_task_record_to_dict_includes_node_outputs():
    r = TaskRecord(task_id="t1", agent_id="echo-agent")
    r.node_outputs["receive"] = '{"input": "hello"}'
    d = r.to_dict()
    assert "node_outputs" in d
    assert d["node_outputs"]["receive"] == '{"input": "hello"}'


def test_task_record_from_row_deserializes_node_outputs():
    row = {
        "task_id": "t1",
        "agent_id": "echo-agent",
        "instance_url": "",
        "state": "completed",
        "input_text": "hi",
        "baselines": "",
        "key_questions": "",
        "output_text": "HI",
        "error": "",
        "created_at": 1000.0,
        "updated_at": 1001.0,
        "a2a_task": "{}",
        "node_outputs": '{"receive": "{\\"input\\": \\"hi\\"}"}',
    }
    r = TaskRecord.from_row(row)
    assert r.node_outputs == {"receive": '{"input": "hi"}'}


def test_task_record_from_row_missing_node_outputs_defaults_empty():
    row = {
        "task_id": "t1",
        "agent_id": "echo-agent",
        "instance_url": "",
        "state": "completed",
        "input_text": "hi",
        "baselines": "",
        "key_questions": "",
        "output_text": "",
        "error": "",
        "created_at": 1000.0,
        "updated_at": 1001.0,
        "a2a_task": "{}",
        # node_outputs intentionally absent
    }
    r = TaskRecord.from_row(row)
    assert r.node_outputs == {}
```

- [ ] **Run test to confirm it fails**

```bash
pytest tests/test_task_store.py -v
```
Expected: 4 failures (field does not exist yet)

- [ ] **Add `node_outputs` to `TaskRecord`**

In `control_plane/task_store.py`:

```python
# In the dataclass fields, after `a2a_task`:
node_outputs: dict[str, str] = field(default_factory=dict)
```

In `to_dict()`, add:
```python
"node_outputs": self.node_outputs,
```

In `from_row()`, add (after the `a2a_task` line):
```python
node_outputs_raw = row.get("node_outputs", "{}")
if isinstance(node_outputs_raw, str):
    node_outputs = json.loads(node_outputs_raw)
else:
    node_outputs = node_outputs_raw or {}
```
And pass `node_outputs=node_outputs` to the `cls(...)` constructor call.

- [ ] **Update Postgres `_ADD_*` migration and `_UPSERT` SQL**

Add a new migration constant after `_ADD_STRUCTURED_INPUT_COLUMNS`:
```python
_ADD_NODE_OUTPUTS_COLUMN = """
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS node_outputs TEXT NOT NULL DEFAULT '{}';
"""
```

Update `_UPSERT` to include `node_outputs` at position `$13`:
```python
_UPSERT = """
INSERT INTO tasks
    (task_id, agent_id, instance_url, state, input_text, baselines, key_questions,
     output_text, error, created_at, updated_at, a2a_task, node_outputs)
VALUES
    ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
ON CONFLICT (task_id) DO UPDATE SET
    state        = EXCLUDED.state,
    output_text  = EXCLUDED.output_text,
    error        = EXCLUDED.error,
    updated_at   = EXCLUDED.updated_at,
    a2a_task     = EXCLUDED.a2a_task,
    node_outputs = EXCLUDED.node_outputs;
"""
```

In `PostgresTaskStore.init()`, add the migration call:
```python
await conn.execute(_ADD_NODE_OUTPUTS_COLUMN)
```

In `PostgresTaskStore.save()`, pass `json.dumps(record.node_outputs)` as the 13th argument.

- [ ] **Run tests to confirm they pass**

```bash
pytest tests/test_task_store.py -v
```
Expected: 4 passed

- [ ] **Commit**

```bash
git add control_plane/task_store.py tests/test_task_store.py
git commit -m "feat: add node_outputs field to TaskRecord"
```

---

## Task 2: Add `baselines`/`key_questions` to `stream_message`

**Files:**
- Modify: `control_plane/a2a_client.py`

> **Note:** This task must be completed before Task 4 (routes.py) since routes.py depends on the updated signature.

- [ ] **Write the failing test** (add to `tests/test_task_store.py` or a new file — create `tests/test_a2a_client.py`)

```python
# tests/test_a2a_client.py
from __future__ import annotations
import json
import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from control_plane.a2a_client import A2AClient


async def test_stream_message_includes_baselines_in_metadata(httpx_mock):
    """stream_message should pass non-empty baselines in message metadata."""
    captured_body = {}

    def capture(request: httpx.Request):
        captured_body.update(json.loads(request.content))
        # Return empty SSE stream
        return httpx.Response(
            200,
            content=b"",
            headers={"content-type": "text/event-stream"},
        )

    httpx_mock.add_callback(capture, url="http://agent:8001/")

    client = A2AClient("http://agent:8001")
    # Consume the generator to trigger the request
    gen = client.stream_message("hello", baselines="some baseline")
    try:
        async for _ in gen:
            pass
    except Exception:
        pass
    finally:
        await gen.aclose()
        await client.close()

    metadata = captured_body.get("params", {}).get("message", {}).get("metadata", {})
    assert metadata.get("baselines") == "some baseline"


async def test_stream_message_omits_empty_baselines(httpx_mock):
    """stream_message should not include baselines key when value is empty string."""
    captured_body = {}

    def capture(request: httpx.Request):
        captured_body.update(json.loads(request.content))
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

    metadata = captured_body.get("params", {}).get("message", {}).get("metadata", {})
    assert "baselines" not in metadata


async def test_stream_message_return_type_supports_aclose():
    """stream_message must return an AsyncGenerator (supports .aclose())."""
    import inspect
    client = A2AClient("http://agent:8001")
    gen = client.stream_message("hello")
    assert hasattr(gen, "aclose"), "stream_message must return an AsyncGenerator"
    await gen.aclose()
    await client.close()
```

- [ ] **Run tests to confirm they fail**

```bash
pytest tests/test_a2a_client.py -v
```
Expected: failures (missing params, no `.aclose()` guarantee)

- [ ] **Update `stream_message` in `control_plane/a2a_client.py`**

Change the return type annotation from `AsyncIterator[dict[str, Any]]` to `AsyncGenerator[dict[str, Any], None]`. Add the import at the top:
```python
from typing import Any, AsyncGenerator, AsyncIterator
```

Add `baselines: str = ""` and `key_questions: str = ""` parameters after `parent_span_id`. Build `metadata` the same way as `send_message` — guard with `if baselines:` and `if key_questions:`:

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
    if parent_span_id or baselines or key_questions:
        message["metadata"] = metadata

    # ... rest of method unchanged (payload, async with, yield)
```

- [ ] **Run tests to confirm they pass**

```bash
pytest tests/test_a2a_client.py -v
```
Expected: 3 passed

- [ ] **Commit**

```bash
git add control_plane/a2a_client.py tests/test_a2a_client.py
git commit -m "feat: add baselines/key_questions to stream_message, update return type to AsyncGenerator"
```

---

## Task 3: Emit `NODE_OUTPUT::` events from executor

**Files:**
- Modify: `agents/base/executor.py`

- [ ] **Make the change in `agents/base/executor.py`**

Add `import json` at the top if not already present (it isn't — add it).

In the `async for event in self.graph.astream(...)` loop, after the existing `result.update(update)` line, add:

```python
await self._emit_status(
    event_queue,
    task_id,
    context_id,
    TaskState.working,
    f"NODE_OUTPUT::{node_name}::{json.dumps(update or {})}",
)
```

The full modified loop body looks like:
```python
node_name = next(iter(event))
await self._emit_status(
    event_queue, task_id, context_id, TaskState.working,
    f"Running node: {node_name}",
)
update = event[node_name]
if update:
    result.update(update)
await self._emit_status(
    event_queue, task_id, context_id, TaskState.working,
    f"NODE_OUTPUT::{node_name}::{json.dumps(update or {})}",
)
```

- [ ] **Verify no existing tests break**

```bash
pytest tests/ -v --ignore=tests/test_task_store.py --ignore=tests/test_a2a_client.py
```
Expected: all previously passing tests still pass (executor is not directly tested by the existing suite)

- [ ] **Commit**

```bash
git add agents/base/executor.py
git commit -m "feat: emit NODE_OUTPUT events from executor after each node"
```

---

## Task 4: Switch `_run_task` to `stream_message` with node output parsing

**Files:**
- Modify: `control_plane/routes.py`
- Create: `tests/test_node_output_stream.py`

- [ ] **Write the failing tests**

```python
# tests/test_node_output_stream.py
"""Tests for _run_task streaming mode and NODE_OUTPUT:: parsing."""
from __future__ import annotations
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from tests.conftest import FAKE_AGENT_ID, FAKE_AGENT_URL, wait_for_task


def make_sse_event(state: str, text: str) -> dict:
    """Build a TaskStatusUpdateEvent dict as stream_message would yield."""
    return {
        "result": {
            "status": {
                "state": state,
                "message": {"parts": [{"text": text}]},
            }
        }
    }


async def _sse_stream(*events):
    """Async generator that yields the given event dicts."""
    for e in events:
        yield e


async def test_node_outputs_populated_after_stream(client, task_store):
    """node_outputs on the task record should contain outputs from NODE_OUTPUT events."""
    node_payload = json.dumps({"output": "HELLO WORLD"})

    async def fake_stream(*args, **kwargs):
        yield make_sse_event("working", "Processing…")
        yield make_sse_event("working", "Running node: process")
        yield make_sse_event("working", f"NODE_OUTPUT::process::{node_payload}")
        yield make_sse_event("completed", "HELLO WORLD")

    with patch("control_plane.routes.A2AClient") as MockClient:
        instance = MockClient.return_value
        instance.stream_message = fake_stream
        instance.close = AsyncMock()

        resp = await client.post(f"/agents/{FAKE_AGENT_ID}/tasks", json={"text": "hello"})
        task_id = resp.json()["task_id"]
        result = await wait_for_task(client, FAKE_AGENT_ID, task_id)

    assert result["state"] == "completed"
    assert "process" in result["node_outputs"]
    assert json.loads(result["node_outputs"]["process"]) == {"output": "HELLO WORLD"}


async def test_node_output_with_double_colon_in_json(client, task_store):
    """NODE_OUTPUT parser must use split('::', 2) so :: inside JSON is preserved."""
    payload_with_colons = json.dumps({"url": "http://example.com::8080/path"})

    async def fake_stream(*args, **kwargs):
        yield make_sse_event("working", f"NODE_OUTPUT::mynode::{payload_with_colons}")
        yield make_sse_event("completed", "done")

    with patch("control_plane.routes.A2AClient") as MockClient:
        instance = MockClient.return_value
        instance.stream_message = fake_stream
        instance.close = AsyncMock()

        resp = await client.post(f"/agents/{FAKE_AGENT_ID}/tasks", json={"text": "hello"})
        task_id = resp.json()["task_id"]
        result = await wait_for_task(client, FAKE_AGENT_ID, task_id)

    stored = json.loads(result["node_outputs"]["mynode"])
    assert stored["url"] == "http://example.com::8080/path"


async def test_stream_ends_without_terminal_event_marks_failed(client, task_store):
    """If the stream closes without a terminal event, task must be marked failed."""
    async def fake_stream(*args, **kwargs):
        yield make_sse_event("working", "Running node: process")
        # stream ends here with no completed/failed/canceled event

    with patch("control_plane.routes.A2AClient") as MockClient:
        instance = MockClient.return_value
        instance.stream_message = fake_stream
        instance.close = AsyncMock()

        resp = await client.post(f"/agents/{FAKE_AGENT_ID}/tasks", json={"text": "hello"})
        task_id = resp.json()["task_id"]
        result = await wait_for_task(client, FAKE_AGENT_ID, task_id)

    assert result["state"] == "failed"
    assert "terminal" in result["error"].lower()


async def test_invalid_json_in_node_output_does_not_crash(client, task_store):
    """Malformed NODE_OUTPUT JSON should be skipped — task still completes."""
    async def fake_stream(*args, **kwargs):
        yield make_sse_event("working", "NODE_OUTPUT::badnode::NOT_VALID_JSON")
        yield make_sse_event("completed", "fine")

    with patch("control_plane.routes.A2AClient") as MockClient:
        instance = MockClient.return_value
        instance.stream_message = fake_stream
        instance.close = AsyncMock()

        resp = await client.post(f"/agents/{FAKE_AGENT_ID}/tasks", json={"text": "hello"})
        task_id = resp.json()["task_id"]
        result = await wait_for_task(client, FAKE_AGENT_ID, task_id)

    assert result["state"] == "completed"
    assert "badnode" not in result["node_outputs"]
```

- [ ] **Run tests to confirm they fail**

```bash
pytest tests/test_node_output_stream.py -v
```
Expected: failures (routes.py still uses `send_message`)

- [ ] **Replace `send_message` with streaming loop in `_run_task` in `control_plane/routes.py`**

Replace the block starting at `result = await client.send_message(...)` through to `record.a2a_task = result` with the streaming loop from the spec. The full replacement:

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
                    await _task_store.save(record)
                    await _broker.publish(task_id, record.to_dict())
                except json.JSONDecodeError:
                    logger.warning("node_output_invalid_json", task_id=task_id, node=node_name)
            continue

        if state_str in ("completed", "failed", "canceled"):
            record.state = TaskState(state_str)
            record.output_text = text_val
            if record.state == TaskState.FAILED:
                record.error = text_val or "Agent returned failed state with no details"
            break
    else:
        record.state = TaskState.FAILED
        record.error = "Stream ended without a terminal status event"
finally:
    await gen.aclose()
```

Remove the old `status`, `state_str`, `output`, `msg`, `parts` variable extraction that followed `send_message`. Keep all existing `except` handlers and the `finally` block (`client.close()`, `instance.active_tasks`). Keep `record.a2a_task = {}` (or remove it — the field is no longer populated from streaming but can stay as an empty dict default).

Also add `import json` to the top of `routes.py` if not already present. (Check: it's not imported currently — add it.)

- [ ] **Run all tests**

```bash
pytest tests/ -v
```
Expected: all tests pass, including the 4 new streaming tests

- [ ] **Commit**

```bash
git add control_plane/routes.py tests/test_node_output_stream.py
git commit -m "feat: switch _run_task to stream_message, capture per-node outputs"
```

---

## Task 5: Create `NodeOutputPanel.jsx`

**Files:**
- Create: `dashboard/src/components/TaskGraphModal/NodeOutputPanel.jsx`

The output panel is a pure display component with no external dependencies beyond Mantine — build it first so it can be tested in isolation.

- [ ] **Create the directory and file**

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
            <Badge key={i} variant="outline" color="hud-cyan" size="sm">
              {v}
            </Badge>
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
  // object
  return (
    <Code block style={{ color: "var(--hud-cyan)", backgroundColor: "var(--hud-bg-surface)", fontSize: 11 }}>
      {JSON.stringify(value, null, 2)}
    </Code>
  );
}

export default function NodeOutputPanel({ nodeId, nodeOutputJson, nodeState, onClose }) {
  const [tab, setTab] = useState("formatted");

  const label = (
    <Group justify="space-between" mb="sm">
      <Text size="xs" fw={600} style={{ color: "var(--hud-cyan)", letterSpacing: "1px", textTransform: "uppercase" }}>
        [ {nodeId} ] OUTPUT
      </Text>
      <Text
        size="xs"
        style={{ color: "var(--hud-text-dimmed)", cursor: "pointer" }}
        onClick={onClose}
      >
        ✕
      </Text>
    </Group>
  );

  // Empty states — checked before rendering tabs
  if (nodeOutputJson === undefined && nodeState === "running") {
    return (
      <div style={{ padding: "12px" }}>
        {label}
        <Text size="sm" style={{ color: "var(--hud-text-dimmed)" }}>
          Node is running
          <span style={{ animation: "blink-cursor 1s step-end infinite" }}>_</span>
        </Text>
      </div>
    );
  }

  if (nodeOutputJson === undefined && nodeState === "pending") {
    return (
      <div style={{ padding: "12px" }}>
        {label}
        <Text size="sm" style={{ color: "var(--hud-text-dimmed)" }}>Node has not run yet</Text>
      </div>
    );
  }

  if (nodeOutputJson === undefined) {
    return (
      <div style={{ padding: "12px" }}>
        {label}
        <Text size="sm" style={{ color: "var(--hud-text-dimmed)" }}>Output not available for this task</Text>
      </div>
    );
  }

  if (nodeOutputJson === "{}") {
    return (
      <div style={{ padding: "12px" }}>
        {label}
        <Text size="sm" style={{ color: "var(--hud-text-dimmed)" }}>Node produced no output</Text>
      </div>
    );
  }

  let parsed;
  let parseError = false;
  try {
    parsed = JSON.parse(nodeOutputJson);
  } catch {
    parseError = true;
  }

  if (parseError) {
    return (
      <div style={{ padding: "12px" }}>
        {label}
        <Badge color="hud-amber" variant="light" mb="xs">Parse error</Badge>
        <Code block style={{ color: "var(--hud-text-primary)", backgroundColor: "var(--hud-bg-surface)", fontSize: 11 }}>
          {nodeOutputJson}
        </Code>
      </div>
    );
  }

  return (
    <div style={{ padding: "12px", height: "100%", overflow: "auto" }}>
      {label}
      <Tabs value={tab} onChange={setTab}>
        <Tabs.List mb="sm">
          <Tabs.Tab value="formatted" style={{ fontSize: 11, letterSpacing: "1px" }}>FORMATTED</Tabs.Tab>
          <Tabs.Tab value="raw" style={{ fontSize: 11, letterSpacing: "1px" }}>RAW</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="formatted">
          <Stack gap="sm">
            {Object.entries(parsed).map(([key, value]) => (
              <div key={key}>
                <Text
                  size="xs"
                  mb={4}
                  style={{
                    color: "var(--hud-text-dimmed)",
                    letterSpacing: "1px",
                    textTransform: "uppercase",
                    fontSize: 11,
                  }}
                >
                  {key}
                </Text>
                {renderValue(value)}
              </div>
            ))}
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="raw">
          <Code
            block
            style={{
              color: "var(--hud-cyan)",
              backgroundColor: "var(--hud-bg-surface)",
              fontSize: 11,
              whiteSpace: "pre-wrap",
            }}
          >
            {JSON.stringify(parsed, null, 2)}
          </Code>
        </Tabs.Panel>
      </Tabs>
    </div>
  );
}
```

- [ ] **Verify the dashboard still builds**

```bash
cd dashboard && npm run build
```
Expected: build succeeds (new file not yet imported anywhere)

- [ ] **Commit**

```bash
git add dashboard/src/components/TaskGraphModal/NodeOutputPanel.jsx
git commit -m "feat: add NodeOutputPanel component with formatted/raw tabs"
```

---

## Task 6: Create `TaskFlowGraph.jsx`

**Files:**
- Create: `dashboard/src/components/TaskGraphModal/TaskFlowGraph.jsx`

- [ ] **Create the file**

```jsx
// dashboard/src/components/TaskGraphModal/TaskFlowGraph.jsx
import { useMemo } from "react";
import { ReactFlow, Background, Controls } from "@xyflow/react";
import { Text } from "@mantine/core";
import { computeLayout } from "../graph/layout";

// Execution state → visual style
const STATE_STYLES = {
  pending: {
    background: "#0d1117",
    border: "1px solid #374151",
    color: "#6b7280",
    opacity: 0.5,
    boxShadow: "none",
  },
  running: {
    background: "#1a1200",
    border: "1px solid #f59e0b",
    color: "#fbbf24",
    opacity: 1,
    boxShadow: "0 0 12px rgba(245,158,11,0.5)",
  },
  completed: {
    background: "#0a1a0a",
    border: "1px solid #22c55e",
    color: "#4ade80",
    opacity: 1,
    boxShadow: "none",
  },
  failed: {
    background: "#1a0505",
    border: "1px solid #ef4444",
    color: "#f87171",
    opacity: 1,
    boxShadow: "none",
  },
  selected: {
    background: "#001a2a",
    border: "2px solid #00d4ff",
    color: "#00d4ff",
    opacity: 1,
    boxShadow: "0 0 14px rgba(0,212,255,0.3)",
  },
};

const DOT_COLORS = {
  running: "#f59e0b",
  completed: "#22c55e",
  failed: "#ef4444",
  selected: "#00d4ff",
};

function ExecutionNode({ data }) {
  const style = STATE_STYLES[data.executionState] || STATE_STYLES.pending;
  const dotColor = DOT_COLORS[data.executionState];

  return (
    <div
      style={{
        ...style,
        borderRadius: 0,
        minWidth: 140,
        padding: "6px 12px",
        fontFamily: "monospace",
        fontSize: 11,
        letterSpacing: "0.5px",
        textTransform: "uppercase",
        display: "flex",
        alignItems: "center",
        gap: 6,
        cursor: "pointer",
      }}
    >
      {dotColor && (
        <span
          style={{
            display: "inline-block",
            width: 6,
            height: 6,
            borderRadius: "50%",
            backgroundColor: dotColor,
            flexShrink: 0,
          }}
        />
      )}
      {data.label}
    </div>
  );
}

const nodeTypes = { executionNode: ExecutionNode };

function getNodeExecutionState({ bareId, selectedNodeId, runningNode, nodeOutputs, taskFailed }) {
  if (bareId === selectedNodeId) return "selected";
  if (bareId === runningNode) return "running";
  if (nodeOutputs && bareId in nodeOutputs) return "completed";
  if (taskFailed && bareId === runningNode) return "failed";
  return "pending";
}

export default function TaskFlowGraph({ agentData, taskState, selectedNodeId, runningNode, onNodeSelect }) {
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
  const taskFailed = taskState?.state === "failed";

  const { nodes: rawNodes, edges } = useMemo(
    () => computeLayout({ agents: [agentData], cross_agent_edges: [] }),
    [agentData]
  );

  // Patch nodes: swap type to executionNode and inject executionState
  const nodes = useMemo(() => {
    return rawNodes.map((node) => {
      if (node.type !== "graphNode") return node; // leave agentGroup nodes alone
      const bareId = node.id.split(":").slice(1).join(":");
      const executionState = getNodeExecutionState({
        bareId,
        selectedNodeId,
        runningNode,
        nodeOutputs,
        taskFailed,
      });
      return {
        ...node,
        type: "executionNode",
        data: { ...node.data, executionState },
      };
    });
  }, [rawNodes, selectedNodeId, runningNode, nodeOutputs, taskFailed]);

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
        const bareId = node.id.split(":").slice(1).join(":");
        onNodeSelect(bareId);
      }}
      proOptions={{ hideAttribution: true }}
    >
      <Background color="rgba(0, 212, 255, 0.06)" gap={20} />
      <Controls
        showInteractive={false}
        style={{
          background: "var(--hud-bg-panel)",
          border: "1px solid var(--hud-border)",
          borderRadius: 0,
        }}
      />
    </ReactFlow>
  );
}
```

- [ ] **Verify the dashboard still builds**

```bash
cd dashboard && npm run build
```
Expected: build succeeds

- [ ] **Commit**

```bash
git add dashboard/src/components/TaskGraphModal/TaskFlowGraph.jsx
git commit -m "feat: add TaskFlowGraph component with execution state overlay"
```

---

## Task 7: Create `TaskGraphModal.jsx`

**Files:**
- Create: `dashboard/src/components/TaskGraphModal.jsx`

- [ ] **Create the file**

```jsx
// dashboard/src/components/TaskGraphModal.jsx
import { useState, useEffect } from "react";
import { Modal, Stack, Text, Badge, Code, Button, Group, Box } from "@mantine/core";
import { cancelTask, subscribeToTask } from "../hooks/useApi";
import TaskFlowGraph from "./TaskGraphModal/TaskFlowGraph";
import NodeOutputPanel from "./TaskGraphModal/NodeOutputPanel";

const STATE_COLORS = {
  completed: "hud-green",
  working: "hud-amber",
  submitted: "gray",
  canceled: "hud-red",
  failed: "hud-red",
  "input-required": "hud-violet",
};

const LIVE_STATES = new Set(["submitted", "working"]);

function extractStatusText(wsMessage) {
  // Extract the latest status message text from a WS task dict.
  // The WS payload is record.to_dict() — it doesn't carry the streaming
  // status text directly. The runningNode is inferred from the last
  // non-NODE_OUTPUT status. We track this separately via the broker
  // publishing record.to_dict() after each node. Since the backend saves
  // after each NODE_OUTPUT and publishes the record, we infer runningNode
  // from the most recent node key added to node_outputs.
  return null; // handled by node_outputs diff below
}

export default function TaskGraphModal({ task, graphData, onClose, onCancelled }) {
  const [taskState, setTaskState] = useState(task);
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [runningNode, setRunningNode] = useState(null);
  const [cancelling, setCancelling] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);

  // Reset state when task changes
  useEffect(() => {
    setTaskState(task);
    setSelectedNodeId(null);
    setRunningNode(null);
    setCancelling(false);
    setConfirmCancel(false);
  }, [task?.task_id]);

  // WS subscription for live tasks
  useEffect(() => {
    if (!task || !LIVE_STATES.has(task.state)) return;

    const unsub = subscribeToTask(task.task_id, (msg) => {
      setTaskState(msg);
      // Infer runningNode: the most recently added key in node_outputs
      // that isn't yet present in our previous state. Alternatively, the
      // backend publishes after each NODE_OUTPUT so node_outputs grows by one
      // key per message. We diff to find the newest key.
      if (msg.node_outputs) {
        const keys = Object.keys(msg.node_outputs);
        if (keys.length > 0) {
          // The last key added is the most recently completed node.
          // After completion it's "completed", not "running" — clear runningNode
          // when we get the completed key. The running node is the one the
          // executor emits "Running node:" for just before NODE_OUTPUT.
          // Since we don't have the raw status text here, we track runningNode
          // as cleared whenever a new key appears (it just completed).
          setRunningNode(null);
        }
      }
      if (!LIVE_STATES.has(msg.state)) {
        setRunningNode(null);
      }
    });

    return unsub;
  }, [task?.task_id, task?.state]);

  // Note: runningNode tracking via the "Running node: X" message text is not
  // available from record.to_dict() WS payloads (those only carry state fields).
  // The broker publishes record.to_dict() which includes node_outputs but not
  // the raw status text. As a result, a node shows "running" only briefly —
  // between when the executor emits "Running node: X" and when it emits
  // NODE_OUTPUT::X (which triggers the broker publish).
  // The visual effect: nodes transition pending → completed without a running
  // flash via WS. This is acceptable. The running state IS visible if the
  // control plane is extended to publish on every status event (future work).

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

  const nodeOutputs = taskState?.node_outputs;
  const nodeOutputJson = selectedNodeId
    ? (nodeOutputs === undefined ? undefined : nodeOutputs?.[selectedNodeId])
    : undefined;

  const nodeState = (() => {
    if (!selectedNodeId) return "pending";
    if (taskState?.state === "failed" && selectedNodeId === runningNode) return "failed";
    if (nodeOutputs?.[selectedNodeId] !== undefined) return "completed";
    if (selectedNodeId === runningNode) return "running";
    return "pending";
  })();

  return (
    <Modal
      opened={!!task}
      onClose={onClose}
      fullScreen
      withCloseButton={true}
      title={
        <Text fw={600} style={{ textTransform: "uppercase", letterSpacing: "2px", fontSize: 14 }}>
          [ TASK GRAPH ]
        </Text>
      }
      styles={{
        body: { padding: 0, height: "calc(100vh - 60px)", display: "flex" },
        content: { display: "flex", flexDirection: "column" },
      }}
    >
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {/* Left: graph (65%) */}
        <div style={{ flex: "0 0 65%", borderRight: "1px solid var(--hud-border)" }}>
          <TaskFlowGraph
            agentData={agentData}
            taskState={taskState}
            selectedNodeId={selectedNodeId}
            runningNode={runningNode}
            onNodeSelect={setSelectedNodeId}
          />
        </div>

        {/* Right: metadata + output panel (35%) */}
        <div style={{ flex: "0 0 35%", display: "flex", flexDirection: "column", overflow: "hidden" }}>
          {/* Task metadata */}
          <Stack
            gap="xs"
            p="md"
            style={{ borderBottom: "1px solid var(--hud-border)", flexShrink: 0 }}
          >
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
              <Badge color={STATE_COLORS[taskState?.state] || "gray"} variant="light">
                {taskState?.state}
              </Badge>
            </div>
            <div>
              <Text size="xs" style={{ color: "var(--hud-text-dimmed)", letterSpacing: "1px" }} tt="uppercase">Created</Text>
              <Text size="sm">
                {taskState?.created_at ? new Date(taskState.created_at * 1000).toLocaleString() : "—"}
              </Text>
            </div>
            {canCancel && (
              <Button
                color="hud-red"
                variant={confirmCancel ? "filled" : "outline"}
                size="xs"
                onClick={handleCancel}
                loading={cancelling}
                style={
                  confirmCancel
                    ? { boxShadow: "0 0 12px rgba(255, 61, 61, 0.3)" }
                    : { borderColor: "var(--hud-red)", color: "var(--hud-red)" }
                }
              >
                {confirmCancel ? "CLICK AGAIN TO CONFIRM" : "CANCEL TASK"}
              </Button>
            )}
          </Stack>

          {/* Node output panel */}
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

- [ ] **Verify the dashboard builds**

```bash
cd dashboard && npm run build
```
Expected: build succeeds

- [ ] **Commit**

```bash
git add dashboard/src/components/TaskGraphModal.jsx
git commit -m "feat: add TaskGraphModal full-screen modal with WS subscription"
```

---

## Task 8: Wire `TaskGraphModal` into `App.jsx`, delete `TaskDetailDrawer`

**Files:**
- Modify: `dashboard/src/App.jsx`
- Delete: `dashboard/src/components/TaskDetailDrawer.jsx`

- [ ] **Remove `TaskDetailDrawer` from `App.jsx` and add `TaskGraphModal`**

In `dashboard/src/App.jsx`:

1. Remove the import line:
   ```js
   import TaskDetailDrawer from "./components/TaskDetailDrawer";
   ```

2. Add the import:
   ```js
   import TaskGraphModal from "./components/TaskGraphModal";
   ```

3. Replace the `<TaskDetailDrawer .../>` JSX:
   ```jsx
   // Remove:
   <TaskDetailDrawer
     task={selectedTask}
     onClose={() => setSelectedTask(null)}
     onCancelled={handleTaskCancelled}
   />

   // Add:
   <TaskGraphModal
     task={selectedTask}
     graphData={graphData}
     onClose={() => setSelectedTask(null)}
     onCancelled={handleTaskCancelled}
   />
   ```

- [ ] **Delete `TaskDetailDrawer.jsx`**

```bash
rm dashboard/src/components/TaskDetailDrawer.jsx
```

- [ ] **Verify the dashboard builds cleanly**

```bash
cd dashboard && npm run build
```
Expected: build succeeds with no import errors

- [ ] **Run all backend tests one final time**

```bash
pytest tests/ -v
```
Expected: all tests pass

- [ ] **Commit**

```bash
git add dashboard/src/App.jsx
git rm dashboard/src/components/TaskDetailDrawer.jsx
git commit -m "feat: replace TaskDetailDrawer with TaskGraphModal in App"
```

---

## Manual Testing Checklist

Once the full stack is running (`bash run-local.sh` or `docker compose up`):

- [ ] Click a **completed** task → modal opens, graph shows, all visited nodes are green
- [ ] Click a green node → output panel shows FORMATTED tab with node data
- [ ] Switch to RAW tab → pretty-printed JSON displayed
- [ ] Click a node with `{}` output → "Node produced no output" shown
- [ ] Click ✕ on output panel → panel closes, no node selected
- [ ] Click ✕ (or outside) on modal → modal closes
- [ ] Dispatch a **new task** → click it while running → modal opens, nodes light up as they complete
- [ ] Click a **pending node** → "Node has not run yet"
- [ ] Cancel a running task → state updates to canceled in modal
- [ ] Check **TaskHistory** — clicking tasks there also opens the modal (not a drawer)
- [ ] Echo agent (2-node graph) and Lead Analyst (fan-out graph) both render correctly

---

## Read Before Implementing

- `agents/base/executor.py` — understand the `astream` loop before editing
- `control_plane/routes.py:149-235` — the `_run_task` function being replaced
- `control_plane/a2a_client.py:93-130` — existing `stream_message` signature
- `dashboard/src/components/graph/layout.js` — `computeLayout` input/output format
- `dashboard/src/hooks/useApi.js:70-76` — `subscribeToTask` signature
