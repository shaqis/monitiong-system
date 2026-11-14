# Uptime Monitor

Self-hosted uptime monitoring for URLs. The stack is a FastAPI backend with PostgreSQL and a Next.js frontend.

## Requirements

- Docker with the Compose plugin

## Setup

Copy the environment template and set the admin password and JWT secret.

```bash
cp .env.example .env
```

Set `FIRST_ADMIN_PASSWORD` and `JWT_SECRET` in `.env`, then start the stack. The `migrate` service applies the schema before the API starts. `FIRST_ADMIN_PASSWORD` must be at least 12 characters and `JWT_SECRET` at least 32 bytes. Startup rejects the documented placeholder values and does not echo the secret in the error.

```bash
docker compose up -d --build
```

Open the dashboard at http://localhost:3000 and sign in with `FIRST_ADMIN_EMAIL` and `FIRST_ADMIN_PASSWORD`. Swagger UI is at http://localhost:8000/docs. The OpenAPI document is at http://localhost:8000/openapi.json. PostgreSQL listens on localhost:5432. If a port is taken, change `FRONTEND_PORT`, `BACKEND_PORT`, or `POSTGRES_PORT` in `.env`.

If you change `FRONTEND_PORT`, set `CORS_ORIGINS` to exactly match the new browser origin, for example `CORS_ORIGINS=["http://localhost:3001"]`. The Next.js server reaches the API through the Compose network with `API_INTERNAL_URL`; the browser uses `NEXT_PUBLIC_API_URL`. The frontend and API must share the cookie host, because the server forwards the auth cookie.

If you change `POSTGRES_USER`, `POSTGRES_PASSWORD`, or `POSTGRES_DB` after the first start, run `docker compose down -v` before starting again. The database volume keeps the old credentials.

## One backend process

Run exactly one `backend` service. The scheduler and the per-monitor check locks are process-local, so a second backend replica would probe every monitor twice. Docker Compose starts one backend process; scale PostgreSQL, not the API replicas.

## Roles

- `admin`: manages users and creates, edits, pauses, deletes, and checks URLs.
- `viewer`: reads the dashboard, URL directory, URL details, and incidents. The UI hides mutation controls and redirects `/users` to `/dashboard`; the API also returns `403` for admin-only calls.

## Security notes

Logout clears the auth cookie only. A bearer token stays valid until it expires. Resetting a user's password invalidates every token issued before the reset.

Tokens minted before token versioning, which carry no `ver` claim, stay valid for a user who never resets a password. To force every session to sign in again, run `UPDATE users SET token_version = token_version + 1;`.

`COOKIE_SECURE` defaults to `true`. Set it to `false` only for local HTTP development, as `.env.example` does. Startup rejects `false` when any `CORS_ORIGINS` entry is not a loopback origin, so a deployment that copies the template to a real domain fails instead of issuing a plaintext cookie.

User creation and password reset require at least 12 characters, the same floor as `FIRST_ADMIN_PASSWORD`.

Monitor creation is admin-only. The prober follows redirects and does not block private address ranges, so an admin can point a monitor at an internal service or a public URL that redirects to one. Treat admin access as trust.

Pausing a monitor closes its open incident at the pause time. Resuming starts a fresh check cycle, and a new failure opens a new incident.

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

The Phase 5 end-to-end verification record, with screenshots and database comparisons, is in [`docs/verification/phase-5.md`](docs/verification/phase-5.md).

## Layout

```text
backend/     FastAPI application, worker, and migrations
frontend/    Next.js App Router dashboard
```

Implementation follows the phases in `PRD.md` and the matching GitHub issues.
