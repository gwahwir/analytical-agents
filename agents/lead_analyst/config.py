"""YAML-driven sub-agent configuration for the Lead Analyst."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).parent / "sub_agents.yaml"


@dataclass
class SubAgentConfig:
    """A single downstream sub-agent."""

    label: str
    url: str
    node_id: str  # derived: sanitised label for use as LangGraph node name

    @property
    def result_key(self) -> str:
        """State dict key where this sub-agent's result is stored."""
        return f"{self.node_id}_result"


def _to_node_id(label: str) -> str:
    """Convert a label to a valid, unique LangGraph node id.

    ``'ASEAN Security Analyst'`` → ``'call_asean_security_analyst'``
    """
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return f"call_{slug}"


def load_sub_agents(path: Path = DEFAULT_CONFIG_PATH) -> list[SubAgentConfig]:
    """Load sub-agent definitions from a YAML file.

    Raises ``ValueError`` on missing required fields or duplicate node ids.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    raw = data.get("sub_agents", [])
    if not raw:
        print("[lead-analyst] WARNING: no sub_agents defined in", path)
        return []

    configs: list[SubAgentConfig] = []
    seen_ids: dict[str, str] = {}

    for entry in raw:
        label = entry.get("label")
        url = entry.get("url")
        if not label:
            raise ValueError(f"sub_agents.yaml: entry missing required field 'label'")
        if not url:
            raise ValueError(f"sub_agents.yaml: entry '{label}' missing required field 'url'")

        node_id = _to_node_id(label)
        if node_id in seen_ids:
            raise ValueError(
                f"sub_agents.yaml: duplicate node id '{node_id}' "
                f"(from '{label}' and '{seen_ids[node_id]}')"
            )
        seen_ids[node_id] = label

        configs.append(SubAgentConfig(label=label, url=url, node_id=node_id))
        print(f"[lead-analyst] Sub-agent: {node_id} -> {url}")

    return configs
