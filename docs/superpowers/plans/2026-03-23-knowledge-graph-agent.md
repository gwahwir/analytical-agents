# Knowledge Graph Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a mem0-backed agent (port 8008) that ingests raw text, extracts entities and issues via LLM, stores them in a Neo4j + pgvector knowledge graph, and returns a structured JSON diff plus human-readable narrative.

**Architecture:** Three LangGraph nodes — `extract_entities_and_issues` (LLM extraction with self-correcting conditional-edge retry loop), `store_in_mem0` (write to Neo4j + pgvector via mem0, compute diff), `generate_narrative` (second LLM call producing the dual-format output). Inherits `LangGraphA2AExecutor` exactly like all other agents.

**Tech Stack:** Python, LangGraph, mem0ai, Neo4j (bolt), pgvector (Postgres), OpenAI API, A2A SDK, FastAPI, pytest-asyncio, pytest-httpx.

**Spec:** `docs/superpowers/specs/2026-03-23-knowledge-graph-agent-design.md`

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Modify | `requirements.txt` | Add `mem0ai` dependency |
| Create | `agents/knowledge_graph/__init__.py` | Empty package marker |
| Create | `agents/knowledge_graph/graph.py` | LangGraph state, 3 nodes, conditional edge retry loop |
| Create | `agents/knowledge_graph/executor.py` | `KnowledgeGraphExecutor` subclassing `LangGraphA2AExecutor`, overrides `format_output` |
| Create | `agents/knowledge_graph/server.py` | A2A FastAPI server, port 8008, lifespan, `/graph` endpoint |
| Create | `agents/knowledge_graph/README.md` | Agent documentation |
| Create | `tests/test_knowledge_graph.py` | All 8 tests |
| Create | `Dockerfile.knowledge-graph` | Container image for this agent |
| Modify | `docker-compose.yml` | Add `pgvector-db` service, add healthcheck to `neo4j`, add `knowledge-graph-agent` service |
| Modify | `run-local.sh` | Add knowledge graph agent startup |
| Modify | `CLAUDE.md` | Add agent to agent table and env var table |

---

## Task 1: Add mem0ai dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add mem0ai to requirements.txt**

Open `requirements.txt` and add after the `langchain==1.2.13` line:

```
mem0ai>=0.1.29
```

- [ ] **Step 2: Verify the package name is correct**

```bash
pip index versions mem0ai 2>/dev/null | head -3
```

Expected: see a list of available versions.

- [ ] **Step 3: Install it**

```bash
pip install mem0ai
```

Expected: installs without errors.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add mem0ai dependency for knowledge graph agent"
```

---

## Task 2: LangGraph graph — state, nodes, conditional edge

**Files:**
- Create: `agents/knowledge_graph/__init__.py`
- Create: `agents/knowledge_graph/graph.py`

- [ ] **Step 1: Write the failing tests for the graph nodes**

Create `tests/test_knowledge_graph.py`:

```python
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
# Cancellation
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
```

- [ ] **Step 2: Run tests — confirm they all fail with ImportError (module not yet created)**

```bash
pytest tests/test_knowledge_graph.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'agents.knowledge_graph'`

- [ ] **Step 3: Create the package init**

Create `agents/knowledge_graph/__init__.py` as an empty file.

- [ ] **Step 4: Create graph.py**

Create `agents/knowledge_graph/graph.py`:

```python
"""Knowledge Graph agent built with LangGraph.

Ingests raw text, extracts entities/issues/relationships via LLM, stores them
in mem0 (Neo4j + pgvector), and returns a structured diff + narrative.

Nodes:
1. extract_entities_and_issues  – LLM extraction with self-correcting retry
2. store_in_mem0                – write to Neo4j + pgvector via mem0, compute diff
3. generate_narrative           – small LLM call producing the dual-format output

The self-correcting retry is implemented as a conditional edge that loops Node 1
back to itself (up to 3 attempts), injecting the previous parse error + raw
output into the prompt on each retry. RetryPolicy is NOT used here because it
cannot inject error context into the retry prompt.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional, TypedDict

import openai
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph

logger = logging.getLogger(__name__)

KG_USER_ID = "knowledge_graph"
MAX_RETRIES = 3

# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

_openai_client = None
_mem0_client = None


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import AsyncOpenAI
        kwargs: dict[str, Any] = {}
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        _openai_client = AsyncOpenAI(**kwargs)
    return _openai_client


def _get_mem0_client():
    global _mem0_client
    if _mem0_client is None:
        required = {
            "MEM0_NEO4J_URL": os.getenv("MEM0_NEO4J_URL"),
            "MEM0_NEO4J_USER": os.getenv("MEM0_NEO4J_USER"),
            "MEM0_NEO4J_PASSWORD": os.getenv("MEM0_NEO4J_PASSWORD"),
            "MEM0_PG_DSN": os.getenv("MEM0_PG_DSN"),
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise EnvironmentError(
                f"Knowledge Graph agent requires these env vars: {', '.join(missing)}"
            )

        from mem0 import Memory
        import urllib.parse

        dsn = required["MEM0_PG_DSN"]
        parsed = urllib.parse.urlparse(dsn)

        config = {
            "graph_store": {
                "provider": "neo4j",
                "config": {
                    "url": required["MEM0_NEO4J_URL"],
                    "username": required["MEM0_NEO4J_USER"],
                    "password": required["MEM0_NEO4J_PASSWORD"],
                },
            },
            "vector_store": {
                "provider": "pgvector",
                "config": {
                    "dbname": parsed.path.lstrip("/"),
                    "user": parsed.username,
                    "password": parsed.password,
                    "host": parsed.hostname,
                    "port": parsed.port or 5432,
                },
            },
            "llm": {
                "provider": "openai",
                "config": {
                    "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                    "api_key": os.getenv("OPENAI_API_KEY", ""),
                },
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "model": "text-embedding-3-small",
                    "api_key": os.getenv("OPENAI_API_KEY", ""),
                },
            },
        }
        _mem0_client = Memory.from_config(config)
    return _mem0_client


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class KnowledgeGraphState(TypedDict):
    input: str
    extracted: Optional[dict]   # None until extraction succeeds or retries exhausted
    retry_count: int
    last_raw: str
    last_error: str
    diff: dict
    stats: dict
    narrative: str
    output: str


# ---------------------------------------------------------------------------
# Node 1: extract_entities_and_issues
# ---------------------------------------------------------------------------

_EXTRACTION_SYSTEM_PROMPT = """\
You are a knowledge graph extraction engine. Given a blob of text (typically a news article or
informational content), extract all key information and return ONLY a valid JSON object with this exact schema:

{
  "entities": [
    {"name": "Full Name", "type": "person|organization|location|product", "attributes": {}}
  ],
  "issues": [
    {
      "name": "Issue Name",
      "type": "issue",
      "attributes": {
        "domain": "comma-separated domains e.g. technology,policy",
        "severity": "high|medium|low",
        "status": "emerging|ongoing|resolved",
        "summary": "1-2 sentence description of the issue"
      }
    }
  ],
  "relationships": [
    {"subject": "Entity Name", "predicate": "verb e.g. leads|involves|acquired", "object": "Entity or Issue Name"}
  ],
  "source_summary": "2-3 sentence summary of the article"
}

Rules:
- Return ONLY valid JSON — no markdown fences, no commentary outside the JSON.
- Issues are world-interest topics: geopolitical tensions, economic crises, policy debates, tech controversies, etc.
- Normalize entity names (e.g. "President Biden" and "Joe Biden" → one entry with full name).
- Omit empty arrays (use [] not null).
- Extract implicit relationships where clearly implied by context.
"""


async def extract_entities_and_issues(
    state: KnowledgeGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """LLM extraction with self-correcting retry via conditional edge."""
    executor = config["configurable"]["executor"]
    task_id = config["configurable"]["task_id"]
    executor.check_cancelled(task_id)

    retry_count = state.get("retry_count", 0)

    # If retries are exhausted, produce empty extraction and log warning
    if retry_count >= MAX_RETRIES:
        logger.warning(
            "extract_entities_and_issues: retries exhausted after %d attempts, "
            "falling back to empty extraction task_id=%s",
            MAX_RETRIES, task_id,
        )
        return {
            "extracted": {"entities": [], "issues": [], "relationships": [], "source_summary": ""},
            "retry_count": retry_count,
        }

    client = _get_openai_client()
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # Build messages — inject error context on retries
    messages: list[dict] = [{"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT}]

    if retry_count > 0 and state.get("last_raw"):
        corrective_prefix = (
            f"Your previous response failed to parse as valid JSON.\n"
            f"Parse error: {state['last_error']}\n"
            f"Your response was:\n{state['last_raw']}\n\n"
            f"Please correct your response and return ONLY valid JSON matching the schema above.\n\n"
            f"Text to extract from:\n"
        )
        messages.append({"role": "user", "content": corrective_prefix + state["input"]})
    else:
        messages.append({"role": "user", "content": f"Text:\n{state['input']}"})

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            max_completion_tokens=4096,
            timeout=300,
        )
        raw = response.choices[0].message.content or ""
        parsed = json.loads(raw)
        logger.debug("extract_entities_and_issues success task_id=%s retry=%d", task_id, retry_count)
        return {"extracted": parsed, "retry_count": retry_count, "last_error": ""}

    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(
            "extract_entities_and_issues parse error attempt=%d task_id=%s error=%s",
            retry_count + 1, task_id, e,
        )
        return {
            "extracted": None,
            "retry_count": retry_count + 1,
            "last_raw": raw if "raw" in locals() else "",
            "last_error": str(e),
        }
    except openai.RateLimitError as e:
        logger.warning("extract_entities_and_issues rate limited task_id=%s: %s", task_id, e)
        return {"extracted": {"entities": [], "issues": [], "relationships": [], "source_summary": ""}, "retry_count": retry_count}
    except openai.APIError as e:
        logger.error("extract_entities_and_issues API error task_id=%s: %s", task_id, e, exc_info=True)
        return {"extracted": {"entities": [], "issues": [], "relationships": [], "source_summary": ""}, "retry_count": retry_count}


def _route_after_extract(state: KnowledgeGraphState) -> str:
    """Route: retry if extraction failed and retries remain, else proceed."""
    if state.get("extracted") is not None:
        return "store_in_mem0"
    if state.get("retry_count", 0) >= MAX_RETRIES:
        return "store_in_mem0"
    return "extract_entities_and_issues"


# ---------------------------------------------------------------------------
# Node 2: store_in_mem0
# ---------------------------------------------------------------------------

async def store_in_mem0(
    state: KnowledgeGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Write entities, issues, and relationships to mem0; compute diff."""
    executor = config["configurable"]["executor"]
    task_id = config["configurable"]["task_id"]
    executor.check_cancelled(task_id)

    extracted = state.get("extracted") or {"entities": [], "issues": [], "relationships": [], "source_summary": ""}
    memory = _get_mem0_client()

    entities_added: list[str] = []
    entities_updated: list[str] = []
    issues_added: list[str] = []
    issues_updated: list[str] = []
    relationships_added: list[str] = []

    # Write entities
    for entity in extracted.get("entities", []):
        name = entity.get("name", "")
        if not name:
            continue
        try:
            existing = memory.search(name, user_id=KG_USER_ID, limit=1)
            results = existing.get("results", []) if isinstance(existing, dict) else existing
            already_exists = len(results) > 0

            attrs = entity.get("attributes", {})
            mem_text = f"{entity.get('type', 'entity').capitalize()}: {name}"
            if attrs:
                attr_str = ", ".join(f"{k}: {v}" for k, v in attrs.items())
                mem_text += f", {attr_str}"
            memory.add(mem_text, user_id=KG_USER_ID)

            if already_exists:
                entities_updated.append(name)
            else:
                entities_added.append(name)
        except Exception as e:
            logger.warning("store_in_mem0: failed to write entity=%s task_id=%s error=%s", name, task_id, e)

    # Write issues
    for issue in extracted.get("issues", []):
        name = issue.get("name", "")
        if not name:
            continue
        try:
            existing = memory.search(name, user_id=KG_USER_ID, limit=1)
            results = existing.get("results", []) if isinstance(existing, dict) else existing
            already_exists = len(results) > 0

            attrs = issue.get("attributes", {})
            mem_text = f"Issue: {name}"
            if attrs.get("summary"):
                mem_text += f". {attrs['summary']}"
            if attrs.get("domain"):
                mem_text += f" Domain: {attrs['domain']}."
            if attrs.get("severity"):
                mem_text += f" Severity: {attrs['severity']}."
            if attrs.get("status"):
                mem_text += f" Status: {attrs['status']}."
            memory.add(mem_text, user_id=KG_USER_ID)

            if already_exists:
                issues_updated.append(name)
            else:
                issues_added.append(name)
        except Exception as e:
            logger.warning("store_in_mem0: failed to write issue=%s task_id=%s error=%s", name, task_id, e)

    # Write relationships
    for rel in extracted.get("relationships", []):
        subj = rel.get("subject", "")
        pred = rel.get("predicate", "")
        obj = rel.get("object", "")
        if not all([subj, pred, obj]):
            continue
        try:
            rel_text = f"{subj} {pred} {obj}"
            memory.add(rel_text, user_id=KG_USER_ID)
            relationships_added.append(rel_text)
        except Exception as e:
            logger.warning("store_in_mem0: failed to write relationship task_id=%s error=%s", task_id, e)

    diff = {
        "entities": {"added": entities_added, "updated": entities_updated},
        "issues": {"added": issues_added, "updated": issues_updated},
        "relationships": {"added": relationships_added},
    }
    stats = {
        "entities_added": len(entities_added),
        "entities_updated": len(entities_updated),
        "issues_added": len(issues_added),
        "issues_updated": len(issues_updated),
        "relationships_added": len(relationships_added),
    }
    return {"diff": diff, "stats": stats}


# ---------------------------------------------------------------------------
# Node 3: generate_narrative
# ---------------------------------------------------------------------------

async def generate_narrative(
    state: KnowledgeGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Generate human-readable narrative and serialise dual-format output."""
    executor = config["configurable"]["executor"]
    task_id = config["configurable"]["task_id"]
    executor.check_cancelled(task_id)

    diff = state.get("diff", {})
    stats = state.get("stats", {})
    source_summary = (state.get("extracted") or {}).get("source_summary", "")

    client = _get_openai_client()
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a knowledge graph assistant. Given a summary of what was just ingested "
                        "into a knowledge graph, write a single concise paragraph (2-4 sentences) describing "
                        "what was added or updated and how it connects to existing knowledge. "
                        "Be specific about entity names and issues."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Source article summary: {source_summary}\n\n"
                        f"Changes made to the knowledge graph:\n{json.dumps(stats, indent=2)}\n\n"
                        f"Detail of changes:\n{json.dumps(diff, indent=2)}"
                    ),
                },
            ],
            temperature=0.3,
            max_completion_tokens=256,
        )
        narrative = response.choices[0].message.content or ""
    except Exception as e:
        logger.warning("generate_narrative LLM call failed task_id=%s: %s", task_id, e)
        narrative = f"Ingested {stats.get('entities_added', 0)} new entities and {stats.get('issues_added', 0)} new issues."

    output = json.dumps({
        "diff": diff,
        "narrative": narrative,
        "stats": stats,
    })
    return {"narrative": narrative, "output": output}


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_knowledge_graph_graph() -> StateGraph:
    graph = StateGraph(KnowledgeGraphState)

    graph.add_node("extract_entities_and_issues", extract_entities_and_issues)
    graph.add_node("store_in_mem0", store_in_mem0)
    graph.add_node("generate_narrative", generate_narrative)

    graph.set_entry_point("extract_entities_and_issues")
    graph.add_conditional_edges(
        "extract_entities_and_issues",
        _route_after_extract,
        {
            "extract_entities_and_issues": "extract_entities_and_issues",
            "store_in_mem0": "store_in_mem0",
        },
    )
    graph.add_edge("store_in_mem0", "generate_narrative")
    graph.add_edge("generate_narrative", END)

    return graph.compile()
```

- [ ] **Step 5: Run the node tests (not cancellation, executor, or pipeline tests yet)**

```bash
pytest tests/test_knowledge_graph.py -v -k "not cancellation and not format_output and not full_pipeline" 2>&1
```

Expected: 5 tests pass. If any fail, read the error and fix `graph.py`.

- [ ] **Step 6: Commit**

```bash
git add agents/knowledge_graph/__init__.py agents/knowledge_graph/graph.py tests/test_knowledge_graph.py
git commit -m "feat: add knowledge graph agent graph nodes and tests"
```

---

## Task 3: Executor

**Files:**
- Create: `agents/knowledge_graph/executor.py`

- [ ] **Step 1: Create executor.py**

```python
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
```

- [ ] **Step 2: Run the format_output test**

```bash
pytest tests/test_knowledge_graph.py::test_kg_format_output_override -v
```

Expected: PASS.

- [ ] **Step 3: Run the cancellation test**

```bash
pytest tests/test_knowledge_graph.py::test_kg_cancellation -v
```

Expected: PASS.

- [ ] **Step 4: Run all knowledge graph tests**

```bash
pytest tests/test_knowledge_graph.py -v
```

Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add agents/knowledge_graph/executor.py
git commit -m "feat: add KnowledgeGraphExecutor with format_output override"
```

---

## Task 4: Server

**Files:**
- Create: `agents/knowledge_graph/server.py`

- [ ] **Step 1: Create server.py**

```python
"""Standalone A2A server for the Knowledge Graph agent.

Run with:
    python -m agents.knowledge_graph.server

Environment variables:
    MEM0_NEO4J_URL        – Required. Neo4j bolt URL (e.g. bolt://localhost:7687).
    MEM0_NEO4J_USER       – Required. Neo4j username.
    MEM0_NEO4J_PASSWORD   – Required. Neo4j password.
    MEM0_PG_DSN           – Required. pgvector-enabled PostgreSQL DSN.
    OPENAI_API_KEY        – Required. OpenAI API key.
    OPENAI_BASE_URL       – Optional. Custom OpenAI-compatible base URL.
    OPENAI_MODEL          – Model to use (default: gpt-4o-mini).
    CONTROL_PLANE_URL     – Optional. Control plane URL for self-registration.
    KNOWLEDGE_GRAPH_AGENT_URL – Optional. This agent's externally-reachable URL.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

import uvicorn
from a2a.server.apps.jsonrpc import A2AFastAPIApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from fastapi import FastAPI

from agents.base.registration import deregister_from_control_plane, register_with_control_plane
from agents.knowledge_graph.executor import KnowledgeGraphExecutor
from dotenv import load_dotenv

load_dotenv()

AGENT_TYPE = "knowledge-graph"
AGENT_PORT = 8008

INPUT_FIELDS = [
    {
        "name": "text",
        "label": "Article / Snippet",
        "type": "textarea",
        "required": True,
        "placeholder": "Paste the article or text snippet to ingest into the knowledge graph...",
    }
]

agent_card = AgentCard(
    name="Knowledge Graph Agent",
    description=(
        "Ingests articles and text snippets, extracts entities (persons, organisations, "
        "locations, products) and issues (topics of world interest), and builds a persistent "
        "knowledge graph backed by Neo4j and pgvector via mem0."
    ),
    version="0.1.0",
    url=f"http://localhost:{AGENT_PORT}",
    capabilities=AgentCapabilities(
        streaming=True,
        push_notifications=False,
    ),
    default_input_modes=["application/json"],
    default_output_modes=["application/json"],
    skills=[
        AgentSkill(
            id="ingest",
            name="Ingest",
            description="Ingests a text article or snippet into the knowledge graph",
            tags=["knowledge-graph", "mem0", "neo4j", "entities", "issues"],
        ),
    ],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    agent_url = os.getenv(
        "KNOWLEDGE_GRAPH_AGENT_URL",
        os.getenv("AGENT_URL", f"http://localhost:{AGENT_PORT}"),
    )
    await register_with_control_plane(AGENT_TYPE, agent_url)
    yield
    await deregister_from_control_plane(AGENT_TYPE, agent_url)


def create_app() -> FastAPI:
    app = FastAPI(title="Knowledge Graph Agent A2A Server", lifespan=lifespan)
    agent_url = os.getenv(
        "KNOWLEDGE_GRAPH_AGENT_URL",
        os.getenv("AGENT_URL", f"http://localhost:{AGENT_PORT}"),
    )
    print(f"My Address is {agent_url}")

    executor = KnowledgeGraphExecutor()
    task_store = InMemoryTaskStore()
    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
    )

    a2a_app = A2AFastAPIApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )
    a2a_app.add_routes_to_app(app)

    @app.get("/graph")
    async def get_graph():
        topology = executor.get_graph_topology()
        topology["input_fields"] = INPUT_FIELDS
        return topology

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=AGENT_PORT)
```

- [ ] **Step 2: Verify the server imports cleanly (no env vars needed yet)**

```bash
python -c "from agents.knowledge_graph.server import create_app; print('OK')"
```

Expected: `My Address is http://localhost:8008` then `OK`.

- [ ] **Step 3: Commit**

```bash
git add agents/knowledge_graph/server.py
git commit -m "feat: add knowledge graph agent A2A server on port 8008"
```

---

## Task 5: README

**Files:**
- Create: `agents/knowledge_graph/README.md`

- [ ] **Step 1: Create the README**

```markdown
# Knowledge Graph Agent

Ingests raw articles and text snippets into a persistent knowledge graph backed by **Neo4j** (graph storage) and **pgvector** (semantic vector search) via [mem0](https://github.com/mem0ai/mem0).

## What It Does

- Extracts **entities** (persons, organisations, locations, products) and **issues** (topics of world interest: geopolitical tensions, economic crises, policy debates, emerging technologies) as first-class graph citizens
- Tracks how entities and issues evolve over time as more articles are ingested
- Returns a **dual-format response**: structured JSON diff (what was added/updated) + human-readable narrative

## Graph

```
extract_entities_and_issues  ──(retry loop, up to 3 attempts)──▶  store_in_mem0  ──▶  generate_narrative
```

| Node | Description |
|------|-------------|
| `extract_entities_and_issues` | LLM extraction with self-correcting retry (injects parse errors back into prompt) |
| `store_in_mem0` | Writes entities, issues, and relationships to Neo4j + pgvector via mem0 |
| `generate_narrative` | Second LLM call producing the human-readable summary + serialised output |

## Running Locally

```bash
MEM0_NEO4J_URL=bolt://localhost:7687 \
MEM0_NEO4J_USER=neo4j \
MEM0_NEO4J_PASSWORD=password \
MEM0_PG_DSN=postgresql://user:pass@localhost:5432/mem0_kg \
OPENAI_API_KEY=sk-... \
CONTROL_PLANE_URL=http://localhost:8000 \
python -m agents.knowledge_graph.server
```

## Input

```json
{"text": "Paste the article or text snippet here..."}
```

## Output

```json
{
  "diff": {
    "entities": {"added": ["Elon Musk", "Tesla"], "updated": []},
    "issues": {"added": ["AI Regulation Debate"], "updated": []},
    "relationships": {"added": ["Elon Musk leads Tesla"]}
  },
  "narrative": "This article introduced 2 new entities and 1 new issue...",
  "stats": {
    "entities_added": 2, "entities_updated": 0,
    "issues_added": 1, "issues_updated": 0,
    "relationships_added": 1
  }
}
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MEM0_NEO4J_URL` | Yes | Neo4j bolt URL |
| `MEM0_NEO4J_USER` | Yes | Neo4j username |
| `MEM0_NEO4J_PASSWORD` | Yes | Neo4j password |
| `MEM0_PG_DSN` | Yes | pgvector-enabled Postgres DSN (separate from control plane DB) |
| `OPENAI_API_KEY` | Yes | OpenAI API key |
| `OPENAI_BASE_URL` | No | Custom OpenAI-compatible base URL |
| `OPENAI_MODEL` | No | LLM model (default: `gpt-4o-mini`) |
| `CONTROL_PLANE_URL` | No | Control plane URL for self-registration |
| `KNOWLEDGE_GRAPH_AGENT_URL` | No | This agent's externally-reachable URL |

## Future Operations (not yet implemented)

- **Query** — `{"query": "AI Regulation Debate"}` → semantic recall + graph traversal + narrative summary
- **Diff** — `{"entity": "Elon Musk", "since": "2026-01-01"}` → attribute diff + relationship diff + narrative
```

- [ ] **Step 2: Commit**

```bash
git add agents/knowledge_graph/README.md
git commit -m "docs: add knowledge graph agent README"
```

---

## Task 6: Dockerfile

**Files:**
- Create: `Dockerfile.knowledge-graph`

- [ ] **Step 1: Create Dockerfile.knowledge-graph**

```dockerfile
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agents/ agents/
COPY control_plane/ control_plane/

EXPOSE 8008
CMD ["python", "-m", "agents.knowledge_graph.server"]
```

- [ ] **Step 2: Commit**

```bash
git add Dockerfile.knowledge-graph
git commit -m "chore: add Dockerfile for knowledge graph agent"
```

---

## Task 7: Docker Compose

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add healthcheck to the existing neo4j service**

In `docker-compose.yml`, the `neo4j` service currently has no healthcheck. Add one so `knowledge-graph-agent` can use `condition: service_healthy`:

Find the neo4j service block and add after `restart: always`:

```yaml
    healthcheck:
      test: ["CMD-SHELL", "wget -q --spider http://localhost:7474 || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 30s
```

Note: `wget` against the Neo4j HTTP API port 7474 is the reliable approach — `cypher-shell` path varies by image version and may not be on `PATH`.

- [ ] **Step 2: Add the pgvector-db service**

Add after the `redis` service block and before `neo4j`:

```yaml
  # ── pgvector DB (for Knowledge Graph Agent vector storage) ─────────────
  pgvector-db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: mem0_kg
      POSTGRES_USER: mem0
      POSTGRES_PASSWORD: mem0_password
    ports:
      - "5433:5432"
    volumes:
      - pgvector_data:/var/lib/postgresql/data
    networks:
      - mc-net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mem0 -d mem0_kg"]
      interval: 5s
      timeout: 5s
      retries: 10
      start_period: 10s
```

Also add `pgvector_data:` to the `volumes:` section at the bottom.

- [ ] **Step 3: Add the knowledge-graph-agent service**

Add after the `probability` service block and before `dashboard`:

```yaml
  # ── Knowledge Graph Agent ───────────────────────────────────────────────
  knowledge-graph-agent:
    build:
      context: .
      dockerfile: Dockerfile.knowledge-graph
    ports:
      - "8008:8008"
    env_file: ".env"
    environment:
      - LOG_LEVEL=INFO
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - OPENAI_MODEL=${OPENAI_MODEL:-gpt-4o-mini}
      - OPENAI_BASE_URL=${OPENAI_BASE_URL:-https://openrouter.ai/api/v1}
      - CONTROL_PLANE_URL=http://control-plane:8000
      - KNOWLEDGE_GRAPH_AGENT_URL=http://knowledge-graph-agent:8008
      - MEM0_NEO4J_URL=bolt://neo4j:7687
      - MEM0_NEO4J_USER=mc
      - MEM0_NEO4J_PASSWORD=mc_password
      - MEM0_PG_DSN=postgresql://mem0:mem0_password@pgvector-db:5432/mem0_kg
    networks:
      - mc-net
    depends_on:
      control-plane:
        condition: service_healthy
      neo4j:
        condition: service_healthy
      pgvector-db:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import httpx; httpx.get('http://localhost:8008/.well-known/agent-card.json').raise_for_status()"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 15s
```

- [ ] **Step 4: Verify the compose file is valid**

```bash
docker compose config --quiet && echo "OK"
```

Expected: `OK` (no YAML errors).

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml
git commit -m "chore: add pgvector-db service and knowledge-graph-agent to docker-compose"
```

---

## Task 8: run-local.sh

**Files:**
- Modify: `run-local.sh`

- [ ] **Step 1: Add the knowledge graph agent to run-local.sh**

Find the line `PROBABILITY_PORT=8007` and add below it:

```bash
KG_PORT=8008
```

Find `echo "[1/9] Starting Control Plane` and change the comment counts throughout (1/9 → 1/10, etc.) OR simply append without renumbering.

After the probability agent block (before the dashboard block), add:

```bash
# ── Knowledge Graph Agent ────────────────────────────────────────────
echo "[9/10] Starting Knowledge Graph Agent on port $KG_PORT..."
MEM0_NEO4J_URL="${MEM0_NEO4J_URL:-bolt://localhost:7687}" \
MEM0_NEO4J_USER="${MEM0_NEO4J_USER:-neo4j}" \
MEM0_NEO4J_PASSWORD="${MEM0_NEO4J_PASSWORD:-password}" \
MEM0_PG_DSN="${MEM0_PG_DSN:-postgresql://mem0:mem0_password@localhost:5433/mem0_kg}" \
CONTROL_PLANE_URL="$CP_URL" \
KNOWLEDGE_GRAPH_AGENT_URL="http://127.0.0.1:$KG_PORT" \
  python -m agents.knowledge_graph.server &
PIDS+=($!)
wait_for_port $KG_PORT "Knowledge Graph Agent"
```

Also update the dashboard start from `[9/9]` to `[10/10]`, and add to the summary printout:

```bash
echo "  Knowledge Graph: http://localhost:$KG_PORT"
```

- [ ] **Step 2: Commit**

```bash
git add run-local.sh
git commit -m "chore: add knowledge graph agent to run-local.sh"
```

---

## Task 9: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add to the agents table**

In the `**Agents:**` table, add a new row:

```
| Knowledge Graph (`agents/knowledge_graph/`) | 8008 | `knowledge-graph` | Ingests articles/snippets, builds persistent knowledge graph of entities and issues via mem0 (Neo4j + pgvector) |
```

- [ ] **Step 2: Add to the env var table**

In the `**Per-Agent URL Variables**` table, add:

```
| `KNOWLEDGE_GRAPH_AGENT_URL` | Knowledge Graph | `http://localhost:8008` |
```

In the `**Shared Agent Variables**` or a new section, add the mem0 vars:

```
| `MEM0_NEO4J_URL` | None | Neo4j bolt URL for knowledge graph agent |
| `MEM0_NEO4J_USER` | None | Neo4j username |
| `MEM0_NEO4J_PASSWORD` | None | Neo4j password |
| `MEM0_PG_DSN` | None | pgvector-enabled Postgres DSN (knowledge graph agent only) |
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add knowledge graph agent to CLAUDE.md"
```

---

## Task 10: Full test suite check

- [ ] **Step 1: Run all tests**

```bash
pytest -v 2>&1
```

Expected: all existing tests pass plus all 8 knowledge graph tests pass. If any existing tests broke, investigate and fix before committing.

- [ ] **Step 2: Run just the knowledge graph tests one more time**

```bash
pytest tests/test_knowledge_graph.py -v
```

Expected: 8 passed.

- [ ] **Step 3: Final commit if any cleanup was needed**

```bash
git add -p  # stage only what changed
git commit -m "fix: ensure all tests pass after knowledge graph agent addition"
```
