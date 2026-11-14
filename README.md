# Uptime Monitor

Self-hosted uptime monitoring for URLs. The stack is a FastAPI backend with PostgreSQL and a Next.js frontend.

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

Open the dashboard at http://localhost:3000 and sign in with `FIRST_ADMIN_EMAIL` and `FIRST_ADMIN_PASSWORD`. Swagger UI is at http://localhost:8000/docs. The OpenAPI document is at http://localhost:8000/openapi.json. PostgreSQL listens on localhost:5432. If a port is taken, change `FRONTEND_PORT`, `BACKEND_PORT`, or `POSTGRES_PORT` in `.env`.

If you change `FRONTEND_PORT`, set `CORS_ORIGINS` to match the new browser origin, for example `CORS_ORIGINS=["http://localhost:3001"]`. The Next.js server reaches the API through the Compose network with `API_INTERNAL_URL`; the browser uses `NEXT_PUBLIC_API_URL`.

If you change `POSTGRES_USER`, `POSTGRES_PASSWORD`, or `POSTGRES_DB` after the first start, run `docker compose down -v` before starting again. The database volume keeps the old credentials.

## One backend process

Run exactly one `backend` service. The scheduler and the per-monitor check locks are process-local, so a second backend replica would probe every monitor twice. Docker Compose starts one backend process; scale PostgreSQL, not the API replicas.

## Roles

- `admin`: manages users and creates, edits, pauses, deletes, and checks URLs.
- `viewer`: reads the dashboard, URL directory, URL details, and incidents. The UI hides mutation controls and redirects `/users` to `/dashboard`; the API also returns `403` for admin-only calls.

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

Frontend checks:

```bash
docker compose exec frontend npx tsc --noEmit
docker compose exec frontend npm run lint
docker compose exec frontend npm run build
```

## Layout

```text
backend/     FastAPI application, worker, and migrations
frontend/    Next.js App Router dashboard
```

Implementation follows the phases in `PRD.md` and the matching GitHub issues.
