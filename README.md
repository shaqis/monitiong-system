# Uptime Monitor

Self-hosted uptime monitoring for URLs. The stack is a FastAPI backend with PostgreSQL and, from Phase 4, a Next.js frontend.

## Requirements

- Docker with the Compose plugin
- Ports 8000 and 5432 free

## Setup

Copy the environment template, then start the database and the API.

```bash
cp .env.example .env
docker compose up -d --build
```

The API serves its OpenAPI document at http://localhost:8000/docs. PostgreSQL listens on localhost:5432.

## Verify

```bash
docker compose config
docker compose ps
docker compose run --rm backend python -c "import fastapi, sqlalchemy, alembic, httpx, apscheduler"
docker compose run --rm backend ruff check .
docker compose run --rm backend pytest -v
```

## Layout

```text
backend/     FastAPI application, worker, and migrations
frontend/    Next.js dashboard (Phase 4)
```

Implementation follows the phases in `PRD.md` and the matching GitHub issues.
