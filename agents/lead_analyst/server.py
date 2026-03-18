"""Standalone A2A server for the Lead Analyst agent.

Run with:
    python -m agents.lead_analyst.server

Sub-agents are defined in ``sub_agents.yaml`` (label + URL pairs).

Environment variables:
    CONTROL_PLANE_URL      – Optional. Control plane URL for self-registration.
    LEAD_ANALYST_AGENT_URL – Optional. This agent's externally-reachable URL.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

import uvicorn
from a2a.server.apps.jsonrpc import A2AFastAPIApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from fastapi import FastAPI

from agents.base.registration import deregister_from_control_plane, register_with_control_plane
from agents.lead_analyst.executor import LeadAnalystExecutor
from dotenv import load_dotenv
load_dotenv()

AGENT_TYPE = "lead-analyst"
AGENT_PORT = 8005

INPUT_FIELDS = [
    {
        "name": "text",
        "label": "Analysis Request",
        "type": "textarea",
        "required": True,
        "placeholder": "Enter the text or request for the lead analyst...",
    },
]

agent_card = AgentCard(
    name="Lead Analyst Agent",
    description=(
        "Orchestrator agent that fans out work to downstream sub-agents "
        "via A2A, collects their results, and returns a synthesized analysis."
    ),
    version="0.1.0",
    url=f"http://localhost:{AGENT_PORT}",
    capabilities=AgentCapabilities(
        streaming=True,
        push_notifications=False,
    ),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[
        AgentSkill(
            id="lead-analysis",
            name="Lead Analysis",
            description="Dispatches work to sub-agents and aggregates their results",
            tags=["orchestration", "analysis", "fan-out"],
        ),
    ],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    agent_url = os.getenv("LEAD_ANALYST_AGENT_URL", os.getenv("AGENT_URL", f"http://localhost:{AGENT_PORT}"))
    await register_with_control_plane(AGENT_TYPE, agent_url)
    yield
    await deregister_from_control_plane(AGENT_TYPE, agent_url)


def create_app() -> FastAPI:
    app = FastAPI(title="Lead Analyst Agent A2A Server", lifespan=lifespan)

    executor = LeadAnalystExecutor()
    task_store = InMemoryTaskStore()
    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
    )

    a2a_app = A2AFastAPIApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )
    a2a_app.add_routes_to_app(app)

    @app.get("/graph")
    async def get_graph():
        topology = executor.get_graph_topology()
        topology["input_fields"] = INPUT_FIELDS

        # Expose downstream connections for cross-agent edge resolution
        downstream_agents = [
            {"from_node": sa.node_id, "agent_url": sa.url}
            for sa in executor.sub_agents
        ]
        if downstream_agents:
            topology["downstream_agents"] = downstream_agents

        return topology

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=AGENT_PORT)
