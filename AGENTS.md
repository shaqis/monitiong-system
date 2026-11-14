# AGENTS.md — Engineering Rules & Conventions

This document defines mandatory architectural rules, coding conventions, and verification workflows for AI coding agents working on this repository. Always read `PRD.md` alongside this file before implementing any feature.

---

## 1. Source of Truth & Execution Workflow

1. **Follow `PRD.md` Strictly**: Do not invent unrequested features, alter database column names, or change API route paths defined in `PRD.md`.
2. **Sequential Phase Execution**: Implement the system strictly in the order defined in **Section 9 (Phased Implementation Plan)** of `PRD.md`. Do not start Frontend work until Backend APIs and pytest suites pass.
3. **Close the Ticket Honestly**: Before starting the next phase, check off every acceptance criterion on the completed phase issue and confirm the merged PR closed it. An unchecked criterion blocks the next phase or moves to a tracked follow-up issue.
4. **Inspect Before Editing**: Always inspect existing directory structure, config files, and schemas before creating or modifying files.
5. **Zero Placeholders**: Never leave `TODO` comments, stubbed functions, hardcoded mock data, or skipped tests in completed phases.
6. **Verify Every Change**: After completing each module or phase, run the relevant linter, type checker, and test suite before moving on.

---

## 2. Tech Stack Boundaries

* **Frontend**: Next.js (App Router), TypeScript (`strict: true`), Tailwind CSS, Shadcn/UI, Recharts.
* **Backend**: FastAPI, Python 3.12+, Pydantic v2, SQLAlchemy 2.0 (Async), Alembic, `httpx`.
* **Database**: PostgreSQL 16+ (via `asyncpg` driver for FastAPI and `psycopg` / `asyncpg` for Alembic).
* **Containerization**: Docker & Docker Compose (`db`, `backend`, `frontend`).

---

## 3. Backend Conventions (FastAPI & Python)

### 3.1 Async-First Architecture
* All database operations, HTTP probes, and route handlers **must be asynchronous** (`async def`).
* **Forbidden**: Never use synchronous blocking libraries such as `requests`, `urllib`, `psycopg2`, or `time.sleep()` inside FastAPI routes or background workers. Use `httpx.AsyncClient` and `asyncio.sleep()`.
* For blocking standard-library calls (such as `ssl` / `socket` certificate inspection), wrap execution in `await asyncio.to_thread(...)` with strict timeouts.

### 3.2 SQLAlchemy 2.0 & Database Rules
* Use SQLAlchemy 2.0 declarative style with `Mapped[...]` and `mapped_column(...)`.
* Every table must use UTC-aware timestamps (`DateTime(timezone=True)`), defaulting to `datetime.now(timezone.utc)`.
* All schema modifications **must** go through **Alembic** migrations (`alembic revision --autogenerate -m "..."`). Never rely on `Base.metadata.create_all()` in application startup.
* Always index foreign keys and high-frequency query columns (especially `(monitor_id, checked_at DESC)` on `monitor_checks`).

### 3.3 Pydantic v2 & API Design
* Use Pydantic v2 syntax (`model_config = ConfigDict(from_attributes=True)`). Never use deprecated v1 `.dict()` or `class Config:`.
* Maintain strict separation between schemas: `*Create`, `*Update`, and `*Response`. Never return ORM models or `hashed_password` fields directly from endpoints.
* Prefix all routes with `/api/v1` and return standard HTTP status codes (`201 Created` on POST creation, `204 No Content` on DELETE, `401 Unauthorized`, `403 Forbidden`, `404 Not Found`, `422 Unprocessable Entity`).

### 3.4 Security & RBAC Enforcement
* Enforce authentication and role checks at the FastAPI dependency layer (`Depends(get_current_user)` and `Depends(require_admin)`).
* Never rely solely on frontend UI hiding to restrict `viewer` users.
* Hash passwords using `bcrypt` (via `passlib[bcrypt]` or `pwdlib`). Never log plain-text passwords, JWT secrets, or authorization headers.
* Enforce the last-admin guardrail: reject any `PATCH /api/v1/users/{id}` request that attempts to deactivate or demote the sole remaining active `admin`.

### 3.5 Background Monitoring Worker Rules
* Bound concurrent URL probes with `asyncio.Semaphore(MAX_CONCURRENT_CHECKS)` (default `20`).
* Catch all network exceptions (`httpx.TimeoutException`, `httpx.ConnectError`, `ssl.SSLError`, DNS resolution errors) cleanly inside `prober.py` so a single failing URL never crashes the scheduler loop.
* Strictly enforce the **2-strike failure rule**:
  * `consecutive_failures == 1`: Record check failure, keep monitor status `UP` (or `DEGRADED`), schedule rapid retry in 5 seconds.
  * `consecutive_failures >= 2`: Set monitor status to `DOWN` and create an open row in `incidents` only if no unresolved incident currently exists for that `monitor_id`.
  * Recovery (`status == UP`): Reset `consecutive_failures = 0`, set status `UP`, and close any open incident by setting `resolved_at`.

### 3.6 Python Code Style
* Use modern Python 3.12+ type hints (`list[str]`, `dict[str, Any]`, `UUID | None`).
* Format and lint with `ruff` (`ruff check .` and `ruff format .`).

---

## 4. Frontend Conventions (Next.js & TypeScript)

### 4.1 TypeScript & Project Structure
* Enable `"strict": true` in `tsconfig.json`. The `any` type is **strictly forbidden**—define explicit TypeScript interfaces in `src/types/` matching backend Pydantic response schemas.
* Keep components modular and single-purpose inside `src/components/{layout,dashboard,monitors,users}`.

### 4.2 Server vs. Client Components
* Default to React Server Components where possible; add `'use client'` only when using React hooks (`useState`, `useEffect`), browser APIs, event handlers, or Recharts components.
* Centralize all backend HTTP communication in `src/lib/api.ts`. Automatically attach auth credentials, parse structured error messages, and redirect to `/login` on `401 Unauthorized`.

### 4.3 Role-Aware UI & UX States
* Use `AuthContext` (`src/lib/auth-context.tsx`) to expose `user`, `role`, `isAdmin`, and `logout`.
* Hide or disable mutation controls (Add URL, Edit, Delete, Pause, Check Now, User Management nav link) when `role === 'viewer'`.
* Protect `/users` with a role guard that redirects `viewer` users immediately to `/dashboard`.
* Every asynchronous view (Dashboard, URLs list, Monitor detail, Users table) must implement explicit **Loading** (skeleton loaders), **Empty** (actionable empty state), and **Error** (retry alert) UI states.

---

## 5. Standard Verification Commands

Run these commands from the repository root (or respective service containers) to verify work before finishing any task:

### Backend Verification
```bash
# Run database migrations
docker compose exec backend alembic upgrade head

# Lint and check formatting
docker compose exec backend ruff check .

# Run unit and RBAC integration tests
docker compose exec backend pytest -v
```

### Frontend Verification
```bash
# TypeScript strict type check
docker compose exec frontend npx tsc --noEmit

# ESLint check
docker compose exec frontend npm run lint

# Production build verification
docker compose exec frontend npm run build
```

### Full-Stack Smoke Check
```bash
docker compose up -d --build
docker compose ps
```