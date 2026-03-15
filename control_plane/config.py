"""Control Plane configuration.

Agent URLs are read from the ``AGENT_URLS`` environment variable as a
comma-separated list, e.g.:

    AGENT_URLS=http://echo-agent:8001,http://summary-agent:8002

Falls back to ``http://localhost:8001`` (the local echo agent) when the
variable is not set, so local development works without any extra config.
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


def load_settings() -> ControlPlaneSettings:
    raw = os.getenv("AGENT_URLS", "http://localhost:8001")
    agents = []
    for url in raw.split(","):
        url = url.strip()
        if url:
            # Derive a slug name from the URL host, e.g. "echo-agent"
            host = url.rstrip("/").rsplit(":", 1)[0].rsplit("/", 1)[-1]
            agents.append(AgentEndpoint(url=url, name=host))

    return ControlPlaneSettings(agents=agents)
