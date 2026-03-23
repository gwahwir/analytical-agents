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

import asyncio
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

    raw = ""
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
            "last_raw": raw,
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
    # Defensive guard: when retry_count >= MAX_RETRIES, the node itself
    # already sets extracted to an empty dict, so this branch is unreachable
    # in practice but protects against future logic changes.
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
            existing = await asyncio.to_thread(memory.search, name, user_id=KG_USER_ID, limit=1)
            results = existing.get("results", []) if isinstance(existing, dict) else existing
            already_exists = len(results) > 0

            attrs = entity.get("attributes", {})
            mem_text = f"{entity.get('type', 'entity').capitalize()}: {name}"
            if attrs:
                attr_str = ", ".join(f"{k}: {v}" for k, v in attrs.items())
                mem_text += f", {attr_str}"
            await asyncio.to_thread(memory.add, mem_text, user_id=KG_USER_ID)

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
            existing = await asyncio.to_thread(memory.search, name, user_id=KG_USER_ID, limit=1)
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
            await asyncio.to_thread(memory.add, mem_text, user_id=KG_USER_ID)

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
            await asyncio.to_thread(memory.add, rel_text, user_id=KG_USER_ID)
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
