"""Tests for meta-analysis flow in the Lead Analyst graph.

Verifies that both static and dynamic modes properly synchronize at the aggregate
node before running the meta-analysis pipeline (peripheral → ach → synthesis).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_runnableconfig():
    """Create a mock RunnableConfig for graph execution."""
    executor = MagicMock()
    executor.check_cancelled = MagicMock()
    return {"configurable": {"executor": executor, "task_id": "t1", "context_id": "c1"}}


# ---------------------------------------------------------------------------
# Test synchronization barriers
# ---------------------------------------------------------------------------

class TestAggregationSynchronization:
    """Test that both modes properly synchronize at the aggregate node."""

    async def test_static_mode_aggregates_before_peripheral_scan(self):
        """Static mode: sub-agents → aggregate → peripheral scan."""
        from agents.lead_analyst.config import SubAgentConfig
        from agents.lead_analyst.graph import build_lead_analyst_graph

        sub_agents = [
            SubAgentConfig(label="Agent A", url="http://a:8001", node_id="agent_a"),
            SubAgentConfig(label="Agent B", url="http://b:8002", node_id="agent_b"),
        ]
        graph = build_lead_analyst_graph(sub_agents=sub_agents, dynamic_discovery=False)
        config = _make_runnableconfig()

        # Mock sub-agent calls
        with patch("agents.lead_analyst.graph._call_sub_agent",
                   new=AsyncMock(return_value='{"summary": "analysis"}')):
            result = await graph.ainvoke({
                "input": "Test question",
                "key_questions": "What are the key findings?"
            }, config=config)

        # Verify: aggregate was called with results from both sub-agents
        assert len(result["results"]) == 2
        # Verify: aggregated_consensus was populated before peripheral scan
        assert "aggregated_consensus" in result
        assert result["aggregated_consensus"]  # Not empty

    async def test_dynamic_mode_check_all_specialists_routes_to_peripheral_scan(self):
        """Dynamic mode router: check_all_specialists_done routes to peripheral_scan when complete."""
        from agents.lead_analyst.graph import check_all_specialists_done

        # Simulate dynamic mode state after all specialists complete
        state = {
            "selected_specialists": [
                {"label": "Specialist A", "url": "http://a:8006/a"},
                {"label": "Specialist B", "url": "http://b:8006/b"},
            ],
            "results": [
                ("Specialist A", '{"summary": "analysis A"}'),
                ("Specialist B", '{"summary": "analysis B"}'),
            ],
        }

        # Should route to peripheral_scan when all specialists are done (NEW FLOW)
        next_node = check_all_specialists_done(state)
        assert next_node == "call_peripheral_scan", "Dynamic mode should route to peripheral_scan after all specialists complete"

    async def test_empty_sub_agents_aggregates_empty_results(self):
        """Static mode with no sub-agents: receive → aggregate → meta-analysis."""
        from agents.lead_analyst.graph import build_lead_analyst_graph

        graph = build_lead_analyst_graph(sub_agents=[], dynamic_discovery=False)
        config = _make_runnableconfig()

        with patch("agents.lead_analyst.graph._call_sub_agent",
                   new=AsyncMock(return_value="peripheral scan output")):
            result = await graph.ainvoke({
                "input": "Test question",
                "key_questions": "What are the key findings?"
            }, config=config)

        # Should handle empty results gracefully
        assert result["aggregated_consensus"] == "No sub-agent results available."
        # Output will still go through meta-analysis pipeline (peripheral, ACH, synthesis)
        # so it won't be exactly the same as aggregated_consensus
        assert "output" in result
        assert result["output"]  # Final output exists (may include meta-analysis)


# ---------------------------------------------------------------------------
# Test meta-analysis pipeline flow
# ---------------------------------------------------------------------------

class TestMetaAnalysisPipeline:
    """Test the sequential meta-analysis flow: peripheral → ach → synthesis."""

    async def test_meta_analysis_runs_by_default(self):
        """Verify meta-analysis pipeline runs by default."""
        from agents.lead_analyst.config import SubAgentConfig
        from agents.lead_analyst.graph import build_lead_analyst_graph

        sub_agents = [
            SubAgentConfig(label="Agent A", url="http://a:8001", node_id="agent_a"),
        ]
        graph = build_lead_analyst_graph(sub_agents=sub_agents)
        config = _make_runnableconfig()

        call_count = {"peripheral": 0, "ach": 0}

        async def mock_call_sub_agent(url, text, context_id=None, parent_span_id=None):
            # Peripheral scan prompt includes "DOMAIN SPECIALIST ANALYSES"
            if "DOMAIN SPECIALIST ANALYSES" in text:
                call_count["peripheral"] += 1
                return "Peripheral findings: weak signal detected"
            # ACH prompt includes "AGGREGATED CONSENSUS TO CHALLENGE"
            elif "AGGREGATED CONSENSUS TO CHALLENGE" in text:
                call_count["ach"] += 1
                return "Alternative hypothesis: H2 considers..."
            return '{"summary": "domain analysis"}'

        with patch("agents.lead_analyst.graph._call_sub_agent", new=AsyncMock(side_effect=mock_call_sub_agent)):
            result = await graph.ainvoke({
                "input": "Test question",
                "key_questions": "What are the findings?"
            }, config=config)

        # Verify meta-analysis stages were called
        assert call_count["peripheral"] > 0, "Peripheral scan was not called"
        assert call_count["ach"] > 0, "ACH red team was not called"
        # Note: synthesis uses OpenAI LLM, not _call_sub_agent, so we check state instead
        assert "output" in result
        assert result["output"]  # Final output was produced

    async def test_peripheral_scan_receives_aggregated_consensus(self):
        """Peripheral scan should receive aggregated results, not raw sub-agent output."""
        from agents.lead_analyst.config import SubAgentConfig
        from agents.lead_analyst.graph import build_lead_analyst_graph

        sub_agents = [
            SubAgentConfig(label="Agent A", url="http://a:8001", node_id="agent_a"),
        ]
        graph = build_lead_analyst_graph(sub_agents=sub_agents)
        config = _make_runnableconfig()

        peripheral_input_captured = None

        async def mock_call_sub_agent(url, text, context_id=None, parent_span_id=None):
            nonlocal peripheral_input_captured
            if "DOMAIN SPECIALIST ANALYSES" in text:
                peripheral_input_captured = text
                return "Peripheral findings"
            return '{"summary": "domain analysis"}'

        with patch("agents.lead_analyst.graph._call_sub_agent", new=AsyncMock(side_effect=mock_call_sub_agent)):
            await graph.ainvoke({
                "input": "Test question",
                "key_questions": "What are the findings?"
            }, config=config)

        # Verify peripheral scan received context about domain analyses
        assert peripheral_input_captured is not None
        assert "DOMAIN SPECIALIST ANALYSES" in peripheral_input_captured

    async def test_ach_receives_aggregated_consensus_and_peripheral(self):
        """ACH red team should receive both aggregated consensus and peripheral findings."""
        from agents.lead_analyst.config import SubAgentConfig
        from agents.lead_analyst.graph import build_lead_analyst_graph

        sub_agents = [
            SubAgentConfig(label="Agent A", url="http://a:8001", node_id="agent_a"),
        ]
        graph = build_lead_analyst_graph(sub_agents=sub_agents)
        config = _make_runnableconfig()

        ach_input_captured = None

        async def mock_call_sub_agent(url, text, context_id=None, parent_span_id=None):
            nonlocal ach_input_captured
            if "AGGREGATED CONSENSUS TO CHALLENGE" in text:
                ach_input_captured = text
                return "Alternative hypotheses"
            elif "DOMAIN SPECIALIST ANALYSES" in text:
                return "Peripheral findings: weak signal"
            return '{"summary": "domain analysis"}'

        with patch("agents.lead_analyst.graph._call_sub_agent", new=AsyncMock(side_effect=mock_call_sub_agent)):
            await graph.ainvoke({
                "input": "Test question",
                "key_questions": "What are the findings?"
            }, config=config)

        # Verify ACH received both aggregated consensus and peripheral findings
        assert ach_input_captured is not None
        assert "AGGREGATED CONSENSUS TO CHALLENGE" in ach_input_captured
        assert "PERIPHERAL SCAN FINDINGS" in ach_input_captured

    async def test_final_synthesis_integrates_all_stages(self):
        """Final synthesis should integrate consensus + peripheral + ACH."""
        from agents.lead_analyst.config import SubAgentConfig
        from agents.lead_analyst.graph import build_lead_analyst_graph

        sub_agents = [
            SubAgentConfig(label="Agent A", url="http://a:8001", node_id="agent_a"),
        ]
        graph = build_lead_analyst_graph(sub_agents=sub_agents)
        config = _make_runnableconfig()

        with patch("agents.lead_analyst.graph._call_sub_agent",
                   new=AsyncMock(return_value='{"summary": "analysis"}')):
            result = await graph.ainvoke({
                "input": "Test question",
                "key_questions": "What are the findings?"
            }, config=config)

        # Verify state has all intermediate results
        assert "aggregated_consensus" in result
        assert "peripheral_findings" in result
        assert "ach_analysis" in result
        # Verify final output exists
        assert "output" in result
        assert result["output"]


# ---------------------------------------------------------------------------
# Test conditional routing
# ---------------------------------------------------------------------------

class TestConditionalMetaAnalysis:
    """Test that should_run_meta_analysis conditional edge works correctly."""

    async def test_conditional_always_routes_to_peripheral_scan(self):
        """Current default: always run meta-analysis."""
        from agents.lead_analyst.config import SubAgentConfig
        from agents.lead_analyst.graph import build_lead_analyst_graph

        sub_agents = [
            SubAgentConfig(label="Agent A", url="http://a:8001", node_id="agent_a"),
        ]
        graph = build_lead_analyst_graph(sub_agents=sub_agents)
        config = _make_runnableconfig()

        peripheral_called = False

        async def mock_call_sub_agent(url, text, context_id=None, parent_span_id=None):
            nonlocal peripheral_called
            if "DOMAIN SPECIALIST ANALYSES" in text:
                peripheral_called = True
                return "Peripheral findings"
            return '{"summary": "analysis"}'

        with patch("agents.lead_analyst.graph._call_sub_agent", new=AsyncMock(side_effect=mock_call_sub_agent)):
            await graph.ainvoke({
                "input": "Test question",
                "key_questions": "What are the findings?"
            }, config=config)

        assert peripheral_called, "Meta-analysis should run by default"


# ---------------------------------------------------------------------------
# Test edge cases
# ---------------------------------------------------------------------------

class TestMetaAnalysisEdgeCases:
    """Test error handling and edge cases in meta-analysis flow."""

    async def test_peripheral_scan_error_does_not_break_pipeline(self):
        """If peripheral scan fails, pipeline should continue."""
        from agents.lead_analyst.config import SubAgentConfig
        from agents.lead_analyst.graph import build_lead_analyst_graph

        sub_agents = [
            SubAgentConfig(label="Agent A", url="http://a:8001", node_id="agent_a"),
        ]
        graph = build_lead_analyst_graph(sub_agents=sub_agents)
        config = _make_runnableconfig()

        async def mock_call_sub_agent(url, text, context_id=None, parent_span_id=None):
            if "DOMAIN SPECIALIST ANALYSES" in text:
                raise Exception("Peripheral scan service down")
            return '{"summary": "analysis"}'

        with patch("agents.lead_analyst.graph._call_sub_agent", new=AsyncMock(side_effect=mock_call_sub_agent)):
            result = await graph.ainvoke({
                "input": "Test question",
                "key_questions": "What are the findings?"
            }, config=config)

        # Should complete despite peripheral scan failure
        assert "peripheral_findings" in result
        assert "[Error" in result["peripheral_findings"]
        assert "output" in result  # Final output still produced

    async def test_ach_red_team_error_does_not_break_pipeline(self):
        """If ACH red team fails, pipeline should continue."""
        from agents.lead_analyst.config import SubAgentConfig
        from agents.lead_analyst.graph import build_lead_analyst_graph

        sub_agents = [
            SubAgentConfig(label="Agent A", url="http://a:8001", node_id="agent_a"),
        ]
        graph = build_lead_analyst_graph(sub_agents=sub_agents)
        config = _make_runnableconfig()

        async def mock_call_sub_agent(url, text, context_id=None, parent_span_id=None):
            if "AGGREGATED CONSENSUS TO CHALLENGE" in text:
                raise Exception("ACH service down")
            elif "DOMAIN SPECIALIST ANALYSES" in text:
                return "Peripheral findings"
            return '{"summary": "analysis"}'

        with patch("agents.lead_analyst.graph._call_sub_agent", new=AsyncMock(side_effect=mock_call_sub_agent)):
            result = await graph.ainvoke({
                "input": "Test question",
                "key_questions": "What are the findings?"
            }, config=config)

        # Should complete despite ACH failure
        assert "ach_analysis" in result
        assert "[Error" in result["ach_analysis"]
        assert "output" in result  # Final output still produced

    async def test_no_openai_key_fallback_in_final_synthesis(self, monkeypatch):
        """Without OpenAI key, final_synthesis should concatenate consensus + ACH."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        from agents.lead_analyst.config import SubAgentConfig
        from agents.lead_analyst.graph import build_lead_analyst_graph

        sub_agents = [
            SubAgentConfig(label="Agent A", url="http://a:8001", node_id="agent_a"),
        ]
        graph = build_lead_analyst_graph(sub_agents=sub_agents)
        config = _make_runnableconfig()

        with patch("agents.lead_analyst.graph._call_sub_agent",
                   new=AsyncMock(return_value='{"summary": "analysis"}')):
            result = await graph.ainvoke({
                "input": "Test question",
                "key_questions": "What are the findings?"
            }, config=config)

        # Should fallback to concatenation
        assert "output" in result
        assert "ACH RED TEAM CHALLENGE" in result["output"]


# ---------------------------------------------------------------------------
# Test check_all_specialists_done router
# ---------------------------------------------------------------------------

class TestSpecialistCompletionRouter:
    """Test the dynamic mode synchronization barrier."""

    def test_routes_to_peripheral_scan_when_all_done(self):
        """Should route to peripheral_scan when all specialists complete (NEW FLOW)."""
        from agents.lead_analyst.graph import check_all_specialists_done

        state = {
            "selected_specialists": [{"label": "A"}, {"label": "B"}, {"label": "C"}],
            "results": [("A", "..."), ("B", "..."), ("C", "...")],
        }
        assert check_all_specialists_done(state) == "call_peripheral_scan"

    def test_loops_back_when_not_all_done(self):
        """Should loop back to call_specialist if some are still pending."""
        from agents.lead_analyst.graph import check_all_specialists_done

        state = {
            "selected_specialists": [{"label": "A"}, {"label": "B"}, {"label": "C"}],
            "results": [("A", "..."), ("B", "...")],  # C still pending
        }
        assert check_all_specialists_done(state) == "call_specialist"

    def test_handles_empty_results(self):
        """Should loop back if no results yet."""
        from agents.lead_analyst.graph import check_all_specialists_done

        state = {
            "selected_specialists": [{"label": "A"}, {"label": "B"}],
            "results": [],
        }
        assert check_all_specialists_done(state) == "call_specialist"
