"""Shared pytest fixtures for Mission Control integration tests.

Uses httpx.AsyncClient with ASGITransport so tests run without a real
server process. A2A agent HTTP calls are intercepted by pytest-httpx.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from httpx import AsyncClient, ASGITransport

from control_plane.pubsub import InMemoryBroker
from control_plane.registry import AgentInstance, AgentRegistry, AgentStatus, AgentType
from control_plane.routes import init_routes, router
from control_plane.task_store import TaskStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_AGENT_ID = "echo-agent"
FAKE_AGENT_URL = "http://echo-agent:8001"


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


def a2a_cancel_response(task_id: str) -> httpx.Response:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"id": task_id, "status": {"state": "canceled"}},
    }
    return httpx.Response(200, json=payload)


async def wait_for_task(client: AsyncClient, agent_id: str, task_id: str, timeout: float = 5.0) -> dict:
    """Poll GET /agents/{agent_id}/tasks/{task_id} until a terminal state is reached."""
    terminal = {"completed", "failed", "canceled"}
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"/agents/{agent_id}/tasks/{task_id}")
        if resp.status_code == 200 and resp.json()["state"] in terminal:
            return resp.json()
        await asyncio.sleep(0.05)
    raise TimeoutError(f"Task {task_id} did not reach a terminal state within {timeout}s")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def task_store() -> TaskStore:
    return TaskStore()


@pytest.fixture()
def broker() -> InMemoryBroker:
    return InMemoryBroker()


@pytest.fixture()
def registry() -> AgentRegistry:
    reg = AgentRegistry.__new__(AgentRegistry)
    reg._types = {}
    reg._poll_interval = 30
    reg._poll_task = None
    reg._client = httpx.AsyncClient()

    instance = AgentInstance(
        url=FAKE_AGENT_URL,
        status=AgentStatus.ONLINE,
        card={
            "name": "Echo Agent",
            "description": "Test echo agent",
            "skills": [{"id": "echo", "name": "Echo"}],
            "capabilities": {"streaming": True},
        },
    )
    agent_type = AgentType(id=FAKE_AGENT_ID, instances=[instance])
    reg._types[FAKE_AGENT_ID] = agent_type
    return reg


@pytest.fixture()
def app(registry, task_store, broker):
    """Return a fully wired FastAPI test app."""
    init_routes(registry, task_store, broker)

    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from control_plane.metrics import instrument_app

    test_app = FastAPI()
    test_app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    test_app.include_router(router)
    instrument_app(test_app)
    return test_app


@pytest.fixture()
async def client(app) -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
