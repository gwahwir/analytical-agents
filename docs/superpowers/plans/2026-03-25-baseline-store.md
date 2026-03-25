# Baseline Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a plain FastAPI service that stores, versions, and semantically retrieves topic baselines — the deterministic storage layer that a future Baseline Agent will call as a tool.

**Architecture:** PostgreSQL with `ltree` for hierarchical topic paths and `pgvector` for narrative embeddings. Three tables: `baseline_topics` (topic registry), `baseline_versions` (append-only version history), `baseline_deltas` (one row per article that triggered a change). The store owns embedding internally — callers pass plain text only.

**Tech Stack:** Python 3.13, FastAPI, asyncpg, pgvector (`hnsw` index), ltree, OpenAI SDK (embeddings), uvicorn, pytest-asyncio, httpx (ASGI test client)

**Spec:** `docs/superpowers/specs/2026-03-25-baseline-store-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `baseline_store/__init__.py` | Create | Empty package marker |
| `baseline_store/stores.py` | Create | asyncpg pool singleton + embedder singleton + DDL SQL constants |
| `baseline_store/routes.py` | Create | All 8 REST endpoint handlers |
| `baseline_store/server.py` | Create | FastAPI app, lifespan (DDL on startup), uvicorn entry point |
| `baseline_store/README.md` | Create | Usage docs, env vars, endpoint reference |
| `tests/test_baseline_store.py` | Create | All 15+ tests (asyncpg + embedder mocked at module level) |
| `Dockerfile.baseline-store` | Create | Container image (same pattern as Dockerfile.memory-agent) |
| `docker-compose.yml` | Modify | Add `baseline-store` service depending on `postgres` |
| `run-local.sh` | Modify | Add baseline-store startup step |
| `CLAUDE.md` | Modify | Add `baseline_store` row to agents table + all `BASELINE_*` env vars |

---

## Shared Test Helpers (read before writing any test)

All tests in `tests/test_baseline_store.py` use this pattern. Memorise it — you'll repeat it every task.

**App fixture** — bypass lifespan (no real DB on startup in tests):
```python
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.fixture
def app():
    # Import here to avoid triggering module-level side effects before patching
    from baseline_store.server import create_app
    return create_app()

@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
```

**asyncpg mock helper** — asyncpg pool uses `async with pool.acquire() as conn:`:
```python
def make_pool(conn):
    """Wrap a mock connection in a pool whose acquire() is an async context manager."""
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=cm)
    return pool
```

**Patch targets** — always patch these two at module level:
- `baseline_store.stores.get_pgvector_pool` — returns a pool mock
- `baseline_store.stores.get_embedder` — returns an `AsyncMock` callable

---

## Task 1: Package scaffold + `stores.py`

**Files:**
- Create: `baseline_store/__init__.py`
- Create: `baseline_store/stores.py`

### What `stores.py` does

Two lazy singletons. Neither talks to anything real until first called.

`get_pgvector_pool()` — creates an `asyncpg` connection pool on first call, runs DDL to create the three tables and indexes, caches the pool. Raises `EnvironmentError` if `BASELINE_PG_DSN` is unset.

`get_embedder()` — returns an async callable `embed(text: str) -> list[float]` that calls the OpenAI embeddings API. Raises `EnvironmentError` if `BASELINE_EMBEDDING_MODEL` or `OPENAI_API_KEY` is unset.

- [ ] **Step 1: Create the package**

```bash
mkdir baseline_store
touch baseline_store/__init__.py
```

- [ ] **Step 2: Write `stores.py`**

```python
# baseline_store/stores.py
"""Lazy singletons for asyncpg connection pool and OpenAI embedder.

Call get_pgvector_pool() to get the pool (runs DDL on first call).
Call get_embedder() to get an async embed(text) -> list[float] callable.
Both raise EnvironmentError if required env vars are missing.
"""
from __future__ import annotations

import os
import logging
from typing import Callable, Optional

import asyncpg

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None
_embedder: Optional[Callable] = None


def _get_dims() -> int:
    raw = os.getenv("BASELINE_EMBEDDING_DIMS")
    if not raw:
        raise EnvironmentError("BASELINE_EMBEDDING_DIMS is required and must match the embedding model output dimensions")
    return int(raw)


# DDL — executed once on first pool access
def _build_ddl(dims: int) -> str:
    return f"""
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS baseline_topics (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_path   ltree NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS baseline_topics_path_gist
    ON baseline_topics USING GIST (topic_path);

CREATE TABLE IF NOT EXISTS baseline_versions (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_path     ltree NOT NULL,
    version_number INTEGER NOT NULL,
    narrative      TEXT NOT NULL,
    embedding      vector({dims}),
    citations      JSONB DEFAULT '[]',
    created_at     TIMESTAMPTZ DEFAULT now(),
    UNIQUE (topic_path, version_number)
);
CREATE INDEX IF NOT EXISTS baseline_versions_topic_gist
    ON baseline_versions USING GIST (topic_path);
CREATE INDEX IF NOT EXISTS baseline_versions_topic_version
    ON baseline_versions (topic_path, version_number DESC);
CREATE INDEX IF NOT EXISTS baseline_versions_embedding
    ON baseline_versions USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS baseline_deltas (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_path        ltree NOT NULL,
    from_version      INTEGER,
    to_version        INTEGER NOT NULL,
    article_metadata  JSONB DEFAULT '{{}}',
    delta_summary     TEXT NOT NULL,
    claims_added      JSONB DEFAULT '[]',
    claims_superseded JSONB DEFAULT '[]',
    created_at        TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS baseline_deltas_topic_gist
    ON baseline_deltas USING GIST (topic_path);
"""


async def get_pgvector_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    dsn = os.getenv("BASELINE_PG_DSN")
    if not dsn:
        raise EnvironmentError("BASELINE_PG_DSN is required")
    dims = _get_dims()
    _pool = await asyncpg.create_pool(dsn)
    async with _pool.acquire() as conn:
        await conn.execute(_build_ddl(dims))
    logger.info("asyncpg pool created and DDL applied (dims=%d)", dims)
    return _pool


def get_embedder() -> Callable:
    global _embedder
    if _embedder is not None:
        return _embedder
    model = os.getenv("BASELINE_EMBEDDING_MODEL")
    api_key = os.getenv("OPENAI_API_KEY")
    if not model:
        raise EnvironmentError("BASELINE_EMBEDDING_MODEL is required")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY is required")
    base_url = os.getenv("OPENAI_BASE_URL")

    from openai import AsyncOpenAI
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    _client = AsyncOpenAI(**kwargs)

    async def embed(text: str) -> list[float]:
        response = await _client.embeddings.create(model=model, input=text)
        return response.data[0].embedding

    _embedder = embed
    return _embedder
```

- [ ] **Step 3: Commit scaffold**

```bash
git add baseline_store/
git commit -m "feat(baseline-store): add package scaffold and stores.py singletons"
```

---

## Task 2: Topic endpoints — `POST /topics` and `GET /topics`

**Files:**
- Create: `baseline_store/routes.py` (start with topic routes only)
- Create: `baseline_store/server.py` (minimal, enough to run tests)
- Create: `tests/test_baseline_store.py` (topic tests only)

### Minimal `server.py` (needed for test fixtures)

```python
# baseline_store/server.py
from __future__ import annotations
import logging
import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn
from dotenv import load_dotenv
from baseline_store.routes import router

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialise pool + run DDL on startup
    from baseline_store.stores import get_pgvector_pool
    await get_pgvector_pool()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Baseline Store", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("BASELINE_PORT", "8010"))
    uvicorn.run(app, host="0.0.0.0", port=port, timeout_graceful_shutdown=15)
```

- [ ] **Step 1: Write failing tests for topic endpoints**

```python
# tests/test_baseline_store.py
from __future__ import annotations
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch
import asyncpg


# ── Shared helpers ──────────────────────────────────────────────────────────

def make_pool(conn):
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=cm)
    return pool


@pytest.fixture
def app():
    from baseline_store.server import create_app
    return create_app()


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ── POST /topics ─────────────────────────────────────────────────────────────

async def test_post_topics_happy_path(client):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={
        "id": "aaaaaaaa-0000-0000-0000-000000000001",
        "topic_path": "climate_change",
        "display_name": "Climate Change",
        "created_at": "2026-03-25T08:00:00+00:00",
    })
    pool = make_pool(conn)

    with patch("baseline_store.stores.get_pgvector_pool", AsyncMock(return_value=pool)):
        resp = await client.post("/topics", json={
            "topic_path": "climate_change",
            "display_name": "Climate Change",
        })

    assert resp.status_code == 201
    body = resp.json()
    assert body["topic_path"] == "climate_change"
    assert body["display_name"] == "Climate Change"
    assert "id" in body
    assert "created_at" in body


async def test_post_topics_duplicate_returns_409(client):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        side_effect=asyncpg.UniqueViolationError("duplicate key")
    )
    pool = make_pool(conn)

    with patch("baseline_store.stores.get_pgvector_pool", AsyncMock(return_value=pool)):
        resp = await client.post("/topics", json={
            "topic_path": "climate_change",
            "display_name": "Climate Change",
        })

    assert resp.status_code == 409
    assert "already registered" in resp.json()["detail"]


# ── GET /topics ───────────────────────────────────────────────────────────────

async def test_get_topics_returns_list(client):
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[
        {"id": "aaa", "topic_path": "climate_change", "display_name": "Climate Change", "created_at": "2026-03-25T00:00:00+00:00"},
        {"id": "bbb", "topic_path": "climate_change.energy", "display_name": "Energy", "created_at": "2026-03-25T00:00:00+00:00"},
    ])
    pool = make_pool(conn)

    with patch("baseline_store.stores.get_pgvector_pool", AsyncMock(return_value=pool)):
        resp = await client.get("/topics")

    assert resp.status_code == 200
    assert len(resp.json()["topics"]) == 2
    assert resp.json()["topics"][0]["topic_path"] == "climate_change"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_baseline_store.py -v
```
Expected: `ImportError` or `404` — routes don't exist yet.

- [ ] **Step 3: Create `baseline_store/routes.py` with topic routes**

```python
# baseline_store/routes.py
from __future__ import annotations
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import asyncpg

from baseline_store.stores import get_pgvector_pool, get_embedder

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Pydantic models ──────────────────────────────────────────────────────────

class TopicCreate(BaseModel):
    topic_path: str
    display_name: str


# ── Topic endpoints ──────────────────────────────────────────────────────────

@router.post("/topics", status_code=201)
async def create_topic(body: TopicCreate):
    pool = await get_pgvector_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO baseline_topics (topic_path, display_name)
                VALUES ($1::ltree, $2)
                RETURNING id::text, topic_path::text, display_name, created_at::text
                """,
                body.topic_path, body.display_name,
            )
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail=f"Topic already registered: {body.topic_path}")
    return dict(row)


@router.get("/topics")
async def list_topics():
    pool = await get_pgvector_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id::text, topic_path::text, display_name, created_at::text FROM baseline_topics ORDER BY topic_path"
        )
    return {"topics": [dict(r) for r in rows]}
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_baseline_store.py -v
```
Expected: all 3 topic tests pass.

- [ ] **Step 5: Commit**

```bash
git add baseline_store/ tests/test_baseline_store.py
git commit -m "feat(baseline-store): add topic endpoints POST /topics and GET /topics"
```

---

## Task 3: Write version endpoint — `POST /baselines/{topic_path}/versions`

**Files:**
- Modify: `baseline_store/routes.py` (add version write route)
- Modify: `tests/test_baseline_store.py` (add version write tests)

This endpoint: (1) checks topic exists, (2) embeds `narrative`, (3) computes `MAX(version_number) + 1` inside a transaction, (4) inserts into `baseline_versions`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_baseline_store.py`:

```python
# ── POST /baselines/{topic_path}/versions ────────────────────────────────────

async def test_post_versions_happy_path(client):
    conn = AsyncMock()
    # First call: check topic exists
    conn.fetchrow = AsyncMock(side_effect=[
        {"topic_path": "us_iran_conflict"},          # topic exists
        {"max": None},                                # no existing versions → version 1
        {                                             # INSERT result
            "id": "cccccccc-0000-0000-0000-000000000001",
            "version_number": 1,
            "created_at": "2026-03-25T09:00:00+00:00",
        },
    ])
    pool = make_pool(conn)
    mock_embed = AsyncMock(return_value=[0.1] * 10)

    with patch("baseline_store.stores.get_pgvector_pool", AsyncMock(return_value=pool)), \
         patch("baseline_store.stores.get_embedder", return_value=mock_embed):
        resp = await client.post(
            "/baselines/us_iran_conflict/versions",
            json={
                "narrative": "Iran tensions elevated as of March 2026.",
                "citations": [{"article_id": "art1", "title": "Iran Update", "url": "https://example.com", "source": "Reuters", "published_at": "2026-03-25T00:00:00Z", "excerpt": "..."}],
            }
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body["version_number"] == 1
    assert "id" in body
    assert "created_at" in body
    # Embedder called once with the narrative text
    mock_embed.assert_called_once_with("Iran tensions elevated as of March 2026.")


async def test_post_versions_topic_not_registered(client):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)  # topic not found
    pool = make_pool(conn)

    with patch("baseline_store.stores.get_pgvector_pool", AsyncMock(return_value=pool)), \
         patch("baseline_store.stores.get_embedder", return_value=AsyncMock()):
        resp = await client.post(
            "/baselines/nonexistent/versions",
            json={"narrative": "test", "citations": []},
        )

    assert resp.status_code == 404
    assert "not registered" in resp.json()["detail"]


async def test_post_versions_conflict_returns_409(client):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[
        {"topic_path": "us_iran_conflict"},   # topic exists
        {"max": 3},                            # existing max version
        asyncpg.UniqueViolationError("conflict"),
    ])
    pool = make_pool(conn)
    mock_embed = AsyncMock(return_value=[0.1] * 10)

    with patch("baseline_store.stores.get_pgvector_pool", AsyncMock(return_value=pool)), \
         patch("baseline_store.stores.get_embedder", return_value=mock_embed):
        resp = await client.post(
            "/baselines/us_iran_conflict/versions",
            json={"narrative": "updated.", "citations": []},
        )

    assert resp.status_code == 409
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_baseline_store.py::test_post_versions_happy_path -v
pytest tests/test_baseline_store.py::test_post_versions_topic_not_registered -v
```
Expected: 404 from FastAPI — route doesn't exist yet.

- [ ] **Step 3: Add version write route to `routes.py`**

Add Pydantic model and route:

```python
import json
from typing import Any


class Citation(BaseModel):
    article_id: str
    title: str
    url: str
    source: str
    published_at: str
    excerpt: str = ""


class VersionCreate(BaseModel):
    narrative: str
    citations: list[Citation] = []


@router.post("/baselines/{topic_path}/versions", status_code=201)
async def create_version(topic_path: str, body: VersionCreate):
    pool = await get_pgvector_pool()
    embed = get_embedder()

    async with pool.acquire() as conn:
        # 1. Verify topic is registered
        topic = await conn.fetchrow(
            "SELECT topic_path FROM baseline_topics WHERE topic_path = $1::ltree",
            topic_path,
        )
        if topic is None:
            raise HTTPException(
                status_code=404,
                detail=f"Topic not registered: {topic_path} — call POST /topics first",
            )

        # 2. Compute next version number
        max_row = await conn.fetchrow(
            "SELECT MAX(version_number) AS max FROM baseline_versions WHERE topic_path = $1::ltree",
            topic_path,
        )
        next_version = (max_row["max"] or 0) + 1

    # 3. Embed narrative OUTSIDE the connection block — avoids holding a pool
    #    connection open during a potentially slow OpenAI network call.
    vector = await embed(body.narrative)

    # 4. Insert in a fresh connection
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO baseline_versions (topic_path, version_number, narrative, embedding, citations)
                VALUES ($1::ltree, $2, $3, $4::vector, $5::jsonb)
                RETURNING id::text, version_number, created_at::text
                """,
                topic_path, next_version, body.narrative,
                str(vector), json.dumps([c.model_dump() for c in body.citations]),
            )
        except asyncpg.UniqueViolationError:
            raise HTTPException(status_code=409, detail="Version conflict — retry with a fresh version number")

        return dict(row)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_baseline_store.py -v
```
Expected: all version tests pass; no regressions on topic tests.

- [ ] **Step 5: Commit**

```bash
git add baseline_store/routes.py tests/test_baseline_store.py
git commit -m "feat(baseline-store): add POST /baselines/{topic_path}/versions"
```

---

## Task 4: Write delta endpoint — `POST /baselines/{topic_path}/deltas`

**Files:**
- Modify: `baseline_store/routes.py`
- Modify: `tests/test_baseline_store.py`

This endpoint validates that `to_version` exists in `baseline_versions` before inserting.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_baseline_store.py`:

```python
# ── POST /baselines/{topic_path}/deltas ──────────────────────────────────────

async def test_post_deltas_happy_path(client):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[
        {"version_number": 8},   # to_version exists
        {                         # INSERT result
            "id": "dddddddd-0000-0000-0000-000000000001",
            "created_at": "2026-03-25T09:00:01+00:00",
        },
    ])
    pool = make_pool(conn)

    with patch("baseline_store.stores.get_pgvector_pool", AsyncMock(return_value=pool)):
        resp = await client.post(
            "/baselines/us_iran_conflict/deltas",
            json={
                "from_version": 7,
                "to_version": 8,
                "article_metadata": {"article_id": "art1", "title": "Iran Update", "url": "https://example.com", "source": "AP", "published_at": "2026-03-25T00:00:00Z"},
                "delta_summary": "Iran crossed 60% enrichment threshold.",
                "claims_added": ["Iran crossed 60% enrichment"],
                "claims_superseded": ["Iran below 60% enrichment"],
            }
        )

    assert resp.status_code == 201
    body = resp.json()
    assert "id" in body
    assert "created_at" in body


async def test_post_deltas_to_version_not_found(client):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)   # to_version does not exist
    pool = make_pool(conn)

    with patch("baseline_store.stores.get_pgvector_pool", AsyncMock(return_value=pool)):
        resp = await client.post(
            "/baselines/us_iran_conflict/deltas",
            json={
                "from_version": 7,
                "to_version": 99,
                "article_metadata": {},
                "delta_summary": "test",
                "claims_added": [],
                "claims_superseded": [],
            }
        )

    assert resp.status_code == 422
    assert "to_version" in resp.json()["detail"]
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_baseline_store.py::test_post_deltas_happy_path -v
```
Expected: 404 — route doesn't exist yet.

- [ ] **Step 3: Add delta route to `routes.py`**

```python
class DeltaCreate(BaseModel):
    from_version: int | None = None
    to_version: int
    article_metadata: dict[str, Any] = {}
    delta_summary: str
    claims_added: list[str] = []
    claims_superseded: list[str] = []


@router.post("/baselines/{topic_path}/deltas", status_code=201)
async def create_delta(topic_path: str, body: DeltaCreate):
    pool = await get_pgvector_pool()
    async with pool.acquire() as conn:
        # Validate to_version exists
        row = await conn.fetchrow(
            """
            SELECT version_number FROM baseline_versions
            WHERE topic_path = $1::ltree AND version_number = $2
            """,
            topic_path, body.to_version,
        )
        if row is None:
            raise HTTPException(
                status_code=422,
                detail=f"to_version {body.to_version} does not exist for topic: {topic_path} — write the version before the delta",
            )

        result = await conn.fetchrow(
            """
            INSERT INTO baseline_deltas
                (topic_path, from_version, to_version, article_metadata, delta_summary, claims_added, claims_superseded)
            VALUES ($1::ltree, $2, $3, $4::jsonb, $5, $6::jsonb, $7::jsonb)
            RETURNING id::text, created_at::text
            """,
            topic_path, body.from_version, body.to_version,
            json.dumps(body.article_metadata), body.delta_summary,
            json.dumps(body.claims_added), json.dumps(body.claims_superseded),
        )
    return dict(result)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_baseline_store.py -v
```
Expected: all delta tests pass; no regressions.

- [ ] **Step 5: Commit**

```bash
git add baseline_store/routes.py tests/test_baseline_store.py
git commit -m "feat(baseline-store): add POST /baselines/{topic_path}/deltas"
```

---

## Task 5: Read endpoints — `/current` and `/history`

> **STATUS:** Implementation complete. Committed as `4aa27bf`. Spec review ✅ passed. **Resumption point: code quality review pending.**

**Files:**
- Modify: `baseline_store/routes.py`
- Modify: `tests/test_baseline_store.py`

- [x] **Step 1: Write failing tests**

Append to `tests/test_baseline_store.py`:

```python
# ── GET /baselines/{topic_path}/current ──────────────────────────────────────

async def test_get_current_happy_path(client):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[
        {"topic_path": "us_iran_conflict"},   # topic exists
        {                                      # current version
            "topic_path": "us_iran_conflict",
            "version_number": 4,
            "narrative": "Iran tensions remain elevated.",
            "citations": '[{"article_id":"art1","title":"...","url":"...","source":"AP","published_at":"...","excerpt":"..."}]',
            "created_at": "2026-03-25T09:00:00+00:00",
        },
    ])
    pool = make_pool(conn)

    with patch("baseline_store.stores.get_pgvector_pool", AsyncMock(return_value=pool)):
        resp = await client.get("/baselines/us_iran_conflict/current")

    assert resp.status_code == 200
    body = resp.json()
    assert body["topic_path"] == "us_iran_conflict"
    assert body["version_number"] == 4
    assert body["narrative"] == "Iran tensions remain elevated."
    assert isinstance(body["citations"], list)


async def test_get_current_topic_not_registered(client):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)   # no topic row
    pool = make_pool(conn)

    with patch("baseline_store.stores.get_pgvector_pool", AsyncMock(return_value=pool)):
        resp = await client.get("/baselines/nonexistent/current")

    assert resp.status_code == 404
    assert "not registered" in resp.json()["detail"]


async def test_get_current_registered_but_no_versions(client):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[
        {"topic_path": "us_iran_conflict"},   # topic exists
        None,                                  # no version row
    ])
    pool = make_pool(conn)

    with patch("baseline_store.stores.get_pgvector_pool", AsyncMock(return_value=pool)):
        resp = await client.get("/baselines/us_iran_conflict/current")

    assert resp.status_code == 404
    assert "No versions" in resp.json()["detail"]


# ── GET /baselines/{topic_path}/history ──────────────────────────────────────

async def test_get_history_happy_path(client):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"topic_path": "us_iran_conflict"})
    conn.fetch = AsyncMock(side_effect=[
        [   # versions (newest first)
            {"version_number": 2, "narrative": "v2", "citations": "[]", "created_at": "2026-03-25T10:00:00+00:00"},
            {"version_number": 1, "narrative": "v1", "citations": "[]", "created_at": "2026-03-25T09:00:00+00:00"},
        ],
        [   # deltas
            {"from_version": 1, "to_version": 2, "delta_summary": "new info",
             "claims_added": "[]", "claims_superseded": "[]",
             "article_metadata": "{}", "created_at": "2026-03-25T10:00:00+00:00"},
        ],
    ])
    pool = make_pool(conn)

    with patch("baseline_store.stores.get_pgvector_pool", AsyncMock(return_value=pool)):
        resp = await client.get("/baselines/us_iran_conflict/history")

    assert resp.status_code == 200
    body = resp.json()
    assert body["topic_path"] == "us_iran_conflict"
    assert len(body["versions"]) == 2
    assert body["versions"][0]["version_number"] == 2   # newest first
    assert len(body["deltas"]) == 1


async def test_get_history_topic_not_registered(client):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    pool = make_pool(conn)

    with patch("baseline_store.stores.get_pgvector_pool", AsyncMock(return_value=pool)):
        resp = await client.get("/baselines/nonexistent/history")

    assert resp.status_code == 404


async def test_get_history_registered_no_versions(client):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"topic_path": "us_iran_conflict"})
    conn.fetch = AsyncMock(side_effect=[[], []])   # no versions, no deltas
    pool = make_pool(conn)

    with patch("baseline_store.stores.get_pgvector_pool", AsyncMock(return_value=pool)):
        resp = await client.get("/baselines/us_iran_conflict/history")

    assert resp.status_code == 200
    body = resp.json()
    assert body["versions"] == []
    assert body["deltas"] == []
```

- [x] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_baseline_store.py::test_get_current_happy_path -v
```
Expected: 404 — routes don't exist yet.

- [x] **Step 3: Add `/current` and `/history` routes to `routes.py`**

```python
@router.get("/baselines/{topic_path}/current")
async def get_current(topic_path: str):
    pool = await get_pgvector_pool()
    async with pool.acquire() as conn:
        topic = await conn.fetchrow(
            "SELECT topic_path FROM baseline_topics WHERE topic_path = $1::ltree",
            topic_path,
        )
        if topic is None:
            raise HTTPException(status_code=404, detail=f"Topic not registered: {topic_path}")

        row = await conn.fetchrow(
            """
            SELECT topic_path::text, version_number, narrative, citations::text, created_at::text
            FROM baseline_versions
            WHERE topic_path = $1::ltree
            ORDER BY version_number DESC
            LIMIT 1
            """,
            topic_path,
        )
    if row is None:
        raise HTTPException(status_code=404, detail=f"No versions written yet for topic: {topic_path}")

    result = dict(row)
    result["citations"] = json.loads(result["citations"])
    return result


@router.get("/baselines/{topic_path}/history")
async def get_history(topic_path: str):
    pool = await get_pgvector_pool()
    async with pool.acquire() as conn:
        topic = await conn.fetchrow(
            "SELECT topic_path FROM baseline_topics WHERE topic_path = $1::ltree",
            topic_path,
        )
        if topic is None:
            raise HTTPException(status_code=404, detail=f"Topic not registered: {topic_path}")

        versions = await conn.fetch(
            """
            SELECT version_number, narrative, citations::text, created_at::text
            FROM baseline_versions
            WHERE topic_path = $1::ltree
            ORDER BY version_number DESC
            """,
            topic_path,
        )
        deltas = await conn.fetch(
            """
            SELECT from_version, to_version, delta_summary,
                   claims_added::text, claims_superseded::text,
                   article_metadata::text, created_at::text
            FROM baseline_deltas
            WHERE topic_path = $1::ltree
            ORDER BY to_version DESC
            """,
            topic_path,
        )

    def parse_version(r):
        d = dict(r)
        d["citations"] = json.loads(d["citations"])
        return d

    def parse_delta(r):
        d = dict(r)
        d["claims_added"] = json.loads(d["claims_added"])
        d["claims_superseded"] = json.loads(d["claims_superseded"])
        d["article_metadata"] = json.loads(d["article_metadata"])
        return d

    return {
        "topic_path": topic_path,
        "versions": [parse_version(r) for r in versions],
        "deltas": [parse_delta(r) for r in deltas],
    }
```

- [x] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_baseline_store.py -v
```
Expected: all current + history tests pass; no regressions.

- [x] **Step 5: Commit**

```bash
git add baseline_store/routes.py tests/test_baseline_store.py
git commit -m "feat(baseline-store): add GET /current and GET /history endpoints"
```

---

## Task 6: Read endpoints — `/rollup` and `/similar`

**Files:**
- Modify: `baseline_store/routes.py`
- Modify: `tests/test_baseline_store.py`

**Critical FastAPI note:** `/baselines/similar` must be registered **before** `/baselines/{topic_path}/...` routes in `routes.py`. Otherwise FastAPI will try to match the literal string `"similar"` as a `topic_path` path parameter. Place `GET /baselines/similar` at the top of the baseline read routes section.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_baseline_store.py`:

```python
# ── GET /baselines/{topic_path}/rollup ───────────────────────────────────────

async def test_get_rollup_returns_descendants(client):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"topic_path": "climate_change"})
    conn.fetch = AsyncMock(return_value=[
        {
            "topic_path": "climate_change.energy",
            "version_number": 3,
            "narrative": "Energy baseline.",
            "citations": "[]",
            "created_at": "2026-03-25T09:00:00+00:00",
        },
    ])
    pool = make_pool(conn)

    with patch("baseline_store.stores.get_pgvector_pool", AsyncMock(return_value=pool)):
        resp = await client.get("/baselines/climate_change/rollup")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ancestor"] == "climate_change"
    assert len(body["descendants"]) == 1
    # Ancestor itself must not be in descendants
    assert all(d["topic_path"] != "climate_change" for d in body["descendants"])


async def test_get_rollup_no_descendants(client):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"topic_path": "climate_change"})
    conn.fetch = AsyncMock(return_value=[])
    pool = make_pool(conn)

    with patch("baseline_store.stores.get_pgvector_pool", AsyncMock(return_value=pool)):
        resp = await client.get("/baselines/climate_change/rollup")

    assert resp.status_code == 200
    assert resp.json()["descendants"] == []


async def test_get_rollup_topic_not_registered(client):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    pool = make_pool(conn)

    with patch("baseline_store.stores.get_pgvector_pool", AsyncMock(return_value=pool)):
        resp = await client.get("/baselines/nonexistent/rollup")

    assert resp.status_code == 404


# ── GET /baselines/similar ────────────────────────────────────────────────────

async def test_get_similar_returns_ranked_results(client):
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[
        {
            "topic_path": "us_iran_conflict",
            "version_number": 4,
            "narrative": "Iran tensions elevated.",
            "citations": "[]",
            "score": 0.91,
            "created_at": "2026-03-25T09:00:00+00:00",
        },
    ])
    pool = make_pool(conn)
    mock_embed = AsyncMock(return_value=[0.1] * 10)

    with patch("baseline_store.stores.get_pgvector_pool", AsyncMock(return_value=pool)), \
         patch("baseline_store.stores.get_embedder", return_value=mock_embed):
        resp = await client.get("/baselines/similar", params={"query": "Iran nuclear", "limit": 3})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["score"] == 0.91
    assert 0.0 <= body["results"][0]["score"] <= 1.0
    mock_embed.assert_called_once_with("Iran nuclear")


async def test_get_similar_embedder_called_once(client):
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    pool = make_pool(conn)
    mock_embed = AsyncMock(return_value=[0.1] * 10)

    with patch("baseline_store.stores.get_pgvector_pool", AsyncMock(return_value=pool)), \
         patch("baseline_store.stores.get_embedder", return_value=mock_embed):
        await client.get("/baselines/similar", params={"query": "test query"})

    mock_embed.assert_called_once_with("test query")
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_baseline_store.py::test_get_rollup_returns_descendants -v
pytest tests/test_baseline_store.py::test_get_similar_returns_ranked_results -v
```
Expected: 404 — routes don't exist yet.

- [ ] **Step 3: Add `/similar` and `/rollup` routes to `routes.py`**

**IMPORTANT:** By this point `routes.py` already has `/versions`, `/deltas`, `/current`, and `/history` handlers with `{topic_path}` path parameters. You must **insert** the `/similar` handler into the file **above all of those** — do NOT append it at the bottom. FastAPI matches routes in definition order; if `GET /baselines/similar` appears after `GET /baselines/{topic_path}/current`, FastAPI will treat "similar" as a `topic_path` value and route to the wrong handler.

Add `/similar` as the first route in the baseline read section of `routes.py` (before all `/{topic_path}/...` routes):

```python
# ── IMPORTANT: /similar must be defined before /{topic_path} routes ──────────

@router.get("/baselines/similar")
async def similar_baselines(query: str, limit: int = 5):
    pool = await get_pgvector_pool()
    embed = get_embedder()
    vector = await embed(query)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT topic_path::text, version_number, narrative, citations::text,
                   1 - (embedding <=> $1::vector) AS score,
                   created_at::text
            FROM baseline_versions
            ORDER BY embedding <=> $1::vector
            LIMIT $2
            """,
            str(vector), limit,
        )

    def parse(r):
        d = dict(r)
        d["citations"] = json.loads(d["citations"])
        return d

    return {"results": [parse(r) for r in rows]}
```

Then add `/rollup` (order relative to other `/{topic_path}` routes doesn't matter):

```python
@router.get("/baselines/{topic_path}/rollup")
async def get_rollup(topic_path: str):
    pool = await get_pgvector_pool()
    async with pool.acquire() as conn:
        topic = await conn.fetchrow(
            "SELECT topic_path FROM baseline_topics WHERE topic_path = $1::ltree",
            topic_path,
        )
        if topic is None:
            raise HTTPException(status_code=404, detail=f"Topic not registered: {topic_path}")

        # Fetch current version per descendant (topic_path strictly below ancestor)
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (v.topic_path)
                v.topic_path::text, v.version_number, v.narrative, v.citations::text, v.created_at::text
            FROM baseline_versions v
            WHERE v.topic_path <@ $1::ltree
              AND v.topic_path != $1::ltree
            ORDER BY v.topic_path, v.version_number DESC
            """,
            topic_path,
        )

    def parse(r):
        d = dict(r)
        d["citations"] = json.loads(d["citations"])
        return d

    return {"ancestor": topic_path, "descendants": [parse(r) for r in rows]}
```

- [ ] **Step 4: Run the full test suite**

```bash
pytest tests/test_baseline_store.py -v
```
Expected: all 15+ tests pass; no regressions.

- [ ] **Step 5: Commit**

```bash
git add baseline_store/routes.py tests/test_baseline_store.py
git commit -m "feat(baseline-store): add GET /rollup and GET /similar endpoints"
```

---

## Task 7: Finalise `server.py` and smoke test

**Files:**
- Modify: `baseline_store/server.py` (already mostly written in Task 2; verify completeness)
- Create: `baseline_store/README.md`

- [ ] **Step 1: Verify `server.py` is complete**

`server.py` should look exactly like the minimal version written in Task 2. Confirm it has:
- `create_app()` returning a `FastAPI` instance with `lifespan` and `router` included
- `app = create_app()` at module level
- `if __name__ == "__main__"` uvicorn runner reading `BASELINE_PORT`

- [ ] **Step 2: Run the full test suite one final time**

```bash
pytest tests/test_baseline_store.py -v
```
Expected: all tests green.

- [ ] **Step 3: Write `baseline_store/README.md`**

Create a README covering: purpose, how to run locally, all endpoints (method + path + one-line description), all env vars (copy from spec), and a note about the embedding dims migration warning.

- [ ] **Step 4: Commit**

```bash
git add baseline_store/server.py baseline_store/README.md
git commit -m "feat(baseline-store): finalise server.py and add README"
```

---

## Task 8: Deployment wiring

**Files:**
- Create: `Dockerfile.baseline-store`
- Modify: `docker-compose.yml`
- Modify: `run-local.sh`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Create `Dockerfile.baseline-store`**

```dockerfile
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY baseline_store/ baseline_store/

EXPOSE 8010
CMD ["python", "-m", "baseline_store.server"]
```

- [ ] **Step 2: Add `baseline-store` service to `docker-compose.yml`**

Add after the `memory-agent` service block:

```yaml
  # ── Baseline Store ────────────────────────────────────────────────────────
  baseline-store:
    build:
      context: .
      dockerfile: Dockerfile.baseline-store
    ports:
      - "8010:8010"
    environment:
      - LOG_LEVEL=INFO
      - BASELINE_PG_DSN=postgresql://mc:mc_password@postgres:5432/missioncontrol
      - BASELINE_EMBEDDING_MODEL=${BASELINE_EMBEDDING_MODEL}
      - BASELINE_EMBEDDING_DIMS=${BASELINE_EMBEDDING_DIMS}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - OPENAI_BASE_URL=${OPENAI_BASE_URL:-https://openrouter.ai/api/v1}
      - BASELINE_STORE_URL=http://baseline-store:8010
    env_file: ".env"
    networks:
      - mc-net
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import httpx; httpx.get('http://localhost:8010/topics').raise_for_status()"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 15s
```

- [ ] **Step 3: Add baseline-store to `run-local.sh`**

After the Memory Agent block and before the Dashboard block, add:

```bash
# ── Baseline Store ────────────────────────────────────────────────────────────
BASELINE_PORT=8010

echo "[11/12] Starting Baseline Store on port $BASELINE_PORT..."
BASELINE_PG_DSN="${BASELINE_PG_DSN:-postgresql://mc:mc_password@localhost:5432/missioncontrol}" \
BASELINE_EMBEDDING_MODEL="${BASELINE_EMBEDDING_MODEL}" \
BASELINE_EMBEDDING_DIMS="${BASELINE_EMBEDDING_DIMS}" \
BASELINE_STORE_URL="http://127.0.0.1:$BASELINE_PORT" \
  python -m baseline_store.server &
PIDS+=($!)
wait_for_port $BASELINE_PORT "Baseline Store"
```

Update the Dashboard step number from `[11/11]` to `[12/12]`, update the totals in step labels throughout (the script uses `[1/10]`, `[2/10]` etc — update `[N/N]` to reflect the new total), and add Baseline Store to the summary block at the bottom:

```bash
echo "  Baseline Store: http://localhost:$BASELINE_PORT"
```

- [ ] **Step 4: Update `CLAUDE.md`**

In the agents table, add a new row:

```markdown
| Baseline Store (`baseline_store/`) | 8010 | N/A (plain FastAPI) | Deterministic storage/retrieval layer for topic baselines: versioned narratives with ltree hierarchy, pgvector semantic search, and delta log. Not an A2A agent. |
```

In the Per-Agent URL Variables table, add:

```markdown
| `BASELINE_STORE_URL` | Baseline Store | `http://localhost:8010` |
```

In the Shared Agent Variables table (or a new Baseline Store section), add:

```markdown
| `BASELINE_PG_DSN` | — | pgvector + ltree Postgres DSN (baseline store only, required) |
| `BASELINE_EMBEDDING_MODEL` | — | Embedding model name (baseline store only, required) |
| `BASELINE_EMBEDDING_DIMS` | — | Vector dims — must match model, no default (baseline store only, required) |
```

Also add to the run command examples:

```markdown
python -m baseline_store.server
```

- [ ] **Step 5: Final test run**

```bash
pytest tests/test_baseline_store.py -v
```
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile.baseline-store docker-compose.yml run-local.sh CLAUDE.md
git commit -m "feat(baseline-store): add Dockerfile, docker-compose, run-local, CLAUDE.md"
```
