---
name: baseline-store implementation progress
description: Current progress on the baseline store service implementation — where to resume
type: project
---

**Status: COMPLETE** — merged to `main` on 2026-03-25.

All 8 tasks done, 19 tests passing. The baseline store is a plain FastAPI service on port 8010 with:
- 8 REST endpoints (topics, versions, deltas, current, history, rollup, similar)
- asyncpg + ltree + pgvector storage
- Dockerfile, docker-compose service, run-local.sh entry, CLAUDE.md docs

No further work required on this feature.
