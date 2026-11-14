# Uptime Monitor

Self-hosted uptime monitoring for URLs. The stack is a FastAPI backend with PostgreSQL and, from Phase 4, a Next.js frontend.

## Requirements

- Docker with the Compose plugin

## Setup

Copy the environment template and set the admin password and JWT secret.

```bash
cp .env.example .env
```

Set `FIRST_ADMIN_PASSWORD` and `JWT_SECRET` in `.env`, then start the stack. The `migrate` service applies the schema before the API starts.

```bash
docker compose up -d --build
```

Swagger UI is at http://localhost:8000/docs. The OpenAPI document is at http://localhost:8000/openapi.json. PostgreSQL listens on localhost:5432. Both ports bind to localhost only. If a port is taken, change `BACKEND_PORT` or `POSTGRES_PORT` in `.env`.

If you change `POSTGRES_USER`, `POSTGRES_PASSWORD`, or `POSTGRES_DB` after the first start, run `docker compose down -v` before starting again. The database volume keeps the old credentials.

## Verify

```bash
docker compose config
docker compose ps
docker compose exec backend alembic current
docker compose exec backend alembic check
docker compose exec backend ruff check .
docker compose exec backend ruff format --check .
docker compose exec backend pytest -v
```

## Layout

```text
backend/     FastAPI application, worker, and migrations
frontend/    Next.js dashboard (Phase 4)
```

Implementation follows the phases in `PRD.md` and the matching GitHub issues.
