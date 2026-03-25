# Design: Fix Langfuse Tracing — Repeated Traces & Orphaned OpenAI Observations

**Date:** 2026-03-25
**Status:** Proposed

---

## Problem Statement

Two symptoms are observed in Langfuse:

1. **Repeated/duplicate root traces** — a single agent run spawns multiple root traces instead of one
2. **OpenAI LLM calls appear as separate root observations** — each direct OpenAI API call creates its own orphaned root trace rather than nesting under the agent's trace

---

## Root Cause Analysis

### Why OpenAI calls appear as separate observations

`agents/lead_analyst/graph.py` uses `from langfuse.openai import AsyncOpenAI` at **lines 347 and 794**. The Langfuse OpenAI SDK wrapper auto-creates a **new root trace per API call** when there is no active `@observe()` context. Since these calls happen inside plain async functions (not decorated with `@observe`), each one spawns an orphaned trace in Langfuse.

### Why traces appear repeated/duplicated

Two separate instrumentation mechanisms are operating simultaneously and producing overlapping output:

| Mechanism | Where | What it creates |
|---|---|---|
| `langfuse.langchain.CallbackHandler` | `agents/base/executor.py` line ~144 | One trace + node-level spans per graph run |
| `Langfuse().start_observation(...)` | `agents/lead_analyst/graph.py` lines 206–213, 500–507 | Manual child spans under same `trace_id` |
| `from langfuse.openai import AsyncOpenAI` | `agents/lead_analyst/graph.py` lines 347, 794 | **New root trace per OpenAI call** (the bug) |

The CallbackHandler and manual spans are both anchored to the same `context_id` as `trace_id` — they work correctly. The Langfuse OpenAI wrapper is the culprit: it has no active trace context and bootstraps new root traces.

A secondary issue is that every call to `Langfuse()` constructs a new SDK client instance (lines 206, 502), rather than reusing a singleton. This can cause race conditions during `flush()` and makes context management harder.

### What is working correctly

- `context_id` propagation across agent boundaries via A2A message metadata (`contextId` + `parentSpanId`) is solid
- The lead analyst correctly threads `parent_span_id` from its manual spans to downstream sub-agent calls
- The `CallbackHandler` correctly creates a root trace and node-level spans for the full graph execution

---

## Design

### Core principle

**Pick one instrumentation mechanism and apply it consistently.** The two mechanisms are:

- **LangChain `CallbackHandler`** — graph/node level (already in place, keep it)
- **`langfuse.openai` wrapper + `@observe` decorator** — generation level (extend to all LLM-calling nodes)

These are compatible and can nest: `@observe` on a node function creates an observation that nests inside the node span created by `CallbackHandler`.

### Proposed changes

#### 1. `agents/base/tracing.py` — add two shared helpers

```python
_langfuse_client = None

def get_langfuse():
    """Return a shared Langfuse client singleton, or None if not configured."""
    global _langfuse_client
    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
        return None
    if _langfuse_client is None:
        from langfuse import Langfuse
        _langfuse_client = Langfuse()
    return _langfuse_client


def get_openai_client(**kwargs):
    """
    Return an AsyncOpenAI client.
    Uses the Langfuse-wrapped version when Langfuse is configured,
    so all API calls are automatically captured as generations.
    Falls back to raw openai.AsyncOpenAI when Langfuse is not configured.
    """
    if os.getenv("LANGFUSE_PUBLIC_KEY"):
        from langfuse.openai import AsyncOpenAI
    else:
        from openai import AsyncOpenAI
    return AsyncOpenAI(**kwargs)
```

`get_openai_client()` is the single import decision point for the entire codebase.

#### 2. `agents/lead_analyst/graph.py` — three OpenAI client fixes + two Langfuse() fixes

| Location | Current | Fix |
|---|---|---|
| Line 347 (`discover`/specialist selection node) | `from langfuse.openai import AsyncOpenAI` then `AsyncOpenAI(**kwargs)` | Replace with `get_openai_client(**kwargs)` from `agents.base.tracing` |
| Line 794 (`final_synthesis` node) | `from langfuse.openai import AsyncOpenAI` then `AsyncOpenAI(**kwargs)` | Same |
| Line 1005 (`_aggregate_results` aggregation node) | `from openai import AsyncOpenAI` then `AsyncOpenAI(**kwargs)` | Same |
| Line 206 (sub-agent span creation) | `Langfuse()` | Replace with `get_langfuse()` singleton |
| Line 502 (specialist span creation) | `Langfuse()` | Replace with `get_langfuse()` singleton |

Additionally, decorate each of the three LLM-calling node functions with `@observe(name="<node_name>")` and set trace context at the top:

```python
from langfuse.decorators import observe, langfuse_context

@observe(name="aggregate_results")
async def aggregate_results_node(state, config):
    context_id = config["configurable"].get("context_id", "")
    langfuse_context.update_current_trace(id=context_id.replace("-", ""))
    # ... rest of node
```

This gives the `langfuse.openai` wrapper an active context, so its generations nest under this observation rather than creating new root traces.

#### 3. All other agents — apply the same two-line pattern

Each agent that makes direct OpenAI calls needs:

1. Replace `from openai import AsyncOpenAI` / `AsyncOpenAI(**kwargs)` with `get_openai_client(**kwargs)` from `agents.base.tracing`
2. Decorate the node function (or LLM helper) with `@observe(name="...")` and set trace context at entry

| Agent | File | Target |
|---|---|---|
| Specialist | `agents/specialist_agent/graph.py` | `process` node (~line 47) |
| Probability | `agents/probability_agent/graph.py` | `_llm_call` helper (~line 199); also move client to module-level singleton to avoid re-creation per call |
| Summarizer | `agents/summarizer/graph.py` | main LLM node (~line 38) |
| Relevancy | `agents/relevancy/graph.py` | main LLM node (~line 54) |
| Extraction | `agents/extraction_agent/graph.py` | main LLM node |
| Memory | `agents/memory_agent/graph.py` | `write` and `search` nodes |

> **Probability Agent note:** `_llm_call` is currently called from multiple nodes and creates a new `AsyncOpenAI` client on every invocation. Move the client to a module-level singleton using `get_openai_client()` and decorate the function with `@observe`.

#### 4. `agents/base/executor.py` — no changes required

The `CallbackHandler` stays. The `@observe` decorators on node functions create observations that nest *inside* the node spans `CallbackHandler` already creates. There is no conflict — Langfuse handles this nesting automatically.

---

## Resulting Trace Structure

After the fix, a full lead analyst run will produce a single trace with this shape:

```
Trace (id = context_id)
├── Graph run span (CallbackHandler)
│   ├── discover_and_select node span
│   │   └── Generation: OpenAI call (LLM specialist selection)
│   ├── [specialist sub-agent spans] (nested via parent_span_id propagation)
│   ├── aggregate_results node span
│   │   └── Generation: OpenAI call (consensus aggregation)
│   ├── ach_red_team node span
│   ├── final_synthesis node span
│   │   └── Generation: OpenAI call (synthesis)
│   └── respond node span
```

---

## Files to Modify

| File | Change |
|---|---|
| `agents/base/tracing.py` | Add `get_langfuse()` and `get_openai_client()` |
| `agents/lead_analyst/graph.py` | Fix 3 OpenAI instantiations, 2 `Langfuse()` calls, add `@observe` on 3 nodes |
| `agents/specialist_agent/graph.py` | `process` node |
| `agents/probability_agent/graph.py` | `_llm_call` helper + client singleton |
| `agents/summarizer/graph.py` | Main node |
| `agents/relevancy/graph.py` | Main node |
| `agents/extraction_agent/graph.py` | Main node |
| `agents/memory_agent/graph.py` | `write`/`search` nodes |

---

## Verification

1. Start all agents locally with Langfuse env vars configured
2. Submit a task to the lead analyst via the dashboard
3. In Langfuse, confirm:
   - Exactly **one root trace** per task run, identified by `context_id`
   - Sub-agent runs appear as **child spans** under the root trace, not as new root traces
   - OpenAI generations appear **nested inside their node spans**, not as standalone root traces
   - No orphaned traces with no parent context
