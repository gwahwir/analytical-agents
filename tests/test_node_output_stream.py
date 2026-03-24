# tests/test_node_output_stream.py
from __future__ import annotations
import json
import pytest
from unittest.mock import AsyncMock, patch

from tests.conftest import FAKE_AGENT_ID, wait_for_task


def make_sse_event(state: str, text: str) -> dict:
    return {"result": {"status": {"state": state, "message": {"parts": [{"text": text}]}}}}


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

    async def fake_stream(*args, **kwargs):
        yield make_sse_event("working", "Running node: process")
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
