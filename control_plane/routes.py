"""REST API routes for the Control Plane."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from control_plane.a2a_client import A2AClient, A2AError
from control_plane.log import get_logger
from control_plane.metrics import (
    task_duration,
    tasks_cancelled,
    tasks_completed,
    tasks_dispatched,
    tasks_failed,
)
from control_plane.registry import AgentRegistry, AgentStatus
from control_plane.task_store import PostgresTaskStore, TaskRecord, TaskState, TaskStore

logger = get_logger(__name__)

router = APIRouter()

# Injected by the app factory
_registry: AgentRegistry | None = None
_task_store: TaskStore | PostgresTaskStore | None = None
_ws_subscribers: dict[str, list[WebSocket]] = {}


def init_routes(registry: AgentRegistry, task_store: TaskStore | PostgresTaskStore) -> None:
    global _registry, _task_store
    _registry = registry
    _task_store = task_store


# ------------------------------------------------------------------
# Request / Response models
# ------------------------------------------------------------------

class TaskRequest(BaseModel):
    text: str


class TaskResponse(BaseModel):
    task_id: str
    agent_id: str
    state: str
    input_text: str
    output_text: str


# ------------------------------------------------------------------
# Agent endpoints
# ------------------------------------------------------------------

@router.get("/agents")
async def list_agents() -> list[dict[str, Any]]:
    assert _registry is not None
    return [a.to_dict() for a in _registry.agents.values()]


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str) -> dict[str, Any]:
    assert _registry is not None
    agent = _registry.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    return agent.to_dict()


# ------------------------------------------------------------------
# Task endpoints
# ------------------------------------------------------------------

@router.post("/agents/{agent_id}/tasks", response_model=TaskResponse)
async def dispatch_task(agent_id: str, req: TaskRequest) -> TaskResponse:
    assert _registry is not None and _task_store is not None

    agent = _registry.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    if agent.status != AgentStatus.ONLINE:
        raise HTTPException(503, f"Agent '{agent_id}' is offline")

    logger.info("task_dispatch", agent_id=agent_id, text=req.text[:80])
    tasks_dispatched.labels(agent_id=agent_id).inc()
    started_at = time.time()

    client = A2AClient(agent.url)
    try:
        result = await client.send_message(req.text)
    except A2AError as e:
        tasks_failed.labels(agent_id=agent_id).inc()
        logger.error("task_dispatch_a2a_error", agent_id=agent_id, error=str(e))
        raise HTTPException(502, str(e))
    except Exception as e:
        tasks_failed.labels(agent_id=agent_id).inc()
        logger.error("task_dispatch_error", agent_id=agent_id, error=str(e))
        raise HTTPException(502, f"Failed to reach agent: {e}")
    finally:
        await client.close()

    task_id = result.get("id", "")
    status = result.get("status", {})
    state_str = status.get("state", "failed")
    output = ""
    msg = status.get("message", {})
    if msg:
        parts = msg.get("parts", [])
        if parts:
            output = parts[0].get("text", "")

    elapsed = time.time() - started_at
    task_duration.labels(agent_id=agent_id).observe(elapsed)

    if state_str == "completed":
        tasks_completed.labels(agent_id=agent_id).inc()
    elif state_str == "failed":
        tasks_failed.labels(agent_id=agent_id).inc()

    logger.info(
        "task_complete",
        agent_id=agent_id,
        task_id=task_id,
        state=state_str,
        duration_s=round(elapsed, 3),
    )

    record = TaskRecord(
        task_id=task_id,
        agent_id=agent_id,
        state=TaskState(state_str),
        input_text=req.text,
        output_text=output,
        a2a_task=result,
    )
    await _task_store.save(record)
    await _notify_ws(task_id, record.to_dict())

    return TaskResponse(
        task_id=task_id,
        agent_id=agent_id,
        state=state_str,
        input_text=req.text,
        output_text=output,
    )


@router.get("/agents/{agent_id}/tasks/{task_id}")
async def get_task(agent_id: str, task_id: str) -> dict[str, Any]:
    assert _task_store is not None
    record = await _task_store.get(task_id)
    if not record or record.agent_id != agent_id:
        raise HTTPException(404, "Task not found")
    return record.to_dict()


@router.delete("/agents/{agent_id}/tasks/{task_id}")
async def cancel_task_endpoint(agent_id: str, task_id: str) -> dict[str, Any]:
    assert _registry is not None and _task_store is not None

    agent = _registry.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")

    record = await _task_store.get(task_id)
    if not record or record.agent_id != agent_id:
        raise HTTPException(404, "Task not found")

    logger.info("task_cancel", agent_id=agent_id, task_id=task_id)

    client = A2AClient(agent.url)
    try:
        await client.cancel_task(task_id)
    except A2AError as e:
        logger.warning("task_cancel_a2a_error", task_id=task_id, error=str(e))
        raise HTTPException(502, str(e))
    finally:
        await client.close()

    record.state = TaskState.CANCELED
    await _task_store.save(record)
    tasks_cancelled.labels(agent_id=agent_id).inc()
    await _notify_ws(task_id, record.to_dict())

    logger.info("task_cancelled", agent_id=agent_id, task_id=task_id)
    return {"status": "cancelled", "task_id": task_id}


@router.get("/tasks")
async def list_all_tasks() -> list[dict[str, Any]]:
    assert _task_store is not None
    return [t.to_dict() for t in await _task_store.list_all()]


# ------------------------------------------------------------------
# WebSocket — live task updates
# ------------------------------------------------------------------

@router.websocket("/ws/tasks/{task_id}")
async def ws_task_updates(websocket: WebSocket, task_id: str) -> None:
    await websocket.accept()

    if task_id not in _ws_subscribers:
        _ws_subscribers[task_id] = []
    _ws_subscribers[task_id].append(websocket)

    logger.debug("ws_connected", task_id=task_id)

    try:
        assert _task_store is not None
        record = await _task_store.get(task_id)
        if record:
            await websocket.send_json(record.to_dict())

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        subs = _ws_subscribers.get(task_id, [])
        if websocket in subs:
            subs.remove(websocket)
        logger.debug("ws_disconnected", task_id=task_id)


async def _notify_ws(task_id: str, data: dict[str, Any]) -> None:
    subscribers = _ws_subscribers.get(task_id, [])
    closed: list[WebSocket] = []
    for ws in subscribers:
        try:
            await ws.send_json(data)
        except Exception:
            closed.append(ws)
    for ws in closed:
        subscribers.remove(ws)
