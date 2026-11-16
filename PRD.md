# Product Requirements Document (PRD): URL & Web App Uptime Monitoring System

## 1. Overview & Objective

Build a self-hosted, black-box website and web application monitoring platform that tracks availability, response latency, content integrity, and SSL certificate health using **target URLs only** (no internal APIs or agents required on monitored targets).

This document is structured for execution by an AI coding agent in a terminal-based workflow. Every schema, endpoint, role permission, and background worker rule is explicitly defined to minimize ambiguity.

## 2. Tech Stack & Architecture

| Layer                  | Technology                                                   | Purpose                                                      |
| ---------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| **Frontend**           | Next.js (App Router), TypeScript, Tailwind CSS, Shadcn/UI, Recharts | Responsive web dashboard, analytics visualizations, URL & user management UI |
| **Backend**            | FastAPI (Python 3.12+), Pydantic v2, SQLAlchemy 2.0 (Async), Alembic | REST API, RBAC enforcement, async HTTP/SSL probing engine    |
| **Worker / Scheduler** | Python `asyncio` (in-process loop) + `httpx` | Periodic non-blocking URL health checks, keyword verification, SSL checks |
| **Database**           | PostgreSQL 16+                                               | Persistent storage for users, monitor configs, check logs, and incidents |
| **Infrastructure**     | Docker & Docker Compose                                      | Reproducible local development and deployment (`db`, `backend`, `frontend`) |

## 3. User Roles & Access Control (RBAC)

The system uses a simple two-role access control model enforced at the FastAPI dependency layer and reflected in the Next.js UI.

### Role Definitions

- `**admin**`: Full system control. Can manage users, configure system settings, and create/edit/delete/pause any monitored URL.
- `**viewer**` *(Standard User)*: Read-only operational access. Can view the analytics dashboard, inspect URL check histories, and view incident logs, but cannot modify users or alter monitor configurations.

### Permission Matrix

| Feature / Action                      | `admin` | `viewer` |
| ------------------------------------- | ------- | -------- |
| Login / Logout / View Own Profile     | Yes     | Yes      |
| View Analytics Dashboard & Charts     | Yes     | Yes      |
| View URL List & Detailed Check Logs   | Yes     | Yes      |
| Trigger Manual "Check Now"            | Yes     | No       |
| Create / Edit / Delete / Pause URLs   | Yes     | No       |
| Access User Management Page           | Yes     | No       |
| Create / Edit Role / Deactivate Users | Yes     | No       |

## 4. Database Schema (PostgreSQL)

Use UUID primary keys and UTC timestamps (`TIMESTAMPTZ`) across all tables.

### 4.1 `users`

Stores user credentials, role assignment, and account status.

- `id`: `UUID` (PK, default `gen_random_uuid()`)
- `email`: `VARCHAR(255)` (Unique, Not Null, Indexed)
- `full_name`: `VARCHAR(120)` (Not Null)
- `hashed_password`: `TEXT` (Not Null)
- `role`: `VARCHAR(20)` (Not Null, default `'viewer'`, check constraint: `role IN ('admin', 'viewer')`)
- `is_active`: `BOOLEAN` (Not Null, default `true`)
- `created_at`: `TIMESTAMPTZ` (Not Null, default `now()`)
- `updated_at`: `TIMESTAMPTZ` (Not Null, default `now()`)

### 4.2 `monitors`

Stores target URLs and check rules.

- `id`: `UUID` (PK, default `gen_random_uuid()`)
- `name`: `VARCHAR(120)` (Not Null — friendly label, e.g., `"Production Portal"`)
- `url`: `TEXT` (Not Null — must start with `http://` or `https://`)
- `http_method`: `VARCHAR(10)` (Not Null, default `'GET'` — supports `'GET'`, `'HEAD'`)
- `interval_seconds`: `INTEGER` (Not Null, default `60` — allowed: `60`, `300`, `600`, `1800`)
- `timeout_seconds`: `INTEGER` (Not Null, default `10` — max `30`)
- `expected_status_code`: `INTEGER` (Not Null, default `200`)
- `keyword`: `VARCHAR(255)` (Nullable — optional substring that must exist in response body)
- `check_ssl`: `BOOLEAN` (Not Null, default `true`)
- `is_active`: `BOOLEAN` (Not Null, default `true` — false when paused)
- `current_status`: `VARCHAR(20)` (Not Null, default `'PENDING'` — `'UP'`, `'DOWN'`, `'DEGRADED'`, `'PENDING'`)
- `consecutive_failures`: `INTEGER` (Not Null, default `0`)
- `ssl_days_remaining`: `INTEGER` (Nullable)
- `last_checked_at`: `TIMESTAMPTZ` (Nullable)
- `created_by`: `UUID` (FK -> `users.id`, `ON DELETE SET NULL`)
- `created_at`: `TIMESTAMPTZ` (Not Null, default `now()`)
- `updated_at`: `TIMESTAMPTZ` (Not Null, default `now()`)

### 4.3 `monitor_checks`

Time-series log of every probe execution.

- `id`: `BIGSERIAL` (PK)
- `monitor_id`: `UUID` (FK -> `monitors.id`, `ON DELETE CASCADE`, Not Null)
- `status`: `VARCHAR(20)` (Not Null — `'UP'`, `'DOWN'`)
- `status_code`: `INTEGER` (Nullable — null on DNS/timeout/connection failure)
- `response_time_ms`: `INTEGER` (Nullable)
- `keyword_matched`: `BOOLEAN` (Nullable)
- `error_message`: `TEXT` (Nullable — e.g., `"Connection timeout after 10s"`, `"Expected 200, got 502"`)
- `checked_at`: `TIMESTAMPTZ` (Not Null, default `now()`)
- **Index**: Composite index on `(monitor_id, checked_at DESC)` for fast time-series queries.

### 4.4 `incidents`

Tracks downtime periods for accurate MTTR (Mean Time To Recovery) and incident history.

- `id`: `UUID` (PK, default `gen_random_uuid()`)
- `monitor_id`: `UUID` (FK -> `monitors.id`, `ON DELETE CASCADE`, Not Null)
- `started_at`: `TIMESTAMPTZ` (Not Null)
- `resolved_at`: `TIMESTAMPTZ` (Nullable — `NULL` means ongoing incident)
- `cause`: `TEXT` (Not Null)

### 4.5 `notification_settings`

Single-row admin-managed email configuration. When the row is absent the worker falls back to the environment variables in section 5.5.

- `id`: `SMALLINT` (PK, `CHECK id = 1`)
- `enabled`: `BOOLEAN` (Not Null, default `false`)
- `provider`: `VARCHAR(20)` (Not Null, default `'smtp'` — `CHECK provider IN ('smtp', 'brevo')`)
- `from_address`: `VARCHAR(255)` (Not Null)
- `from_name`: `VARCHAR(120)` (Not Null)
- `recipients`: `VARCHAR(255)[]` (Not Null, default `'{}'`)
- `timeout_seconds`: `DOUBLE PRECISION` (Not Null, default `10`)
- `smtp_host`: `VARCHAR(255)` (Nullable)
- `smtp_port`: `INTEGER` (Not Null, default `587`, `CHECK smtp_port BETWEEN 1 AND 65535`)
- `smtp_starttls`: `BOOLEAN` (Not Null, default `true`)
- `smtp_ssl`: `BOOLEAN` (Not Null, default `false`, `CHECK NOT (smtp_starttls AND smtp_ssl)`)
- `smtp_username`: `VARCHAR(255)` (Nullable)
- `smtp_password_encrypted`: `TEXT` (Nullable — Fernet token, never plaintext)
- `brevo_api_key_encrypted`: `TEXT` (Nullable — Fernet token, never plaintext)
- `updated_at`: `TIMESTAMPTZ` (Not Null, default `now()`)

## 5. Functional Requirements

### 5.1 Authentication & Bootstrap

- **Initial Admin Seeding**: On backend startup, if the `users` table is empty, automatically seed an initial admin account using environment variables (`FIRST_ADMIN_EMAIL`, `FIRST_ADMIN_PASSWORD`, `FIRST_ADMIN_NAME`).
- **Login Flow**: Users sign in with email and password. Backend validates credentials and returns a JWT access token (stored securely via HTTP-only cookie or bearer auth header).
- **Protected Routes**: Unauthenticated users accessing any route other than `/login` are redirected to `/login`. Deactivated users (`is_active = false`) cannot log in or use existing tokens.

### 5.2 Analytics Dashboard (`/dashboard`)

Provides a high-level operational overview with a global time-range selector (`1H`, `24H`, `7D`, `30D`):

- **KPI Summary Cards**:
  - Total Monitored URLs (Active vs. Paused)
  - Operational Health (`UP` count vs. `DOWN` count)
  - Overall Uptime Percentage across selected period
  - Average Response Time (`ms`)
- **Response Latency Trend Chart**: Multi-line or area chart displaying average response time (`ms`) over time.
- **Uptime & Status Breakdown**: Visual status bar per monitor showing recent check intervals (green = UP, red = DOWN, gray = paused/no data).
- **Recent Incidents Feed**: Table listing active and recently resolved downtime events with monitor name, failure cause, start time, and duration.

### 5.3 URL Management (`/urls` and `/urls/[id]`)

- **URL Directory Table**:
  - Columns: Status badge (`UP` / `DOWN` / `PENDING` / `PAUSED`), Name & URL, HTTP Method, Interval, Last Latency (`ms`), Uptime (24h), SSL Expiry (days remaining), and Actions.
  - Search by name/URL and filter by status (`ALL`, `UP`, `DOWN`, `PAUSED`).
- **Add / Edit URL Modal (Admin Only)**:
  - Fields: Display Name, Target URL, HTTP Method (`GET`/`HEAD`), Check Interval (`1m`, `5m`, `10m`, `30m`), Timeout (`5s–30s`), Expected Status Code (default `200`), Optional Content Keyword, and SSL Check toggle.
  - Validation: Reject malformed URLs; warn if `HEAD` method is paired with a body keyword check.
- **Monitor Detail Page (`/urls/[id]`)**:
  - Dedicated response-time chart, uptime stats (`24h`, `7d`, `30d`), SSL certificate expiration badge, incident timeline, and paginated raw check logs.
  - Admin actions: **Run Check Now**, **Pause/Resume**, **Edit**, **Delete**.

### 5.4 User Management (`/users` — Admin Only)

- Redirect `viewer` users to `/dashboard` if they navigate to `/users` directly.
- **User Table**: Display Full Name, Email, Role badge (`admin` / `viewer`), Status (`Active` / `Inactive`), and Created Date.
- **Create User Modal**: Admin can create new accounts with Email, Full Name, Temporary Password, and Role.
- **Manage User Actions**:
  - Toggle role between `admin` and `viewer`.
  - Activate / Deactivate account.
  - Reset user password.
  - Guardrail: Prevent an admin from deactivating or demoting their own account if they are the last active `admin`.

### 5.5 Email Notifications (Admin, Database Configured)

Sends an operational email when an incident opens or resolves. Settings live in the single-row `notification_settings` table and are edited on the admin **Settings** page. The effective configuration is resolved on every send, so a saved change takes effect without a restart. When no row exists, the environment variables below are the fallback.

- **Storage**: one row (`id = 1`). `smtp` and `brevo` are editable from the UI. `mailgun` and `mailtrap` remain environment-only providers.
- **Secrets at rest**: `smtp_password` and `brevo_api_key` are encrypted with Fernet using a key derived from `JWT_SECRET`. Rotating `JWT_SECRET` makes the saved secrets undecryptable; re-enter them on the settings page.
- **Transport selection**: `EMAIL_PROVIDER` sets the fallback provider and is one of `smtp`, `brevo`, `mailgun`, or `mailtrap`. A saved row overrides it. Every transport implements one `EmailTransport` interface, so the worker and the API do not branch on the provider.
- **Enablement**: `EMAIL_NOTIFICATIONS_ENABLED` (default `false`) or the saved row's toggle. When false, incident emails are not sent. The admin test endpoint still works when transport configuration is complete, so an operator can verify credentials before enabling alerts.
- **Sender**: `EMAIL_FROM_ADDRESS` and `EMAIL_FROM_NAME` (default `Uptime Monitor`).
- **Recipients**: `NOTIFICATION_RECIPIENTS` is a JSON list of addresses, for example `["ops@example.com","oncall@example.com"]`. It is required when alerts are enabled. The settings page accepts the same list separated by commas or new lines.
- **SMTP**: `SMTP_HOST`, `SMTP_PORT` (default `587`), `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_STARTTLS` (default `true`), `SMTP_SSL` (default `false`). StartTLS and implicit TLS are mutually exclusive.
- **Brevo**: `BREVO_API_KEY`.
- **Mailgun**: `MAILGUN_API_KEY`, `MAILGUN_DOMAIN`, and `MAILGUN_API_URL` (default `https://api.mailgun.net/v3`; set `https://api.eu.mailgun.net/v3` for the EU region).
- **Mailtrap**: `MAILTRAP_API_TOKEN` (Mailtrap sending API, `https://send.api.mailtrap.io/api/send`).
- **Events**:
  - **Incident opened**: after the second consecutive failed check commits. The message names the monitor, URL, failure cause, and start time.
  - **Incident resolved**: after a successful check closes the open incident. The message names the monitor, URL, resolution time, and duration.
  - A first failed check (`DEGRADED`) does not send email. Further failures on an open incident do not resend it.
- **Delivery semantics**: best effort, one message per transition, sent after the database transaction commits. A delivery failure is logged and never changes the check result, monitor status, or incident. This phase has no retry queue and no delivery table.
- **Secrets**: never returned by an API, never logged, and never stored in plaintext.

## 6. Background Monitoring Engine Rules

1. **Polling Loop**: Every 10 seconds, the scheduler queries `monitors` where `is_active = true` and (`last_checked_at IS NULL` OR `last_checked_at + interval_seconds <= now()`).
2. **Concurrent Execution**: Execute due checks concurrently using `asyncio.gather` with a semaphore (`MAX_CONCURRENT_CHECKS=20`) to prevent socket exhaustion.
3. **Probe Logic**:
   - Send request using `httpx.AsyncClient(follow_redirects=True, verify=True)` with custom header `User-Agent: UptimeMonitor/1.0`.
   - Measure elapsed wall-clock time in milliseconds.
   - **Success Criteria**:
     - HTTP status matches `expected_status_code` (or is within `200–299` if default).
     - If `keyword` is configured, `keyword in response.text` must evaluate to `True`.
4. **SSL Inspection**:
   - For `https://` URLs with `check_ssl = true`, inspect the peer TLS certificate `notAfter` field (at least once every 6 hours or on every check) and update `ssl_days_remaining`.
5. **False-Alarm Prevention (Retry & State Machine)**:
   - On single failure: Increment `consecutive_failures`. Keep `current_status` as `'UP'` (or `'DEGRADED'`) if `consecutive_failures == 1`, and immediately schedule a re-check after 5 seconds.
   - When `consecutive_failures >= 2`: Transition `current_status` to `'DOWN'` and open a new row in `incidents` (if no open incident exists for that monitor).
   - On recovery: Reset `consecutive_failures = 0`, set `current_status = 'UP'`, and update `resolved_at = now()` on the open incident.

## 7. API Specification (FastAPI)

All endpoints are prefixed with `/api/v1`.

### Auth

- `POST /auth/login` — Authenticate user, return JWT & user profile.
- `POST /auth/logout` — Clear auth session/cookie.
- `GET /auth/me` — Return current authenticated user details and role.

### Dashboard

- `GET /dashboard/summary?range=24h` — Return KPI metrics, aggregated latency series, and active/recent incidents.

### Monitors (URLs)

- `GET /monitors` — List all monitors with latest status, 24h uptime %, and SSL days remaining (`admin` & `viewer`).
- `POST /monitors` — Create a new monitor (`admin` only).
- `GET /monitors/{id}` — Get monitor config + detailed metrics (`admin` & `viewer`).
- `PATCH /monitors/{id}` — Update monitor settings or pause/resume (`admin` only).
- `DELETE /monitors/{id}` — Delete monitor and cascade check logs (`admin` only).
- `POST /monitors/{id}/check-now` — Trigger an immediate out-of-band check (`admin` only).
- `GET /monitors/{id}/checks?range=24h&limit=100` — Paginated check history and chart points (`admin` & `viewer`).

### Users

- `GET /users` — List all users (`admin` only).
- `POST /users` — Create a new user (`admin` only).
- `PATCH /users/{id}` — Update user role, name, password, or active status (`admin` only).

### Notifications

- `GET /notifications/settings` — Return the effective email configuration with secret values omitted (`admin` only). The response reports `source` as `database` when the saved row is in use, otherwise `environment`, plus `smtp_password_set` and `brevo_api_key_set` flags.
- `PATCH /notifications/settings` — Save `smtp` or `brevo` settings, sender details, and recipients (`admin` only). Returns the same body as `GET`. Missing or invalid provider details return `422 Unprocessable Entity`; an empty recipients list is rejected. Blank secret fields keep the stored value, and clearing the SMTP username clears the stored password.
- `POST /notifications/test` — Send a test email to the saved recipients through the effective transport (`admin` only). Returns `204 No Content` when the provider accepted the message, `503 Service Unavailable` when transport configuration is incomplete, and `502 Bad Gateway` when the provider rejects or cannot be reached.

## 8. Suggested Repository Structure

```text
uptime-monitor/
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic/
│   └── app/
│       ├── main.py              # FastAPI app, CORS, startup seed & scheduler
│       ├── core/
│       │   ├── config.py        # Pydantic Settings
│       │   ├── security.py      # Password hashing & JWT verification
│       │   └── deps.py          # get_current_user, require_admin dependencies
│       ├── db/
│       │   ├── session.py       # Async SQLAlchemy engine & session
│       │   └── models.py        # User, Monitor, MonitorCheck, Incident
│       ├── schemas/             # Pydantic request/response models
│       ├── api/v1/
│       │   ├── auth.py
│       │   ├── dashboard.py
│       │   ├── monitors.py
│       │   ├── notifications.py
│       │   └── users.py
│       ├── notifications/       # Incident events and email transports
│       │   ├── events.py
│       │   ├── service.py
│       │   └── transports.py
│       └── worker/
│           ├── prober.py        # httpx probe + SSL expiry checker
│           └── scheduler.py     # Async periodic check runner
└── frontend/
    ├── Dockerfile
    ├── package.json
    └── src/
        ├── app/
        │   ├── login/page.tsx
        │   ├── dashboard/page.tsx
        │   ├── urls/page.tsx
        │   ├── urls/[id]/page.tsx
        │   └── users/page.tsx
        ├── components/
        │   ├── layout/          # Sidebar, Topbar, RoleGuard
        │   ├── dashboard/       # KPI cards, LatencyChart, IncidentsTable
        │   ├── monitors/        # MonitorTable, MonitorFormModal, UptimeBar
        │   └── users/           # UserTable, UserFormModal
        └── lib/
            ├── api.ts           # Typed API client with auth handling
            └── auth-context.tsx # Current user & role state provider
```

## 9. Phased Implementation Plan (For AI TUI Execution)

Execute and verify in strict sequential order:

1. **Phase 1 — Infrastructure & Database**: Set up `docker-compose.yml` with PostgreSQL, initialize FastAPI with SQLAlchemy 2.0 + Alembic migrations, create all 4 tables, and implement startup admin seeding.
2. **Phase 2 — Auth & User Management API**: Implement JWT authentication, `get_current_user` / `require_admin` dependencies, and `/api/v1/auth` + `/api/v1/users` endpoints. Write pytest integration tests verifying RBAC enforcement (`403 Forbidden` when `viewer` calls admin endpoints).
3. **Phase 3 — Monitoring Engine & Monitor API**: Implement `prober.py` (HTTP status, latency, keyword check, SSL expiry), `scheduler.py` (with 2-strike failure threshold and incident lifecycle), and `/api/v1/monitors` + `/api/v1/dashboard` endpoints.
4. **Phase 4 — Next.js Frontend**: Scaffold Next.js App Router with Tailwind + Shadcn/UI, build authentication flow, role-aware navigation sidebar, Analytics Dashboard with Recharts, URL Management CRUD + Detail view, and Admin User Management page.
5. **Phase 5 — End-to-End Verification**: Run full stack via Docker Compose, verify login as both `admin` and `viewer`, add test URLs (valid `200` URL, invalid keyword URL, unreachable URL), confirm incident creation/recovery, and validate dashboard metrics.
6. **Phase 6 — Email Notifications**: Implement the four transport adapters, incident open/resolve dispatch after commit, environment fallback validation, the admin test-send endpoint, and the editable admin settings page backed by `notification_settings`. Verify with pytest: each provider payload, one email per transition, silent first-failure, replica-conflict suppression, failure isolation from check recording, encrypted secrets, and RBAC on the notification endpoints.