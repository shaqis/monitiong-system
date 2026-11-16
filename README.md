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

## Email notifications

Incident open and recovery can send email through SMTP, Brevo, Mailgun, or Mailtrap. Configuration is environment-only; there is no settings page and no database table for credentials. Set `EMAIL_NOTIFICATIONS_ENABLED=true`, choose `EMAIL_PROVIDER`, fill that provider's block, and list `NOTIFICATION_RECIPIENTS` as a JSON list. Empty optional values count as unset. The first failed check stays silent; an email goes out only when the second consecutive failure opens an incident, and again when a successful check resolves it.

Verify credentials before enabling alerts with the admin-only test endpoint. Sign in, keep the cookie, then call it:

```bash
curl -sS -c /tmp/uptime-cookies -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"<FIRST_ADMIN_PASSWORD>"}'
curl -sS -o /dev/null -w '%{http_code}\n' -b /tmp/uptime-cookies \
  -X POST http://localhost:8000/api/v1/notifications/test
rm -f /tmp/uptime-cookies
```

`204` means the provider accepted the message, `503` means the transport configuration is incomplete, and `502` means the provider rejected or could not be reached. Delivery is best effort. A failed send is logged and does not change the check, the monitor status, or the incident. There is no retry queue.

## Security notes

Logout clears the auth cookie only. A bearer token stays valid until it expires. Resetting a user's password invalidates every token issued before the reset.

Tokens minted before token versioning, which carry no `ver` claim, stay valid for a user who never resets a password. To force every session to sign in again, run `UPDATE users SET token_version = token_version + 1;`.

`COOKIE_SECURE` defaults to `true`. Set it to `false` only for local HTTP development, as `.env.example` does. Startup rejects `false` unless `CORS_ORIGINS` is non-empty and every entry is a loopback origin, so a plaintext cookie is limited to a loopback deployment. A copied template that names a real domain fails to start instead of issuing a plaintext cookie.

User creation and password reset require at least 12 characters, the same floor as `FIRST_ADMIN_PASSWORD`.

`FIRST_ADMIN_PASSWORD` is validated at startup even when the users table already has rows, because settings load before the seed decides to skip. An existing install whose `.env` still holds a bootstrap password under 12 characters must replace that value before upgrading. The seed does not change an existing admin's password, so reset the password through the admin API if the old value should change as well.

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
