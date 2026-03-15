"""Control Plane configuration.

All settings are read from environment variables:

    AGENT_URLS    Comma-separated list of agent base URLs.
                  Defaults to http://localhost:8001 for local development.

    DATABASE_URL  asyncpg-compatible PostgreSQL DSN, e.g.:
                  postgresql://user:password@host:5432/dbname
                  When not set the control plane uses an in-memory store.

    LOG_LEVEL     Logging verbosity (DEBUG / INFO / WARNING / ERROR).
                  Defaults to INFO.
"""

from __future__ import annotations

import os

from pydantic import BaseModel


class AgentEndpoint(BaseModel):
    url: str
    name: str | None = None


class ControlPlaneSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    agents: list[AgentEndpoint] = []
    health_poll_interval_seconds: int = 30
    database_url: str | None = None


def load_settings() -> ControlPlaneSettings:
    # Agent URLs
    raw = os.getenv("AGENT_URLS", "http://localhost:8001")
    agents = []
    for url in raw.split(","):
        url = url.strip()
        if url:
            host = url.rstrip("/").rsplit(":", 1)[0].rsplit("/", 1)[-1]
            agents.append(AgentEndpoint(url=url, name=host))

    return ControlPlaneSettings(
        agents=agents,
        database_url=os.getenv("DATABASE_URL"),
    )
