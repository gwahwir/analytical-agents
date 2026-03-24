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
├── executor.py    # Overrides execute() to dispatch write/search/traverse
├── server.py      # A2A FastAPI server, port 8009, 3 skills
└── README.md
```

Infrastructure reuses the existing `postgres` (pgvector) and `neo4j` Docker Compose services — no new containers required.

---

## Skills

Three A2A skills declared on the AgentCard. Callers route to the correct skill by including an `operation` field in the JSON input body alongside the skill-specific parameters.

| Skill ID | `operation` value | Key Input Fields | Output |
|---|---|---|---|
| `memory/write` | `"write"` | `text: str`, `namespace: str` | `{ stored: bool, namespace: str, entities_added: int, relationships_added: int }` |
| `memory/search` | `"search"` | `query: str`, `namespace: str`, `limit: int` (optional, default 5) | `{ results: [{ content: str, score: float, metadata: { entities: [...], namespace: str } }] }` |
| `memory/traverse` | `"traverse"` | `entity: str`, `namespace: str`, `depth: int` (optional, default 2) | `{ nodes: [{ name: str, type: str, namespace: str }], edges: [{ subject: str, predicate: str, object: str, namespace: str }] }` |

Example input body for write:
```json
{ "operation": "write", "text": "Apple acquired Beats in 2014.", "namespace": "lead_analyst" }
```

---

## Executor Dispatch

`MemoryAgentExecutor` subclasses `LangGraphA2AExecutor` and overrides `execute()` to handle multi-skill routing before the graph runs. `build_graph()` is implemented and returns the WriteGraph (satisfying the abstract method contract); it is only invoked for `operation: "write"`.

```
execute(context, event_queue):
  input_json = parse(context.get_user_input())
  operation  = input_json["operation"]

  if operation == "write":
      run WriteGraph via self.graph.astream(...)   ← base class pattern
  elif operation == "search":
      result = await search_memories(input_json)
      emit completed event with result
  elif operation == "traverse":
      result = await traverse_graph(input_json)
      emit completed event with result
  else:
      emit failed event
```

`get_graph_topology()` (called by `GET /graph`) uses `build_graph()` and returns the WriteGraph topology only — the 3-node write flow (extract → store → done). The two direct-call paths (search, traverse) are not LangGraph nodes and are not shown in the dashboard graph; this is acceptable because they are single-step point queries with no branching.

---

## Data Flow

### Write (`operation: "write"`)

```
raw text + namespace
  → [Node 1: extract]  LLM call → { entities, relationships, summary }
                        self-correcting retry up to 3 attempts
                        (same error-injection pattern as knowledge_graph)
  → [Node 2: store]    asyncpg INSERT embeddings into memories table (pgvector)
                        langchain_neo4j CREATE/MERGE nodes + relationships (Neo4j)
  → output: { stored: true, namespace, entities_added: int, relationships_added: int }
```

`stored` is `true` if at least one item was successfully written to either backend; `false` only if both backends rejected all writes.

### Search (`operation: "search"`)

Direct async function — no LangGraph. Steps:
1. Embed `query` using the configured embedding model
2. `SELECT content, metadata, 1 - (embedding <=> $vec) AS score FROM memories WHERE namespace = $ns ORDER BY embedding <=> $vec LIMIT $limit`
3. Return `{ results: [...] }`

Cancellation: `check_cancelled(task_id)` is called once before the embedding call and once before the DB query.

### Traverse (`operation: "traverse"`)

Direct async function — no LangGraph. Steps:
1. Run Cypher via `langchain_neo4j`:
   ```cypher
   MATCH (n:Entity {name: $entity, namespace: $ns})-[r*1..$depth]-(m:Entity {namespace: $ns})
   RETURN n, r, m
   ```
2. Flatten to `{ nodes: [{name, type, namespace}], edges: [{subject, predicate, object, namespace}] }`

Cancellation: `check_cancelled(task_id)` is called once before the Cypher query.

---

## Storage Design

### pgvector — `memories` table

```sql
CREATE EXTENSION IF NOT EXISTS vector;

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
    USING hnsw (embedding vector_cosine_ops);
```

`hnsw` is used instead of `ivfflat` because it performs well on small-to-medium datasets without requiring a minimum row count to be useful (available in pgvector 0.5+, which is present in the `pgvector/pgvector:pg16-trixie` image already in docker-compose).

Table and index are created on agent startup via `asyncpg` if they do not already exist.

`metadata` column content written during the write path:
```json
{ "entities": ["Apple", "Beats"], "namespace": "lead_analyst", "source": "write" }
```

### Neo4j

- Nodes: `:Entity { name: str, type: str, namespace: str }`
- Relationships: `(a:Entity)-[:RELATES { predicate: str, namespace: str }]->(b:Entity)`
- Namespace is a property on every node and edge; all queries filter by `namespace`.
- Both agents (`memory_agent` and `knowledge_graph`) write to the same Neo4j instance. No conflict: `memory_agent` uses `:Entity` nodes; mem0 (used by `knowledge_graph`) uses its own internal label scheme. Coexistence is safe.

### pgvector coexistence with `knowledge_graph`

The `knowledge_graph` agent's mem0 client manages its own tables (mem0 creates `memory_vector` or similar internal tables). The `memory_agent` creates a `memories` table — a distinct name that does not conflict with any mem0-managed table. Both agents can point at the same Postgres database safely. The `MEMORY_PG_DSN` and `MEM0_PG_DSN` env vars can point at the same or different DSNs.

---

## `stores.py` — Client Singletons

Two module-level singletons initialized lazily on first use:

- `get_pgvector_pool()` — returns an `asyncpg` connection pool; runs `CREATE TABLE IF NOT EXISTS` on first call; requires `MEMORY_PG_DSN`
- `get_neo4j_graph()` — returns a `langchain_neo4j` `Neo4jGraph` instance; requires `MEMORY_NEO4J_URL`, `MEMORY_NEO4J_USER`, `MEMORY_NEO4J_PASSWORD`
- `get_embedder()` — returns an embedding callable (OpenAI or compatible); requires `MEMORY_EMBEDDING_MODEL` and `OPENAI_API_KEY`

All three raise `EnvironmentError` on first use if required env vars are missing (fail-fast, consistent with existing agents). All are thin wrappers to allow easy mocking in tests.

---

## Error Handling

| Scenario | Behavior |
|---|---|
| LLM extraction returns invalid JSON | Retry up to 3 times with error context injected into prompt |
| Missing required env vars | `EnvironmentError` on first store access; agent fails to start |
| Single entity fails to write to Neo4j | Log warning, skip, continue — partial success reported in output |
| Single embedding fails to insert into pgvector | Log warning, skip, continue |
| Both backends reject all writes | `stored: false` in output; task still completes (not failed) |
| Unknown `operation` value | Emit `TaskState.failed` with descriptive message |
| Task cancelled mid-write (LangGraph) | `check_cancelled(task_id)` at each node; raises `CancelledError` |
| Task cancelled mid-search or mid-traverse | `check_cancelled(task_id)` called before each I/O call |

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MEMORY_AGENT_URL` | `http://localhost:8009` | Agent's externally-reachable URL |
| `MEMORY_NEO4J_URL` | — | Neo4j bolt URL (required) |
| `MEMORY_NEO4J_USER` | — | Neo4j username (required) |
| `MEMORY_NEO4J_PASSWORD` | — | Neo4j password (required) |
| `MEMORY_PG_DSN` | — | pgvector-enabled PostgreSQL DSN (required) |
| `MEMORY_EMBEDDING_MODEL` | — | Embedding model name, e.g. `text-embedding-3-small` (required) |
| `MEMORY_EMBEDDING_DIMS` | `1024` | Vector dimensions — must match the embedding model's output |
| `OPENAI_API_KEY` | — | Required for LLM extraction and embeddings |
| `OPENAI_BASE_URL` | OpenAI default | Custom OpenAI-compatible base URL |
| `OPENAI_MODEL` | `gpt-4o-mini` | LLM model for entity extraction |

`MEMORY_*` vars are intentionally separate from `MEM0_*` vars so both `memory_agent` and `knowledge_graph` can coexist pointing at the same or different backends.

---

## Testing

File: `tests/test_memory_agent.py`

| Test | What is mocked | What is asserted |
|---|---|---|
| `memory/write` happy path | LLM extraction call + asyncpg pool + Neo4j graph | Output has correct `entities_added`, `relationships_added`, `stored: true` |
| `memory/write` retry | LLM returns invalid JSON on attempt 1, valid on attempt 2 | Task completes; retry count = 2 |
| `memory/search` | asyncpg query (returns fake rows with embeddings + scores) | Results are ranked, namespace-filtered, match expected shape |
| `memory/traverse` | Neo4j Cypher call | Nodes and edges match expected shape with correct properties |
| Namespace isolation | asyncpg query | Search in namespace `A` returns no rows written to namespace `B` |
| Cancellation (write) | `CancellableMixin.check_cancelled` raises on second call | Task reaches `canceled` state |
| Cancellation (search) | `check_cancelled` raises before DB query | Task reaches `canceled` state |
| Unknown operation | No store mocks needed | Task reaches `failed` state with descriptive message |

All tests use `pytest-asyncio` (`asyncio_mode = auto`) and `pytest-httpx`. No real Neo4j or Postgres process required. Store singletons are patched at the module level (`stores.get_pgvector_pool`, `stores.get_neo4j_graph`, `stores.get_embedder`).

---

## Deployment

**`docker-compose.yml`** — add `memory-agent` service depending on `control-plane`, `postgres` (already `service_healthy`), and `neo4j` (already `service_healthy`). No new infrastructure services required.

**`run-local.sh`** — add step starting `python -m agents.memory_agent.server` with `MEMORY_*` env vars.

**`Dockerfile.memory-agent`** — follows the same pattern as `Dockerfile.knowledge-graph`.

**CLAUDE.md** — add `memory_agent` row to the agents table and the env var tables.
