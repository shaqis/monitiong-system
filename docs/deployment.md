# How to deploy to production with Docker

This guide puts the stack on one Linux server. Caddy terminates TLS on ports 80 and 443 and routes each request to the API or the frontend. PostgreSQL and the application ports stay private to the Compose network.

You need a server you control, sudo access, and a DNS record you can point at it.

## What the deployment must respect

Three properties of this codebase decide the shape of every file below. Read them first.

**Run exactly one backend process.** The scheduler and the per-monitor check locks are process-local (`backend/app/worker/scheduler.py`, and the note in `README.md`). A second replica probes every monitor twice and opens duplicate incidents. Docker Compose starts one backend by default. Keep it that way: no `--scale backend=2` and no `--workers` above 1.

**Serve the UI and the API from one host.** The login response sets `access_token` with `path=/` and no `Domain` attribute (`backend/app/api/v1/auth.py`). A cookie without `Domain` belongs to the host that set it. Next.js server components forward `cookies()` to the API (`frontend/src/lib/server-session.ts`), so the page host must be the cookie host. Route the UI at `/` and the API at `/api/` on one domain. Two subdomains do not work, because the frontend host never receives the API host's cookie.

**`NEXT_PUBLIC_API_URL` is compiled into the browser bundle.** `next build` inlines it. If you change that value, rebuild the frontend image. Restarting the container is not enough.

## Topology

```text
Browser
  |
  |  https://monitor.example.com
  v
Caddy  :80 :443
  |-- /api/*  -> backend:8000   one uvicorn worker, runs the scheduler
  |-- /*      -> frontend:3000  next start, server components call the API
  |
backend -> db:5432 PostgreSQL, no published port
```

## Step 1: Prepare the server

Install Docker Engine with the Compose plugin from your distribution's package manager. Then check the version:

```bash
docker compose version
```

The server needs a DNS `A` record (and an `AAAA` record if it has IPv6) pointing at its IP address before you start Caddy. Caddy requests the certificate on first start and fails the challenge without correct DNS.

If the server runs `ufw`, open the web ports:

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
```

Port 80 must stay reachable. Caddy uses it for the ACME challenge and for the redirect to HTTPS.

## Step 2: Get the code

```bash
sudo mkdir -p /srv
sudo chown "$USER":"$USER" /srv
git clone <repository-url> /srv/uptime-monitor
cd /srv/uptime-monitor
```

## Step 3: Create the production Compose file

Create `docker-compose.prod.yml` at the repository root and commit it. The development file `docker-compose.yml` is not a production stack: it bind-mounts the source, runs `uvicorn --reload`, runs `npm run dev`, and publishes three ports on the host.

```yaml
name: uptime-monitor

x-logging: &default-logging
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"

services:
  db:
    image: postgres:16-alpine
    restart: unless-stopped
    logging: *default-logging
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-uptime}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}
      POSTGRES_DB: ${POSTGRES_DB:-uptime}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 5s
      timeout: 5s
      retries: 10

  migrate:
    build:
      context: ./backend
    restart: "no"
    logging: *default-logging
    environment:
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER:-uptime}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB:-uptime}
    depends_on:
      db:
        condition: service_healthy
    command: alembic upgrade head

  backend:
    build:
      context: ./backend
    restart: unless-stopped
    logging: *default-logging
    environment:
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER:-uptime}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB:-uptime}
      FIRST_ADMIN_EMAIL: ${FIRST_ADMIN_EMAIL:-admin@example.com}
      FIRST_ADMIN_PASSWORD: ${FIRST_ADMIN_PASSWORD:?set FIRST_ADMIN_PASSWORD in .env}
      FIRST_ADMIN_NAME: ${FIRST_ADMIN_NAME:-Admin}
      CORS_ORIGINS: ${CORS_ORIGINS:?set CORS_ORIGINS in .env}
      JWT_SECRET: ${JWT_SECRET:?set JWT_SECRET in .env}
      JWT_ALGORITHM: ${JWT_ALGORITHM:-HS256}
      JWT_EXPIRE_MINUTES: ${JWT_EXPIRE_MINUTES:-60}
      AUTH_COOKIE_NAME: ${AUTH_COOKIE_NAME:-access_token}
      COOKIE_SECURE: ${COOKIE_SECURE:-true}
      SCHEDULER_ENABLED: ${SCHEDULER_ENABLED:-true}
      SCHEDULER_POLL_SECONDS: ${SCHEDULER_POLL_SECONDS:-10}
      SCHEDULER_RETRY_SECONDS: ${SCHEDULER_RETRY_SECONDS:-5}
      MAX_CONCURRENT_CHECKS: ${MAX_CONCURRENT_CHECKS:-20}
      PROBE_USER_AGENT: ${PROBE_USER_AGENT:-UptimeMonitor/1.0}
      SSL_INSPECT_TIMEOUT_SECONDS: ${SSL_INSPECT_TIMEOUT_SECONDS:-5}
      DB_POOL_SIZE: ${DB_POOL_SIZE:-20}
      DB_MAX_OVERFLOW: ${DB_MAX_OVERFLOW:-10}
      EMAIL_NOTIFICATIONS_ENABLED: ${EMAIL_NOTIFICATIONS_ENABLED:-false}
      EMAIL_PROVIDER: ${EMAIL_PROVIDER:-smtp}
      EMAIL_FROM_ADDRESS: ${EMAIL_FROM_ADDRESS:-}
      EMAIL_FROM_NAME: ${EMAIL_FROM_NAME:-Uptime Monitor}
      NOTIFICATION_RECIPIENTS: ${NOTIFICATION_RECIPIENTS:-[]}
      NOTIFICATION_TIMEOUT_SECONDS: ${NOTIFICATION_TIMEOUT_SECONDS:-10}
      SMTP_HOST: ${SMTP_HOST:-}
      SMTP_PORT: ${SMTP_PORT:-587}
      SMTP_USERNAME: ${SMTP_USERNAME:-}
      SMTP_PASSWORD: ${SMTP_PASSWORD:-}
      SMTP_STARTTLS: ${SMTP_STARTTLS:-true}
      SMTP_SSL: ${SMTP_SSL:-false}
      BREVO_API_KEY: ${BREVO_API_KEY:-}
      MAILGUN_API_KEY: ${MAILGUN_API_KEY:-}
      MAILGUN_DOMAIN: ${MAILGUN_DOMAIN:-}
      MAILGUN_API_URL: ${MAILGUN_API_URL:-https://api.mailgun.net/v3}
      MAILTRAP_API_TOKEN: ${MAILTRAP_API_TOKEN:-}
    depends_on:
      db:
        condition: service_healthy
      migrate:
        condition: service_completed_successfully
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/openapi.json', timeout=2)"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile.prod
      args:
        NEXT_PUBLIC_API_URL: ${NEXT_PUBLIC_API_URL:?set NEXT_PUBLIC_API_URL in .env}
    restart: unless-stopped
    logging: *default-logging
    environment:
      API_INTERNAL_URL: ${API_INTERNAL_URL:-http://backend:8000/api/v1}
      NEXT_TELEMETRY_DISABLED: "1"
    depends_on:
      backend:
        condition: service_healthy
    healthcheck:
      test:
        [
          "CMD",
          "node",
          "-e",
          "fetch('http://127.0.0.1:3000/login').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))",
        ]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 40s

  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    logging: *default-logging
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"
    environment:
      DOMAIN: ${DOMAIN:?set DOMAIN in .env}
    volumes:
      - ./deploy/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      backend:
        condition: service_healthy
      frontend:
        condition: service_healthy

volumes:
  pgdata:
  caddy_data:
  caddy_config:
```

Only Caddy publishes ports. The database and the application services are reachable by name on the Compose network and unreachable from outside the host.

`migrate` applies `alembic upgrade head` on every `up`, then exits. The backend waits for it to finish, so a schema change ships with the same deploy as the code.

## Step 4: Create the frontend production image

`frontend/Dockerfile` runs `npm run dev`, which is the development server. Create `frontend/Dockerfile.prod` and commit it.

```dockerfile
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY --from=builder --chown=node:node /app/.next ./.next
COPY --from=builder --chown=node:node /app/next.config.mjs ./next.config.mjs
RUN chown -R node:node /app
USER node
EXPOSE 3000
CMD ["npm", "run", "start"]
```

The builder stage receives `NEXT_PUBLIC_API_URL` because the value is inlined at build time. The runner stage installs production dependencies only and starts `next start`. It runs as the `node` user.

The production build needs no running API. Every route is dynamic and fetches at request time, so the image builds while the backend is down or not yet created.

If the build is killed for running out of memory, add swap to the server or build the image on another machine and push it to a registry.

## Step 5: Create the reverse proxy configuration

Create `deploy/Caddyfile` and commit it.

```caddyfile
{$DOMAIN} {
	encode zstd gzip

	handle /api/* {
		reverse_proxy backend:8000
	}

	handle {
		reverse_proxy frontend:3000
	}
}
```

Caddy obtains and renews the certificate for `{$DOMAIN}` from Let's Encrypt, and redirects HTTP to HTTPS. It needs a resolvable domain, which is why the DNS record comes first.

`handle /api/*` forwards the request with its path intact, so `https://monitor.example.com/api/v1/monitors` reaches `http://backend:8000/api/v1/monitors`. The second block catches everything else and reaches the frontend. The two `handle` blocks are mutually exclusive, so no request reaches both services.

Because only `/api/*` is routed to the API, the API docs at `/docs` and `/openapi.json` are not reachable from the internet. They stay reachable inside the network, which is what the backend healthcheck uses.

## Step 6: Write the environment file

Create `.env` from the template, then add `DOMAIN`, which the template does not include, and replace every value in angle brackets.

```bash
cp .env.example .env
openssl rand -hex 24   # POSTGRES_PASSWORD
openssl rand -hex 32   # JWT_SECRET
chmod 600 .env
```

```dotenv
# Public hostname. Caddy issues the certificate for this name.
DOMAIN=monitor.example.com

# PostgreSQL. The password is embedded in DATABASE_URL, so keep it URL-safe.
POSTGRES_USER=uptime
POSTGRES_PASSWORD=<hex from openssl rand -hex 24>
POSTGRES_DB=uptime

# Backend
JWT_SECRET=<hex from openssl rand -hex 32>
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60
AUTH_COOKIE_NAME=access_token
COOKIE_SECURE=true
CORS_ORIGINS=["https://monitor.example.com"]

FIRST_ADMIN_EMAIL=you@example.com
FIRST_ADMIN_PASSWORD=<at least 12 characters>
FIRST_ADMIN_NAME=Admin

# Frontend
NEXT_PUBLIC_API_URL=https://monitor.example.com/api/v1
API_INTERNAL_URL=http://backend:8000/api/v1

# Worker and connection pool
SCHEDULER_ENABLED=true
SCHEDULER_POLL_SECONDS=10
SCHEDULER_RETRY_SECONDS=5
MAX_CONCURRENT_CHECKS=20
PROBE_USER_AGENT=UptimeMonitor/1.0
SSL_INSPECT_TIMEOUT_SECONDS=5
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10

# Email notifications (optional)
EMAIL_NOTIFICATIONS_ENABLED=false
EMAIL_PROVIDER=smtp
EMAIL_FROM_ADDRESS=
EMAIL_FROM_NAME=Uptime Monitor
NOTIFICATION_RECIPIENTS=[]
NOTIFICATION_TIMEOUT_SECONDS=10
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_STARTTLS=true
SMTP_SSL=false
BREVO_API_KEY=
MAILGUN_API_KEY=
MAILGUN_DOMAIN=
MAILGUN_API_URL=https://api.mailgun.net/v3
MAILTRAP_API_TOKEN=
```

The application validates these values at startup and exits on a bad one.

- `JWT_SECRET` must be at least 32 bytes and must not be a documented placeholder.
- `FIRST_ADMIN_PASSWORD` must be 12 to 72 bytes and must not be a documented placeholder. The value is validated on every start, even after the first admin exists, so keep it valid across upgrades. The seed creates the admin only while the `users` table is empty.
- `COOKIE_SECURE` must be `true` unless `CORS_ORIGINS` lists only loopback hosts. A real domain with `COOKIE_SECURE=false` stops the API at startup instead of issuing a plaintext cookie.
- `CORS_ORIGINS` must list the exact browser origin, scheme included, and must not contain `*`.
- `DB_POOL_SIZE + DB_MAX_OVERFLOW` must be at least `MAX_CONCURRENT_CHECKS`, because each concurrent probe holds a connection.
- Use hex for `POSTGRES_PASSWORD`. Compose builds `DATABASE_URL` from it, and reserved characters break the URL.
- `NEXT_PUBLIC_API_URL` must be the same host as `DOMAIN`, with the `/api/v1` path. A different host breaks the session cookie.
- `NOTIFICATION_RECIPIENTS` is a JSON list of addresses. It is required when `EMAIL_NOTIFICATIONS_ENABLED=true`.
- Email notifications use only the block for `EMAIL_PROVIDER`. Empty values count as unset. With `smtp`, set `SMTP_HOST` and either both `SMTP_USERNAME` and `SMTP_PASSWORD` or neither. StartTLS (`SMTP_STARTTLS=true`, port 587) and implicit TLS (`SMTP_SSL=true`, port 465) are mutually exclusive.
- `POSTGRES_PORT`, `BACKEND_PORT`, and `FRONTEND_PORT` from the template are unused here. The production file publishes no application ports.
- Keep `.env` out of Git. The repository `.gitignore` already excludes it.

## Step 7: Build and start

Check the configuration before you build. Compose reports missing variables and YAML errors here.

```bash
docker compose -f docker-compose.prod.yml config --quiet
```

No output means the file is valid. Do not paste the output of `docker compose config` into a ticket or chat, because it prints resolved secrets.

Start the stack:

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs migrate
```

The first build takes a few minutes. When it finishes, `ps` shows `db`, `backend`, `frontend`, and `caddy` as `running` with `healthy` state, and `migrate` as `exited (0)`. The `migrate` log lists each revision it applied. It prints nothing when the schema is already current.

If `db` reports unhealthy, the Postgres password in `.env` does not match the one inside the existing volume. See [Troubleshooting](#troubleshooting).

## Step 8: Verify the deployment

Run these checks in order. Each one proves a layer of the deployment.

1. The UI serves over HTTPS.

   ```bash
   curl -sS -o /dev/null -w '%{http_code}\n' https://monitor.example.com/login
   ```

   Expected: `200`.

2. The proxy routes the API, and unauthenticated calls are rejected.

   ```bash
   curl -sS -o /dev/null -w '%{http_code}\n' https://monitor.example.com/api/v1/auth/me
   ```

   Expected: `401`.

3. Login sets a secure, HTTP-only cookie on the public host.

   ```bash
   curl -sS -i -X POST https://monitor.example.com/api/v1/auth/login \
     -H 'Content-Type: application/json' \
     -d '{"email":"you@example.com","password":"<FIRST_ADMIN_PASSWORD>"}' \
     | grep -i '^set-cookie'
   ```

   Expected: a `set-cookie` header for `access_token` that contains `HttpOnly`, `Secure`, `SameSite=Lax`, and `Path=/`. This command leaves the admin password in the shell history, so clear that history after the check.

4. The database is at the latest revision.

   ```bash
   docker compose -f docker-compose.prod.yml exec backend alembic current
   ```

   Expected: one revision hash followed by `(head)`.

5. Exactly one backend process runs.

   ```bash
   docker compose -f docker-compose.prod.yml ps backend
   ```

   Expected: one container. More than one means duplicate probes.

6. Email notifications reach the provider.

   ```bash
   curl -sS -c /tmp/uptime-cookies -X POST https://monitor.example.com/api/v1/auth/login \
     -H 'Content-Type: application/json' \
     -d '{"email":"you@example.com","password":"<FIRST_ADMIN_PASSWORD>"}'
   curl -sS -o /dev/null -w '%{http_code}\n' -b /tmp/uptime-cookies \
     -X POST https://monitor.example.com/api/v1/notifications/test
   rm -f /tmp/uptime-cookies
   ```

   Expected: `204` when the provider accepted the message, `503` when the transport block is incomplete, and `502` when the provider rejected or could not be reached. The test endpoint works while `EMAIL_NOTIFICATIONS_ENABLED=false`, so credentials can be verified before alerts are turned on. Clear the shell history after the login command.

Then open `https://monitor.example.com` in a browser, sign in with the admin credentials, and add a monitor. Wait one poll interval and confirm the dashboard shows a check.

## Step 9: Back up the database

The database volume lives on the server and nothing else copies it. Take a dump before every upgrade and on a schedule.

Create a directory the deploy user can write:

```bash
sudo install -d -o "$USER" -g "$(id -gn)" /var/backups/uptime
```

Take a dump:

```bash
docker compose -f docker-compose.prod.yml exec -T db pg_dump -U uptime -Fc uptime > /var/backups/uptime/uptime-$(date +%F).dump
```

A daily cron entry. Run it as a user in the `docker` group.

```cron
0 3 * * * cd /srv/uptime-monitor && docker compose -f docker-compose.prod.yml exec -T db pg_dump -U uptime -Fc uptime > /var/backups/uptime/uptime-$(date +\%F).dump
```

Copy the dumps off the server. A dump on the same disk is lost with the disk or the server.

Restore a dump:

```bash
docker compose -f docker-compose.prod.yml stop backend
docker compose -f docker-compose.prod.yml exec -T db pg_restore -U uptime -d uptime --clean --if-exists < /var/backups/uptime/uptime-2026-11-15.dump
docker compose -f docker-compose.prod.yml start backend
```

Stop the backend first. A running scheduler writes check rows while the restore runs.

## Step 10: Update the running stack

Take a dump first. Then pull, rebuild, and replace the containers.

```bash
docker compose -f docker-compose.prod.yml exec -T db pg_dump -U uptime -Fc uptime > /var/backups/uptime/uptime-before-update.dump
git pull
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
```

Compose builds the new images, runs `migrate` against the existing database, then recreates `backend`, `frontend`, and `caddy`. The database volume and the Caddy certificates survive.

To roll back, check out the previous revision and rebuild:

```bash
git checkout <previous-commit>
docker compose -f docker-compose.prod.yml up -d --build
```

A migration that already ran may not reverse cleanly. If the old code cannot run against the migrated schema, restore the dump from before the update instead of downgrading.

## Troubleshooting

**Caddy logs an ACME failure or serves a self-signed certificate.** The DNS record does not point at this server, port 80 is blocked, or another process holds port 80. Check with `docker compose -f docker-compose.prod.yml logs caddy` and `dig +short monitor.example.com`.

**Caddy returns 502.** The frontend or the backend is not healthy. Read `docker compose -f docker-compose.prod.yml logs --tail=100 backend` and `docker compose -f docker-compose.prod.yml logs --tail=100 frontend`. The proxy only starts after both pass their healthchecks.

**Login succeeds, then every page redirects to `/login`.** The browser is not sending the cookie back to the frontend. Check that `NEXT_PUBLIC_API_URL` names the same host as `DOMAIN`, that `CORS_ORIGINS` matches the browser origin exactly including the scheme, and that the browser uses `https://`. Rebuild the frontend after any change to `NEXT_PUBLIC_API_URL`.

**The backend exits with `JWT_SECRET must be at least 32 bytes`, `FIRST_ADMIN_PASSWORD must be at least 12 characters`, or a placeholder error.** Fix the value in `.env` and recreate the container with `docker compose -f docker-compose.prod.yml up -d backend`. Environment changes apply only on recreate.

**The backend exits with `DB_POOL_SIZE + DB_MAX_OVERFLOW must be at least MAX_CONCURRENT_CHECKS`.** Raise `DB_POOL_SIZE` or lower `MAX_CONCURRENT_CHECKS`.

**Every monitor gets two checks and duplicate incidents.** More than one backend process is running. `docker compose -f docker-compose.prod.yml ps` should list one. Remove any `--scale backend` flag and keep `--workers 1`.

**`db` is unhealthy after you changed the Postgres password.** The volume keeps the old credentials. Put the old password back in `.env`. If you no longer have it, restore a dump into a fresh volume. `docker compose down -v` deletes the data.

**The disk fills up.** Container logs are capped at 10 MB with three files per service by the `logging` block. Check the backup directory and the Docker images next, with `docker system df`.

## Hardening notes

- `backend/Dockerfile` installs the `dev` extra, so the API image carries `pytest` and `ruff`. To drop them, change the install line to `RUN pip install --no-cache-dir .` and remove `COPY tests ./tests` in a production copy of the file. The API does not import anything from `tests`.
- Logout clears the cookie only. A copied token stays valid until it expires, so keep `JWT_EXPIRE_MINUTES` short. Changing `JWT_SECRET` invalidates every issued token.
- Resetting a user's password invalidates that user's earlier tokens. To force every session to sign in again, run `UPDATE users SET token_version = token_version + 1;` in the database.
- Monitor creation is admin-only, and the prober follows redirects without blocking private address ranges. Treat admin access as trust.
- The auth cookie is `HttpOnly` and `Secure`. Do not put the UI behind a second proxy that terminates TLS without forwarding the original scheme.
