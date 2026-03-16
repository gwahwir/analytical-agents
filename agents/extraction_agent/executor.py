"""Executor that bridges A2A requests to the Relevancy LangGraph."""

from __future__ import annotations

from langgraph.graph.state import CompiledStateGraph

from agents.base.executor import LangGraphA2AExecutor
from agents.relevancy.graph import build_relevancy_graph


class ExtractionExecutor(LangGraphA2AExecutor):
    """Runs the relevancy graph: parse input → LLM check → JSON output."""

    def build_graph(self) -> CompiledStateGraph:
        return build_relevancy_graph()
