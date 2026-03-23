# Knowledge Graph Agent — Design Spec

**Date:** 2026-03-23
**Status:** Approved
**Port:** 8008
**Agent Type ID:** `knowledge-graph`
**Location:** `agents/knowledge_graph/`

---

## 1. Purpose

A persistent knowledge graph agent that ingests raw articles or text snippets and builds an evolving, queryable knowledge graph of **entities** (persons, organisations, locations, products) and **issues** (topics of world interest: geopolitical tensions, economic crises, policy debates, emerging technologies, etc.) as first-class citizens.

The agent tracks how entities and issues evolve over time across multiple ingestion events. It is designed to eventually be registered as a callable A2A sub-agent consumed by the Lead Analyst and Probability agents (see Section 10).

---

## 2. Scope (Current Implementation)

**In scope:**
- Ingest raw text → extract entities, issues, and relationships via LLM
- Store extracted data into mem0 (Neo4j graph + pgvector vectors)
- Return a dual-format response: structured JSON diff + human-readable narrative

**Out of scope (documented for future implementation — see Section 9):**
- Query operation
- Diff operation

---

## 3. Architecture

```
agents/knowledge_graph/
├── graph.py       # LangGraph state machine (3 nodes)
├── executor.py    # Subclass of LangGraphA2AExecutor
├── server.py      # A2A FastAPI server, port 8008
└── README.md
```

Follows the identical structure of all existing agents in this repo (`graph.py` → `executor.py` → `server.py`), inheriting from `LangGraphA2AExecutor`.

---

## 4. LangGraph State

```python
class KnowledgeGraphState(TypedDict):
    # Input
    input: str                      # raw text from A2A request

    # Node 1 output / Node 2+3 input
    extracted: dict                 # parsed extraction JSON (entities, issues, relationships, source_summary)

    # Self-correcting retry state (Node 1)
    retry_count: int                # number of extraction attempts so far
    last_raw: str                   # raw LLM response from last attempt (for retry prompt)
    last_error: str                 # parse error message from last attempt (for retry prompt)

    # Node 2 output / Node 3 input
    diff: dict                      # added/updated entities, issues, relationships
    stats: dict                     # counts summary

    # Node 3 output
    narrative: str                  # human-readable summary of what changed
    output: str                     # final serialised dual-format artifact (JSON string)
```

---

## 5. Data Schema

### 5.1 Extraction Output (`extracted` field)

```json
{
  "entities": [
    {"name": "Elon Musk", "type": "person", "attributes": {"role": "CEO", "sentiment": "neutral"}},
    {"name": "Tesla", "type": "organization", "attributes": {"sector": "automotive"}},
    {"name": "United States", "type": "location", "attributes": {"type": "country"}},
    {"name": "Starlink", "type": "product", "attributes": {"owner": "SpaceX"}}
  ],
  "issues": [
    {
      "name": "AI Regulation Debate",
      "type": "issue",
      "attributes": {
        "domain": "technology|policy",
        "severity": "high|medium|low",
        "status": "emerging|ongoing|resolved",
        "summary": "Brief description of the issue"
      }
    }
  ],
  "relationships": [
    {"subject": "Elon Musk", "predicate": "leads", "object": "Tesla"},
    {"subject": "AI Regulation Debate", "predicate": "involves", "object": "United States"}
  ],
  "source_summary": "2-3 sentence summary of the source article."
}
```

### 5.2 Agent Response (Dual Output)

The executor overrides `format_output()` to serialise the full dual-format artifact as a JSON string:

```json
{
  "diff": {
    "entities": {"added": [...], "updated": [...]},
    "issues": {"added": [...], "updated": [...]},
    "relationships": {"added": [...]}
  },
  "narrative": "This article introduced 3 new entities and updated the ongoing 'AI Regulation Debate' issue, linking it to Tesla and the United States for the first time.",
  "stats": {
    "entities_added": 2,
    "entities_updated": 1,
    "issues_added": 0,
    "issues_updated": 1,
    "relationships_added": 3
  }
}
```

### 5.3 mem0 Storage Mapping

- A single fixed `user_id = "knowledge_graph"` is used for all mem0 writes — this keeps the entire graph in one partition so cross-entity relationships are traversable
- Each entity and issue is passed to `mem0.add()` as a structured text string (e.g. `"Person: Elon Musk, role: CEO, sentiment: neutral"`) so mem0's internal entity extractor can create or merge the corresponding Neo4j node and pgvector embedding
- Relationships are passed as relationship-statement strings (e.g. `"Elon Musk leads Tesla"`) so mem0's graph pipeline creates the corresponding Neo4j edges
- mem0 handles deduplication within the partition natively; the agent does not need to manage it explicitly

---

## 6. LangGraph Nodes (3 total)

### Node 1: `extract_entities_and_issues`

Makes an LLM call (OpenAI) to extract the structured JSON defined in Section 5.1.

**Self-correcting retry via conditional edge (not RetryPolicy):**

Because the retry behaviour requires injecting the previous raw output and parse error back into the prompt, a standard `RetryPolicy` (which simply re-invokes the node) is insufficient. Instead:

- On successful JSON parse: transition to `store_in_mem0`
- On failed JSON parse:
  - Increment `retry_count`, store `last_raw` and `last_error` in state
  - If `retry_count < 3`: loop back to `extract_entities_and_issues` via a conditional edge; the next invocation builds a corrective prompt including `last_raw` and `last_error`
  - If `retry_count >= 3`: transition to `store_in_mem0` with an empty extraction and log a warning

This requires a conditional edge from `extract_entities_and_issues` back to itself (with a counter guard) and then forward to `store_in_mem0`.

### Node 2: `store_in_mem0`

Performs all mem0 writes and computes the diff:

1. For each entity and issue: call `mem0.search()` to check if it already exists (pre-state), then call `mem0.add()` to upsert it
2. For each relationship: call `mem0.add()` with the relationship string
3. Determine added vs. updated from search results vs. write results
4. Populate `diff` and `stats` in state

**Individual write failures** are logged but do not abort the ingest — partial success is preferred over total failure.

### Node 3: `generate_narrative`

Makes a second, small LLM call (can use a cheaper/faster model) that takes `diff`, `stats`, and `source_summary` and produces the human-readable `narrative` string. Then serialises the full dual-format artifact into `output`.

**Cancellation:** `executor.check_cancelled(task_id)` is called at the start of all three nodes.

---

## 7. Data Flow

```
Raw text (A2A input)
        │
        ▼
┌──────────────────────────────────┐
│   extract_entities_and_issues     │  ← LLM call (OpenAI)
│   - Parse input text              │
│   - Extract entities/issues/      │
│     relationships/source_summary  │
│   - Parse JSON response           │
└──────────┬───────────────────────┘
           │
    JSON valid?
     │        │
    yes       no (retry_count < 3)
     │        └──── inject last_raw + last_error
     │              into prompt, loop back
     │
    (retry_count >= 3 → empty extraction)
     │
     ▼
┌──────────────────────────────────┐
│          store_in_mem0            │  ← mem0 hybrid client
│   - Search existing entities/     │    (Neo4j + pgvector)
│     issues (pre-state)            │    user_id = "knowledge_graph"
│   - Add entities via mem0         │
│   - Add issues via mem0           │
│   - Add relationships via mem0    │
│   - Compute diff + stats          │
└──────────┬───────────────────────┘
           │
           ▼
┌──────────────────────────────────┐
│        generate_narrative         │  ← LLM call (small/fast model)
│   - Generate human narrative      │
│   - Serialise dual-format output  │
└──────────┬───────────────────────┘
           │
           ▼
  Dual output artifact
  (structured diff + narrative, JSON string)
```

---

## 8. Environment Variables

| Variable | Description |
|---|---|
| `MEM0_NEO4J_URL` | Neo4j bolt URL (e.g. `bolt://localhost:7687`) |
| `MEM0_NEO4J_USER` | Neo4j username |
| `MEM0_NEO4J_PASSWORD` | Neo4j password |
| `MEM0_PG_DSN` | pgvector-enabled PostgreSQL DSN — **separate from `DATABASE_URL`** (the control plane's task store DB). Must point to a Postgres instance with the `pgvector` extension enabled. |
| `KNOWLEDGE_GRAPH_AGENT_URL` | Agent's externally reachable URL |
| `OPENAI_API_KEY` | Required for LLM calls |
| `OPENAI_BASE_URL` | Optional custom OpenAI-compatible base URL |
| `OPENAI_MODEL` | LLM model (default: `gpt-4o-mini`) |
| `CONTROL_PLANE_URL` | Control plane URL for self-registration |

**mem0 client lifecycle:** Module-level `Memory` client instantiated once on first use (mirroring `_openai_client` pattern in the extraction agent). If `MEM0_NEO4J_URL`, `MEM0_NEO4J_USER`, `MEM0_NEO4J_PASSWORD`, or `MEM0_PG_DSN` are missing, raises a descriptive `EnvironmentError` at startup.

---

## 9. Infrastructure (Docker)

A `Dockerfile.knowledge-graph` is required following the pattern of existing agent Dockerfiles.

A new service block is added to `docker-compose.yml`:

```yaml
knowledge-graph-agent:
  build:
    context: .
    dockerfile: Dockerfile.knowledge-graph
  ports:
    - "8008:8008"
  environment:
    - CONTROL_PLANE_URL=http://control-plane:8000
    - KNOWLEDGE_GRAPH_AGENT_URL=http://knowledge-graph-agent:8008
    - OPENAI_API_KEY=${OPENAI_API_KEY}
    - OPENAI_MODEL=${OPENAI_MODEL:-gpt-4o-mini}
    - MEM0_NEO4J_URL=bolt://neo4j:7687
    - MEM0_NEO4J_USER=${NEO4J_USER:-neo4j}
    - MEM0_NEO4J_PASSWORD=${NEO4J_PASSWORD:-password}
    - MEM0_PG_DSN=${MEM0_PG_DSN}
  depends_on:
    - control-plane
    - neo4j
    - pgvector-db
```

**New infrastructure services required:**
- `neo4j` — Neo4j graph database (if not already in `docker-compose.yml`)
- `pgvector-db` — Postgres with the `pgvector` extension (separate from the control plane's Postgres if one exists)

Both services need healthcheck conditions before `knowledge-graph-agent` starts.

---

## 10. Testing

All tests follow the existing `pytest-asyncio` + `pytest-httpx` pattern in `tests/`.

| Test | Description |
|---|---|
| `test_kg_extract_node_happy_path` | Unit test for `extract_entities_and_issues` with mocked OpenAI returning valid JSON; verifies `extracted` schema compliance |
| `test_kg_extract_node_self_correcting_retry` | Mocked OpenAI returns bad JSON for first 2 attempts, valid JSON on 3rd; verifies `last_raw` and `last_error` are injected into retry prompt |
| `test_kg_extract_node_retry_exhausted` | Mocked OpenAI returns bad JSON all 3 attempts; verifies fallback to empty extraction and warning log |
| `test_kg_store_node` | Unit test for `store_in_mem0` with mocked mem0 client; verifies diff and stats computation |
| `test_kg_generate_narrative_node` | Unit test for `generate_narrative` with mocked OpenAI and pre-populated diff/stats; verifies `output` is valid dual-format JSON |
| `test_kg_format_output_override` | Verifies `KnowledgeGraphExecutor.format_output()` returns the JSON artifact string correctly from the final state |
| `test_kg_full_pipeline` | Integration test mocking OpenAI + mem0; submits raw text via A2A, asserts dual-output artifact structure |
| `test_kg_cancellation` | Verifies clean cancellation mid-graph at each node |

---

## 11. Future Operations (Not Implemented)

### 11.1 Query

Accept a named entity or issue and return a structured answer synthesising:
- Semantic recall from pgvector (what do we know about X?)
- Graph traversal from Neo4j (what is X connected to, and how?)
- A human-readable summary

Input: `{"query": "AI Regulation Debate"}`
Output: summary + related entities/issues + relationship map

### 11.2 Diff

Accept a named entity or issue and a reference date/snapshot ID. Return:
- What attributes changed
- What new relationships appeared or disappeared
- A narrative describing how X has evolved since the reference point

Input: `{"entity": "Elon Musk", "since": "2026-01-01"}`
Output: attribute diff + relationship diff + narrative

---

## 12. Integration Path (Future)

This agent is designed to be registered as a callable **A2A sub-agent** within the existing platform:

- **Lead Analyst** — once the query operation (Section 11.1) is implemented, Lead Analyst can fan out to this agent as a sub-agent to enrich its context with knowledge graph data before aggregating specialist results
- **Probability Agent** — once the diff operation (Section 11.2) is implemented, Probability Agent can request entity/issue evolution timelines to inform probability shift calculations

The dual JSON/narrative output format (Section 5.2) is designed to be consumable by both machine (JSON diff) and LLM-based (narrative) downstream agents. No changes to the Lead Analyst or Probability Agent are required for the current ingest-only scope.
