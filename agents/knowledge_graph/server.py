"""Standalone A2A server for the Knowledge Graph agent.

Run with:
    python -m agents.knowledge_graph.server

Environment variables:
    MEM0_NEO4J_URL        – Required. Neo4j bolt URL (e.g. bolt://localhost:7687).
    MEM0_NEO4J_USER       – Required. Neo4j username.
    MEM0_NEO4J_PASSWORD   – Required. Neo4j password.
    MEM0_PG_DSN           – Required. pgvector-enabled PostgreSQL DSN.
    OPENAI_API_KEY        – Required. OpenAI API key.
    OPENAI_BASE_URL       – Optional. Custom OpenAI-compatible base URL.
    OPENAI_MODEL          – Model to use (default: gpt-4o-mini).
    CONTROL_PLANE_URL     – Optional. Control plane URL for self-registration.
    KNOWLEDGE_GRAPH_AGENT_URL – Optional. This agent's externally-reachable URL.
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
from agents.knowledge_graph.executor import KnowledgeGraphExecutor
from dotenv import load_dotenv

load_dotenv()

AGENT_TYPE = "knowledge-graph"
AGENT_PORT = 8008

INPUT_FIELDS = [
    {
        "name": "text",
        "label": "Article / Snippet",
        "type": "textarea",
        "required": True,
        "placeholder": "Paste the article or text snippet to ingest into the knowledge graph...",
    }
]

agent_card = AgentCard(
    name="Knowledge Graph Agent",
    description=(
        "Ingests articles and text snippets, extracts entities (persons, organisations, "
        "locations, products) and issues (topics of world interest), and builds a persistent "
        "knowledge graph backed by Neo4j and pgvector via mem0."
    ),
    version="0.1.0",
    url=f"http://localhost:{AGENT_PORT}",
    capabilities=AgentCapabilities(
        streaming=True,
        push_notifications=False,
    ),
    default_input_modes=["application/json"],
    default_output_modes=["application/json"],
    skills=[
        AgentSkill(
            id="ingest",
            name="Ingest",
            description="Ingests a text article or snippet into the knowledge graph",
            tags=["knowledge-graph", "mem0", "neo4j", "entities", "issues"],
        ),
    ],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    agent_url = os.getenv(
        "KNOWLEDGE_GRAPH_AGENT_URL",
        os.getenv("AGENT_URL", f"http://localhost:{AGENT_PORT}"),
    )
    await register_with_control_plane(AGENT_TYPE, agent_url)
    yield
    await deregister_from_control_plane(AGENT_TYPE, agent_url)


def create_app() -> FastAPI:
    app = FastAPI(title="Knowledge Graph Agent A2A Server", lifespan=lifespan)
    agent_url = os.getenv(
        "KNOWLEDGE_GRAPH_AGENT_URL",
        os.getenv("AGENT_URL", f"http://localhost:{AGENT_PORT}"),
    )
    print(f"My Address is {agent_url}")

    executor = KnowledgeGraphExecutor()
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
        return topology

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=AGENT_PORT)
