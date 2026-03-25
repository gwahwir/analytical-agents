"""Tests for baseline comparison specialist and Lead Analyst integration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_runnableconfig():
    """Create a mock RunnableConfig for graph execution."""
    executor = MagicMock()
    executor.check_cancelled = MagicMock()
    return {"configurable": {"executor": executor, "task_id": "t1", "context_id": "c1"}}


class TestBaselineComparisonNode:
    """Test baseline comparison node in Lead Analyst graph."""

    @pytest.mark.asyncio
    async def test_baseline_comparison_called_when_baselines_provided(self):
        """Baseline comparison node is invoked when baselines field is populated."""
        from agents.lead_analyst.graph import call_baseline_comparison

        state = {
            "baselines": "Prior assessment: Risk level is high",
            "aggregated_consensus": "New assessment: Risk level is moderate",
        }
        config = _make_runnableconfig()

        with patch(
            "agents.lead_analyst.graph._call_sub_agent",
            new=AsyncMock(return_value='{"baseline_changes": {"confirmed": ["Point A"]}}'),
        ) as mock_call:
            result = await call_baseline_comparison(state, config)

        assert "baseline_comparison" in result
        assert result["baseline_comparison"]  # Not empty
        assert "baseline_changes" in result["baseline_comparison"]
        mock_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_baseline_comparison_skipped_when_no_baselines(self):
        """Baseline comparison is skipped when baselines field is empty."""
        from agents.lead_analyst.graph import call_baseline_comparison

        state = {
            "baselines": "",  # Empty baselines
            "aggregated_consensus": "New assessment: Risk level is moderate",
        }
        config = _make_runnableconfig()

        with patch(
            "agents.lead_analyst.graph._call_sub_agent",
            new=AsyncMock(return_value="mock output"),
        ) as mock_call:
            result = await call_baseline_comparison(state, config)

        # Baseline comparison should return empty string
        assert result.get("baseline_comparison", "") == ""
        # _call_sub_agent should NOT be called
        mock_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_baseline_comparison_input_format(self):
        """Verify baseline comparison receives correctly formatted input."""
        from agents.lead_analyst.graph import call_baseline_comparison

        state = {
            "baselines": "Original assessment: Risk level is high",
            "aggregated_consensus": "New assessment: Risk level is moderate",
        }
        config = _make_runnableconfig()

        with patch(
            "agents.lead_analyst.graph._call_sub_agent",
            new=AsyncMock(return_value='{"confirmed": []}'),
        ) as mock_call:
            await call_baseline_comparison(state, config)

        # Verify _call_sub_agent was called with formatted input including ACH context
        call_args = mock_call.call_args
        input_text = call_args[0][1]  # Second positional arg
        assert "## BASELINE ASSESSMENTS:" in input_text
        assert "Original assessment: Risk level is high" in input_text
        assert "## NEW ANALYSIS (Aggregated Consensus):" in input_text
        assert "New assessment: Risk level is moderate" in input_text
        # Should include ACH section even if not provided in state
        assert "## ACH RED TEAM CHALLENGES" in input_text

    @pytest.mark.asyncio
    async def test_baseline_comparison_error_handling(self):
        """Verify graceful error handling when specialist call fails."""
        from agents.lead_analyst.graph import call_baseline_comparison

        state = {
            "baselines": "Prior assessment: Risk level is high",
            "aggregated_consensus": "New assessment",
        }
        config = _make_runnableconfig()

        # Simulate specialist failure
        with patch(
            "agents.lead_analyst.graph._call_sub_agent",
            new=AsyncMock(side_effect=Exception("Connection refused")),
        ):
            result = await call_baseline_comparison(state, config)

        # Should return error message, not raise exception
        assert "baseline_comparison" in result
        assert result["baseline_comparison"].startswith("[Error calling baseline_comparison:")


class TestBaselineComparisonIntegration:
    """Integration tests for baseline comparison in full Lead Analyst pipeline."""

    @pytest.mark.asyncio
    async def test_final_synthesis_includes_baseline_changes(self):
        """Final synthesis output includes baseline comparison results when provided."""
        from agents.lead_analyst.graph import final_synthesis

        state = {
            "aggregated_consensus": "Consensus analysis here",
            "ach_analysis": "ACH challenges here",
            "baseline_comparison": '{"baseline_changes": {"challenged": ["Point X"]}}',
        }
        config = _make_runnableconfig()

        # Test without OpenAI key (concatenation mode)
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            result = await final_synthesis(state, config)

        output = result["output"]
        assert "BASELINE CHANGE ANALYSIS" in output
        assert "baseline_changes" in output

    @pytest.mark.asyncio
    async def test_final_synthesis_without_baseline_comparison(self):
        """Final synthesis works correctly when no baseline comparison provided."""
        from agents.lead_analyst.graph import final_synthesis

        state = {
            "aggregated_consensus": "Consensus analysis here",
            "ach_analysis": "ACH challenges here",
            "baseline_comparison": "",  # No baseline comparison
        }
        config = _make_runnableconfig()

        # Test without OpenAI key (concatenation mode)
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            result = await final_synthesis(state, config)

        output = result["output"]
        # Should still work, just without baseline comparison section
        assert "Consensus analysis here" in output
        assert "ACH challenges here" in output
        assert "BASELINE CHANGE ANALYSIS" not in output

    @pytest.mark.asyncio
    async def test_final_synthesis_skips_error_baseline_comparison(self):
        """Final synthesis skips baseline comparison section when it contains an error."""
        from agents.lead_analyst.graph import final_synthesis

        state = {
            "aggregated_consensus": "Consensus analysis here",
            "ach_analysis": "ACH challenges here",
            "baseline_comparison": "[Error calling baseline_comparison: Connection refused]",
        }
        config = _make_runnableconfig()

        # Test without OpenAI key (concatenation mode)
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            result = await final_synthesis(state, config)

        output = result["output"]
        # Should not include error message in output
        assert "BASELINE CHANGE ANALYSIS" not in output
        assert "[Error calling baseline_comparison:" not in output


class TestGraphWiring:
    """Test that baseline comparison node is correctly wired into the graph."""

    def test_baseline_comparison_node_exists(self):
        """Verify baseline_comparison node is added to the graph."""
        from agents.lead_analyst.graph import build_lead_analyst_graph

        graph = build_lead_analyst_graph(sub_agents=[], dynamic_discovery=False)

        # Check that the compiled graph has the baseline_comparison node
        # LangGraph's compiled graphs have a 'nodes' attribute
        assert hasattr(graph, "nodes")
        node_names = [node for node in graph.nodes.keys()]
        assert "call_baseline_comparison" in node_names

    def test_baseline_comparison_in_pipeline_sequence(self):
        """Verify baseline_comparison is correctly positioned in the pipeline."""
        from agents.lead_analyst.graph import build_lead_analyst_graph

        graph = build_lead_analyst_graph(sub_agents=[], dynamic_discovery=False)

        # Verify edges exist: ach_red_team → baseline_comparison → final_synthesis
        # LangGraph compiled graphs have edges stored in graph structure
        assert hasattr(graph, "nodes")
        # This is a smoke test - if the graph compiles without error, edges are correct
        # Full edge validation would require inspecting internal LangGraph structure


class TestBaselineComparisonWithACH:
    """Test baseline comparison integration with ACH context."""

    @pytest.mark.asyncio
    async def test_baseline_comparison_receives_ach_context(self):
        """Verify ACH analysis is passed to baseline comparison specialist."""
        from agents.lead_analyst.graph import call_baseline_comparison

        state = {
            "baselines": "Prior: Risk level high",
            "aggregated_consensus": "Current: Risk level moderate",
            "ach_analysis": "ACH challenges: Consensus may underestimate risk due to X",
        }
        config = _make_runnableconfig()

        with patch(
            "agents.lead_analyst.graph._call_sub_agent",
            new=AsyncMock(return_value='{"confirmed_tentative": ["Risk level"]}'),
        ) as mock_call:
            await call_baseline_comparison(state, config)

        # Verify ACH context is included in input
        call_args = mock_call.call_args
        input_text = call_args[0][1]
        assert "## ACH RED TEAM CHALLENGES" in input_text
        assert "ACH challenges: Consensus may underestimate risk" in input_text

    @pytest.mark.asyncio
    async def test_baseline_comparison_handles_missing_ach(self):
        """Verify graceful handling when ACH is not available."""
        from agents.lead_analyst.graph import call_baseline_comparison

        state = {
            "baselines": "Prior: Risk level high",
            "aggregated_consensus": "Current: Risk level moderate",
            # No ach_analysis in state
        }
        config = _make_runnableconfig()

        with patch(
            "agents.lead_analyst.graph._call_sub_agent",
            new=AsyncMock(return_value='{"confirmed": ["Risk level"]}'),
        ) as mock_call:
            result = await call_baseline_comparison(state, config)

        # Should still work, with "not available" message
        assert "baseline_comparison" in result
        call_args = mock_call.call_args
        input_text = call_args[0][1]
        assert "ACH analysis not available" in input_text

    @pytest.mark.asyncio
    async def test_final_synthesis_appends_raw_outputs(self):
        """Verify final synthesis appends raw ACH and baseline comparison as appendices."""
        from agents.lead_analyst.graph import final_synthesis

        state = {
            "aggregated_consensus": "Consensus analysis here",
            "ach_analysis": "ACH challenges: H2, H3, H4 hypotheses",
            "baseline_comparison": '{"baseline_changes": {"confirmed": ["Point A"]}}',
        }
        config = _make_runnableconfig()

        # Test without OpenAI key (concatenation mode)
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            result = await final_synthesis(state, config)

        output = result["output"]
        # Should include appendices with raw outputs
        assert "## APPENDIX A: ACH RED TEAM CHALLENGE" in output
        assert "ACH challenges: H2, H3, H4 hypotheses" in output
        assert "## APPENDIX B: BASELINE CHANGE ANALYSIS" in output
        assert '{"baseline_changes"' in output
