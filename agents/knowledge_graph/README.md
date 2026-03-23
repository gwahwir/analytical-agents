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
