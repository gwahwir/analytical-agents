"""Executor that bridges A2A requests to the Knowledge Graph LangGraph."""

from __future__ import annotations

from langgraph.graph.state import CompiledStateGraph

from agents.base.executor import LangGraphA2AExecutor
from agents.knowledge_graph.graph import build_knowledge_graph_graph


class KnowledgeGraphExecutor(LangGraphA2AExecutor):
    """Runs the knowledge graph pipeline: extract → store → narrative."""

    def build_graph(self) -> CompiledStateGraph:
        return build_knowledge_graph_graph()

    def format_output(self, result: dict) -> str:
        """Return the pre-serialised dual-format JSON artifact."""
        return result.get("output", "{}")
