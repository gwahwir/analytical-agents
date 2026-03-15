"""Control Plane FastAPI application.

Run with:
    python -m control_plane.server
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from control_plane.config import load_settings
from control_plane.log import CorrelationIdMiddleware, configure_logging, get_logger
from control_plane.metrics import instrument_app
from control_plane.registry import AgentRegistry
from control_plane.routes import init_routes, router
from control_plane.task_store import TaskStore

configure_logging(log_level=os.getenv("LOG_LEVEL", "INFO"))
logger = get_logger(__name__)

settings = load_settings()
registry = AgentRegistry(poll_interval=settings.health_poll_interval_seconds)
task_store = TaskStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", agent_count=len(settings.agents))
    await registry.register_all(settings.agents)
    registry.start_polling()

    online = sum(1 for a in registry.agents.values() if a.status.value == "online")
    logger.info("registry_ready", online=online, total=len(registry.agents))

    yield

    await registry.close()
    logger.info("shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Mission Control — Control Plane",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    init_routes(registry, task_store)
    app.include_router(router)
    instrument_app(app)

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host=settings.host, port=settings.port)
