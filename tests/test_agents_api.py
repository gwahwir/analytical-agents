"""Tests for the /agents endpoints."""

from __future__ import annotations

from tests.conftest import FAKE_AGENT_ID


async def test_list_agents_returns_registered_agent(client):
    resp = await client.get("/agents")
    assert resp.status_code == 200
    agents = resp.json()
    assert len(agents) == 1
    assert agents[0]["id"] == FAKE_AGENT_ID
    assert agents[0]["status"] == "online"


async def test_get_agent_found(client):
    resp = await client.get(f"/agents/{FAKE_AGENT_ID}")
    assert resp.status_code == 200
    assert resp.json()["id"] == FAKE_AGENT_ID


async def test_get_agent_not_found(client):
    resp = await client.get("/agents/nonexistent")
    assert resp.status_code == 404


async def test_agent_has_skills(client):
    resp = await client.get(f"/agents/{FAKE_AGENT_ID}")
    data = resp.json()
    assert len(data["skills"]) == 1
    assert data["skills"][0]["id"] == "echo"


async def test_agent_exposes_instances(client):
    resp = await client.get(f"/agents/{FAKE_AGENT_ID}")
    data = resp.json()
    assert "instances" in data
    assert len(data["instances"]) == 1
    assert data["instances"][0]["status"] == "online"
    assert data["instances"][0]["active_tasks"] == 0
