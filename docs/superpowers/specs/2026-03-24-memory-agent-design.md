# Memory Agent Design

**Date:** 2026-03-24
**Status:** Approved
**Port:** 8009
**Agent type ID:** `memory-agent`

## Overview

A general-purpose dual-store memory agent that any other agent in the Mission Control system can call to write and retrieve memories. Memories are namespaced by a caller-supplied string, stored in two backends simultaneously — pgvector for semantic search and Neo4j for graph traversal — and written via LLM extraction from raw text.

This agent does **not** use mem0. It drives `asyncpg` (pgvector) and `langchain_neo4j` (Neo4j) directly, giving full control over schema, query logic, and what gets stored.

---

## Architecture

```
agents/memory_agent/
├── graph.py       # WriteGraph: extract → store (LangGraph, with retry)
├── stores.py      # Singleton clients for pgvector (asyncpg) and Neo4j (langchain_neo4j)
├── executor.py    # Dispatches write/search/traverse to graph or direct async functions
├── server.py      # A2A FastAPI server, port 8009, 3 skills
└── README.md
```

Infrastructure reuses the existing `postgres` (pgvector) and `neo4j` Docker Compose services — no new containers required.

---

## Skills

Three A2A skills registered on the agent:

| Skill ID | Input | Output |
|---|---|---|
| `memory/write` | `text`, `namespace` | `{ stored, namespace, entities_added, relationships_added }` |
| `memory/search` | `query`, `namespace`, `limit` (optional, default 5) | `{ results: [{ content, score, metadata }] }` |
| `memory/traverse` | `entity`, `namespace`, `depth` (optional, default 2) | `{ nodes: [...], edges: [...] }` |

---

## Data Flow

### Write (`memory/write`)

```
raw text + namespace
  → [Node 1: extract]  LLM call → { entities, relationships, summary }
                        self-correcting retry up to 3 attempts (same pattern as knowledge_graph)
  → [Node 2: store]    asyncpg INSERT embeddings into memories table (pgvector)
                        langchain_neo4j CREATE/MERGE nodes + relationships (Neo4j)
  → output: { stored, namespace, entities_added, relationships_added }
```

### Search (`memory/search`)

Direct async function (no LangGraph). Embeds the query string, runs a cosine similarity search against the `memories` table filtered by namespace, returns top-k ranked results.

### Traverse (`memory/traverse`)

Direct async function (no LangGraph). Runs a parameterized Cypher query via `langchain_neo4j`, walking the graph up to `depth` hops from the named entity within the given namespace. Returns nodes and edges.

---

## Storage Design

### pgvector — `memories` table

```sql
CREATE TABLE IF NOT EXISTS memories (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    namespace   TEXT NOT NULL,
    content     TEXT NOT NULL,
    embedding   vector(1024),
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS memories_namespace_idx ON memories (namespace);
CREATE INDEX IF NOT EXISTS memories_embedding_idx ON memories
    USING ivfflat (embedding vector_cosine_ops);
```

Table is created on agent startup if it does not already exist. Embedding dimensions are configurable via `MEMORY_EMBEDDING_DIMS` (default 1024).

### Neo4j

- Nodes: `:Entity { name, type, namespace }`
- Relationships: `(a)-[:RELATES { predicate, namespace }]->(b)`
- Namespace is a property on every node and edge; queries always filter by namespace.
- No separate graph per namespace — one graph, namespace as a property filter.

---

## `stores.py` — Client Singletons

Two module-level singletons initialized lazily on first use:

- `get_pgvector_pool()` — returns an `asyncpg` connection pool; reads schema from env vars; creates the `memories` table on first call
- `get_neo4j_driver()` — returns a `langchain_neo4j` `Neo4jGraph` instance

Both raise `EnvironmentError` on startup if required env vars are missing (fail-fast, consistent with existing agents). Both are thin wrappers so they can be easily mocked in tests.

---

## Executor Dispatch

`MemoryAgentExecutor` subclasses `LangGraphA2AExecutor`. On each incoming task:

1. Parse the skill ID from the A2A request (`memory/write`, `memory/search`, or `memory/traverse`)
2. Route:
   - `memory/write` → run `WriteGraph` via LangGraph
   - `memory/search` → call `search_memories()` directly
   - `memory/traverse` → call `traverse_graph()` directly
3. Emit `TaskStatusUpdateEvent` at each step

---

## Error Handling

| Scenario | Behavior |
|---|---|
| LLM extraction returns invalid JSON | Retry up to 3 times with error context injected into prompt |
| Store connection missing env vars | Fail fast on startup with clear `EnvironmentError` |
| Single entity fails to write to Neo4j | Log warning, skip, continue — partial success reported in output |
| Single embedding fails to insert | Log warning, skip, continue |
| Task cancelled mid-write | `check_cancelled(task_id)` called at each LangGraph node; raises and sets task to `canceled` |

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MEMORY_AGENT_URL` | `http://localhost:8009` | Agent's externally-reachable URL |
| `MEMORY_NEO4J_URL` | — | Neo4j bolt URL (required) |
| `MEMORY_NEO4J_USER` | — | Neo4j username (required) |
| `MEMORY_NEO4J_PASSWORD` | — | Neo4j password (required) |
| `MEMORY_PG_DSN` | — | pgvector-enabled PostgreSQL DSN (required) |
| `MEMORY_EMBEDDING_DIMS` | `1024` | Vector dimensions — must match embedding model output |

These are intentionally separate from the `MEM0_*` vars used by `knowledge_graph` so both agents can coexist pointing at the same or different backends.

---

## Testing

File: `tests/test_memory_agent.py`

Test cases:
- `memory/write` — mock LLM + both store writes; assert output counts are correct
- `memory/write` retry — mock first LLM response as invalid JSON, second as valid; assert retry succeeded
- `memory/search` — mock asyncpg query; assert results are ranked and namespace-filtered
- `memory/traverse` — mock Neo4j query; assert nodes and edges returned correctly
- Namespace isolation — assert search in namespace `A` does not return results written to namespace `B`
- Cancellation — assert `check_cancelled` raises mid-graph and task reaches `canceled` state

All tests use `pytest-asyncio` (async by default via `asyncio_mode = auto`) and `pytest-httpx`. No real Neo4j or Postgres process required.

---

## Deployment

**`docker-compose.yml`** — add `memory-agent` service depending on `control-plane`, `postgres`, and `neo4j` (all already present).

**`run-local.sh`** — add step 10/11 starting `python -m agents.memory_agent.server` with `MEMORY_*` env vars.

**`Dockerfile.memory-agent`** — follows the same pattern as `Dockerfile.knowledge-graph`.
