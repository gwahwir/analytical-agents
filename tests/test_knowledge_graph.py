"""Tests for the knowledge graph agent."""
from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

KG_USER_ID = "knowledge_graph"

SAMPLE_EXTRACTION = {
    "entities": [
        {"name": "Elon Musk", "type": "person", "attributes": {"role": "CEO", "sentiment": "neutral"}},
        {"name": "Tesla", "type": "organization", "attributes": {"sector": "automotive"}},
    ],
    "issues": [
        {
            "name": "AI Regulation Debate",
            "type": "issue",
            "attributes": {"domain": "technology", "severity": "high", "status": "ongoing", "summary": "Debate over AI rules"},
        }
    ],
    "relationships": [
        {"subject": "Elon Musk", "predicate": "leads", "object": "Tesla"},
    ],
    "source_summary": "An article about Elon Musk and Tesla amid AI regulation concerns.",
}


def make_config(retry_count: int = 0, last_raw: str = "", last_error: str = "") -> dict[str, Any]:
    """Build a minimal RunnableConfig for testing graph nodes directly."""
    executor = MagicMock()
    executor.check_cancelled = MagicMock()
    return {
        "configurable": {
            "executor": executor,
            "task_id": "test-task-id",
            "context_id": "test-context-id",
        }
    }


# ---------------------------------------------------------------------------
# Node 1: extract_entities_and_issues
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kg_extract_node_happy_path():
    """Valid JSON on first attempt — sets extracted, retry_count stays 0."""
    from agents.knowledge_graph.graph import extract_entities_and_issues

    state = {
        "input": "Article about Elon Musk leading Tesla during AI debate.",
        "extracted": None,
        "retry_count": 0,
        "last_raw": "",
        "last_error": "",
    }
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps(SAMPLE_EXTRACTION)

    with patch("agents.knowledge_graph.graph._get_openai_client") as mock_client_fn:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_client_fn.return_value = mock_client

        result = await extract_entities_and_issues(state, make_config())

    assert result["extracted"] == SAMPLE_EXTRACTION
    assert result["retry_count"] == 0
    assert result["last_error"] == ""


@pytest.mark.asyncio
async def test_kg_extract_node_self_correcting_retry():
    """Bad JSON on first 2 attempts, valid on 3rd — error context injected into retry prompts."""
    from agents.knowledge_graph.graph import extract_entities_and_issues

    call_count = 0
    captured_messages = []

    async def mock_create(**kwargs):
        nonlocal call_count
        call_count += 1
        captured_messages.append(kwargs["messages"])
        resp = MagicMock()
        if call_count < 3:
            resp.choices[0].message.content = "not valid json {{{"
        else:
            resp.choices[0].message.content = json.dumps(SAMPLE_EXTRACTION)
        return resp

    # Simulate retry loop manually by calling the node 3 times with accumulating state
    state = {
        "input": "Some article text.",
        "extracted": None,
        "retry_count": 0,
        "last_raw": "",
        "last_error": "",
    }
    with patch("agents.knowledge_graph.graph._get_openai_client") as mock_client_fn:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = mock_create
        mock_client_fn.return_value = mock_client

        # First call — fails
        result1 = await extract_entities_and_issues(state, make_config())
        assert result1["extracted"] is None
        assert result1["retry_count"] == 1
        assert result1["last_error"] != ""
        assert result1["last_raw"] == "not valid json {{{"

        # Second call — fails, error context from previous attempt must be in prompt
        state.update(result1)
        result2 = await extract_entities_and_issues(state, make_config())
        assert result2["extracted"] is None
        assert result2["retry_count"] == 2

        # The second call's prompt should mention the previous error
        second_call_messages = captured_messages[1]
        user_message_content = second_call_messages[-1]["content"]
        assert result1["last_raw"] in user_message_content or result1["last_error"] in user_message_content

        # Third call — succeeds
        state.update(result2)
        result3 = await extract_entities_and_issues(state, make_config())
        assert result3["extracted"] == SAMPLE_EXTRACTION


@pytest.mark.asyncio
async def test_kg_extract_node_retry_exhausted(caplog):
    """All 3 attempts return bad JSON — falls back to empty extraction and logs warning."""
    from agents.knowledge_graph.graph import extract_entities_and_issues

    async def always_bad(**kwargs):
        resp = MagicMock()
        resp.choices[0].message.content = "not json at all"
        return resp

    with patch("agents.knowledge_graph.graph._get_openai_client") as mock_client_fn:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = always_bad
        mock_client_fn.return_value = mock_client

        with caplog.at_level(logging.WARNING, logger="agents.knowledge_graph.graph"):
            # Simulate 3 failed retries (retry_count already at 3)
            state = {
                "input": "Article text.",
                "extracted": None,
                "retry_count": 3,
                "last_raw": "not json at all",
                "last_error": "Expecting value",
            }
            result = await extract_entities_and_issues(state, make_config())

    # When retry_count >= 3, should produce empty extraction
    assert result["extracted"] == {
        "entities": [], "issues": [], "relationships": [], "source_summary": ""
    }
    assert any("exhausted" in r.message.lower() or "fallback" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# Node 2: store_in_mem0
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kg_store_node():
    """mem0 search + add calls made; diff and stats computed correctly."""
    from agents.knowledge_graph.graph import store_in_mem0

    state = {
        "input": "...",
        "extracted": SAMPLE_EXTRACTION,
        "retry_count": 0,
        "last_raw": "",
        "last_error": "",
        "diff": {},
        "stats": {},
    }

    mock_memory = MagicMock()
    # search returns empty → entity is new
    mock_memory.search = MagicMock(return_value={"results": []})
    mock_memory.add = MagicMock(return_value={"results": [{"id": "mem-1"}]})

    with patch("agents.knowledge_graph.graph._get_mem0_client", return_value=mock_memory):
        result = await store_in_mem0(state, make_config())

    assert result["diff"]["entities"]["added"] == ["Elon Musk", "Tesla"]
    assert result["diff"]["entities"]["updated"] == []
    assert result["diff"]["issues"]["added"] == ["AI Regulation Debate"]
    assert result["stats"]["entities_added"] == 2
    assert result["stats"]["issues_added"] == 1
    assert result["stats"]["relationships_added"] == 1


# ---------------------------------------------------------------------------
# Node 3: generate_narrative
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kg_generate_narrative_node():
    """LLM called with diff + stats + source_summary; output is valid dual-format JSON."""
    from agents.knowledge_graph.graph import generate_narrative

    state = {
        "extracted": SAMPLE_EXTRACTION,
        "diff": {
            "entities": {"added": ["Elon Musk", "Tesla"], "updated": []},
            "issues": {"added": ["AI Regulation Debate"], "updated": []},
            "relationships": {"added": ["Elon Musk leads Tesla"]},
        },
        "stats": {"entities_added": 2, "entities_updated": 0, "issues_added": 1, "issues_updated": 0, "relationships_added": 1},
        "narrative": "",
        "output": "",
    }

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "Added 2 entities and 1 new issue."

    with patch("agents.knowledge_graph.graph._get_openai_client") as mock_client_fn:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_client_fn.return_value = mock_client

        result = await generate_narrative(state, make_config())

    assert result["narrative"] == "Added 2 entities and 1 new issue."
    parsed = json.loads(result["output"])
    assert "diff" in parsed
    assert "narrative" in parsed
    assert "stats" in parsed
    assert parsed["narrative"] == "Added 2 entities and 1 new issue."


# ---------------------------------------------------------------------------
# Executor: format_output override
# ---------------------------------------------------------------------------

def test_kg_format_output_override():
    """KnowledgeGraphExecutor.format_output() returns the output field as-is."""
    from agents.knowledge_graph.executor import KnowledgeGraphExecutor

    executor = KnowledgeGraphExecutor()
    artifact = json.dumps({"diff": {}, "narrative": "nothing changed", "stats": {}})
    result = executor.format_output({"output": artifact})
    assert result == artifact
    parsed = json.loads(result)
    assert parsed["narrative"] == "nothing changed"


# ---------------------------------------------------------------------------
# Full pipeline integration test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kg_full_pipeline():
    """Full pipeline: raw text in, dual-format JSON artifact out."""
    from agents.knowledge_graph.graph import build_knowledge_graph_graph

    graph = build_knowledge_graph_graph()

    mock_extraction_response = MagicMock()
    mock_extraction_response.choices[0].message.content = json.dumps(SAMPLE_EXTRACTION)

    mock_narrative_response = MagicMock()
    mock_narrative_response.choices[0].message.content = "2 entities and 1 issue were added."

    call_count = 0

    async def mock_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return mock_extraction_response
        return mock_narrative_response

    mock_memory = MagicMock()
    mock_memory.search = MagicMock(return_value={"results": []})
    mock_memory.add = MagicMock(return_value={"results": [{"id": "mem-1"}]})

    executor = MagicMock()
    executor.check_cancelled = MagicMock()

    with patch("agents.knowledge_graph.graph._get_openai_client") as mock_client_fn, \
         patch("agents.knowledge_graph.graph._get_mem0_client", return_value=mock_memory):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = mock_create
        mock_client_fn.return_value = mock_client

        result = await graph.ainvoke(
            {
                "input": "Article about Elon Musk leading Tesla during the AI regulation debate.",
                "extracted": None,
                "retry_count": 0,
                "last_raw": "",
                "last_error": "",
                "diff": {},
                "stats": {},
                "narrative": "",
                "output": "",
            },
            config={
                "configurable": {
                    "executor": executor,
                    "task_id": "pipeline-test",
                    "context_id": "pipeline-ctx",
                }
            },
        )

    assert result["output"] != ""
    parsed = json.loads(result["output"])
    assert "diff" in parsed
    assert "narrative" in parsed
    assert "stats" in parsed
    assert parsed["narrative"] == "2 entities and 1 issue were added."
    assert parsed["stats"]["entities_added"] == 2
    assert parsed["stats"]["issues_added"] == 1


# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kg_cancellation():
    """check_cancelled is called at the start of every node."""
    from agents.knowledge_graph.graph import (
        extract_entities_and_issues,
        generate_narrative,
        store_in_mem0,
    )
    from agents.base.cancellation import CancellableMixin

    class CancellingExecutor(CancellableMixin):
        def __init__(self):
            super().__init__()

        def check_cancelled(self, task_id):
            raise asyncio.CancelledError("cancelled")

    import asyncio

    executor = CancellingExecutor()
    config = {
        "configurable": {
            "executor": executor,
            "task_id": "cancel-task",
            "context_id": "cancel-ctx",
        }
    }
    state = {"input": "text", "extracted": None, "retry_count": 0, "last_raw": "", "last_error": ""}
    with pytest.raises(asyncio.CancelledError):
        await extract_entities_and_issues(state, config)

    state2 = {**state, "extracted": SAMPLE_EXTRACTION, "diff": {}, "stats": {}}
    with pytest.raises(asyncio.CancelledError):
        await store_in_mem0(state2, config)

    state3 = {**state2, "narrative": "", "output": ""}
    with pytest.raises(asyncio.CancelledError):
        await generate_narrative(state3, config)
