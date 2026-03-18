"""A2A executor for the Lead Analyst agent."""

from __future__ import annotations

from langgraph.graph.state import CompiledStateGraph

from agents.base import LangGraphA2AExecutor
from agents.lead_analyst.config import SubAgentConfig, load_sub_agents
from agents.lead_analyst.graph import build_lead_analyst_graph


class LeadAnalystExecutor(LangGraphA2AExecutor):
    """Wraps the lead analyst LangGraph in an A2A-compatible executor."""

    def __init__(self, sub_agents: list[SubAgentConfig] | None = None) -> None:
        super().__init__()
        self._sub_agents = sub_agents if sub_agents is not None else load_sub_agents()

    @property
    def sub_agents(self) -> list[SubAgentConfig]:
        return self._sub_agents

    def build_graph(self) -> CompiledStateGraph:
        return build_lead_analyst_graph(self._sub_agents)
