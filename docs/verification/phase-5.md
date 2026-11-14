# Phase 5 end-to-end verification

This run proves the full stack works through the browser and the worker. It covers both roles, the two-strike failure rule, incident recovery, dashboard accuracy, every admin mutation, and the delete cascade. Every number below comes from a command or a database query recorded in this document.

- Date: 2026-11-14 16:00 to 16:13 UTC.
- Base: `main` at `859453e`, the merge of Phase 4.
- Branch: `phase-5-verification`.
- Stack: Compose project `phase5` on ports 3002 (frontend), 8003 (backend), and 5435 (Postgres), with a fresh database volume.
- Browser: Playwright 1.64 driving Chromium 1243 headless at 1440x1200.
- Target server: a container on the `phase5` network, alias `target`, running `python -m http.server 9000` over a directory under `.audit/phase-5-target`.

## Start the stack and confirm health

```bash
COMPOSE_PROJECT_NAME=phase5 \
BACKEND_PORT=8003 POSTGRES_PORT=5435 FRONTEND_PORT=3002 \
CORS_ORIGINS='["http://localhost:3002"]' \
NEXT_PUBLIC_API_URL=http://localhost:8003/api/v1 \
docker-compose up -d --build
```

```text
NAME                SERVICE    STATUS
phase5-backend-1    backend    Up (healthy)      127.0.0.1:8003->8000/tcp
phase5-db-1         db         Up (healthy)      127.0.0.1:5435->5432/tcp
phase5-frontend-1   frontend   Up (healthy)      127.0.0.1:3002->3000/tcp
phase5-migrate-1    migrate    Exited (0)
```

`alembic current` reports `a883d511c882 (head)`.

The login page renders at the frontend port.

![Login page](phase-5/01-login.png)

This pull request adds a healthcheck to the `frontend` service so all three services report a health state. Before the change the frontend only reported `Up`.

## Scenario monitors

The admin created all three monitors through the Add URL dialog in the browser. The defaults supplied method `GET`, interval 60 seconds, timeout 10 seconds, and expected status 200.

| Name | URL | Keyword | Purpose |
| --- | --- | --- | --- |
| Phase 5 Healthy | `http://target:9000/index.html` | none | Always returns 200. |
| Phase 5 Keyword Missing | `http://target:9000/keyword.html` | `PAYMENT ENABLED` | Body lacks the keyword. |
| Phase 5 Unreachable | `http://target:9099/` | none | Closed port, connection refused. |

After creation the list shows all three as `PENDING`.

![Admin URL list with three new monitors](phase-5/04-admin-urls-created.png)

## Two-strike failure rule

A database poller sampled every monitor every 500 milliseconds while the scheduler ran. The transition sequence is exact.

| Time (UTC) | Monitor | Status | Consecutive failures | Checks | Incidents | Open incidents |
| --- | --- | --- | --- | --- | --- | --- |
| 16:03:31 | Phase 5 Healthy | PENDING | 0 | 0 | 0 | 0 |
| 16:03:32 | Phase 5 Keyword Missing | PENDING | 0 | 0 | 0 | 0 |
| 16:03:32 | Phase 5 Unreachable | PENDING | 0 | 0 | 0 | 0 |
| 16:03:40 | Phase 5 Healthy | UP | 0 | 1 | 0 | 0 |
| 16:03:40 | Phase 5 Keyword Missing | DEGRADED | 1 | 1 | 0 | 0 |
| 16:03:40 | Phase 5 Unreachable | DEGRADED | 1 | 1 | 0 | 0 |
| 16:03:45 | Phase 5 Unreachable | DOWN | 2 | 2 | 1 | 1 |
| 16:03:46 | Phase 5 Keyword Missing | DOWN | 2 | 2 | 1 | 1 |

Both failure monitors stayed `DEGRADED` after the first failure with zero incidents. Each reached `DOWN` only on the second failure, and each opened exactly one incident. Later failures increased `consecutive_failures` to 4 without opening another incident.

The check rows show the two failure causes.

| Monitor | Status | HTTP | Keyword matched | Error |
| --- | --- | --- | --- | --- |
| Phase 5 Keyword Missing | DOWN | 200 | false | `Keyword 'PAYMENT ENABLED' not found in first 1 MiB of response body` |
| Phase 5 Unreachable | DOWN | null | null | `Connection failed: All connection attempts failed` |
| Phase 5 Healthy | UP | 200 | null | null |

![Dashboard with two monitors down and two ongoing incidents](phase-5/05-admin-dashboard-down.png)

![URL list with both failure monitors down](phase-5/06-admin-urls-down.png)

![Keyword monitor detail with an ongoing incident](phase-5/07-admin-detail-keyword-down.png)

![Unreachable monitor detail with a connection failure](phase-5/08-admin-detail-unreachable-down.png)

## Recovery

The target body was changed to contain `PAYMENT ENABLED`, then a check ran. The next sampled state was:

| Field | Value |
| --- | --- |
| `current_status` | `UP` |
| `consecutive_failures` | `0` |
| Checks | 4 |
| Incidents | 1 |
| Open incidents | 0 |
| `resolved_at` | `2026-11-14 16:05:31.281838+00` |
| Incident duration | 105 seconds |

The detail page shows `UP`, four checks, and the incident marked `Resolved` with a resolved timestamp.

![Recovered keyword monitor with a resolved incident](phase-5/09-admin-detail-keyword-recovered.png)

## Dashboard values against the database

The API response for `GET /api/v1/dashboard/summary?range=24h` and a SQL snapshot were taken together at 16:09 UTC. They match field by field.

| Metric | API | SQL |
| --- | --- | --- |
| Total monitors | 2 | 2 |
| Active monitors | 2 | 2 |
| Paused monitors | 0 | 0 |
| UP | 2 | 2 |
| DOWN or DEGRADED | 0 | 0 |
| PENDING | 0 | 0 |
| Overall uptime | 82.35% | 82.35% |
| Average response time | 33.18 ms | 33.18 ms |
| Incidents in the window | 1 | 1 |

The SQL used the same window and filters as the endpoint.

```sql
with w as (select now() - interval '24 hours' as since)
select 'total_monitors', count(*) from monitors
union all select 'active_monitors', count(*) from monitors where is_active
union all select 'paused_monitors', count(*) from monitors where not is_active
union all select 'up_count', count(*) from monitors where is_active and current_status = 'UP'
union all select 'down_count', count(*) from monitors where is_active and current_status in ('DOWN', 'DEGRADED')
union all select 'pending_count', count(*) from monitors where is_active and current_status = 'PENDING'
union all select 'overall_uptime',
  coalesce(round(100.0 * count(*) filter (where status = 'UP') / nullif(count(*), 0), 2), 0)
  from monitor_checks, w where checked_at >= w.since
union all select 'avg_response_time_ms',
  coalesce(round(avg(response_time_ms)::numeric, 2), 0)
  from monitor_checks, w where checked_at >= w.since and response_time_ms is not null
union all select 'incidents_in_window', count(*)
  from incidents, w
  where resolved_at is null or resolved_at >= w.since or started_at >= w.since;
```

All four ranges returned data.

| Range | Monitors | UP | DOWN | Uptime | Latency points | Incidents |
| --- | --- | --- | --- | --- | --- | --- |
| 1h | 2 | 2 | 0 | 82.35% | 8 | 1 |
| 24h | 2 | 2 | 0 | 82.35% | 1 | 1 |
| 7d | 2 | 2 | 0 | 82.35% | 1 | 1 |
| 30d | 2 | 2 | 0 | 82.35% | 1 | 1 |

The values drift as new checks land. The final screenshot at 16:12 shows 85.00% uptime and 30 ms average because more successful checks had arrived. The incident feed, status bars, and per-monitor values still agree with the database.

![Final dashboard for 24 hours](phase-5/24-admin-dashboard-final-24h.png)

![Dashboard for 7 days](phase-5/25-admin-dashboard-7d.png)

![Dashboard for 30 days](phase-5/25-admin-dashboard-30d.png)

## Viewer access

A viewer account was created from the Users page, then used in a fresh browser context with no admin cookies.

| Check | Result |
| --- | --- |
| `/dashboard` | 200, renders KPIs, charts, status bars, and incidents |
| `/urls` Add URL buttons | 0 |
| `/urls` Actions column headers | 0 |
| `/urls` row action buttons | 0 |
| Monitor detail mutation buttons | 0 |
| `/users` | Redirects to `/dashboard` |
| `/users` Create user buttons after redirect | 0 |
| Users nav links in the sidebar | 0 |
| `POST /api/v1/monitors` with the viewer token | 403, `Admin access required` |
| `GET /api/v1/users` with the viewer token | 403, `Admin access required` |

![Admin users page](phase-5/17-admin-users.png)

![Create viewer dialog](phase-5/18-admin-create-viewer.png)

![Users list with the new viewer](phase-5/19-admin-users-with-viewer.png)

![Viewer dashboard](phase-5/20-viewer-dashboard.png)

![Viewer URL list without Add URL or Actions](phase-5/21-viewer-urls.png)

![Viewer monitor detail without mutation buttons](phase-5/22-viewer-detail.png)

![Viewer redirected from /users to /dashboard](phase-5/23-viewer-users-redirect.png)

## Admin mutations

Each action ran from the browser against the live stack.

| Action | Observed result | Screenshot |
| --- | --- | --- |
| Pause | Row badge changed to `PAUSED`, alert `Monitor paused` | `10-admin-paused.png` |
| Resume | Row badge returned to `UP`, alert `Monitor resumed` | `11-admin-resumed.png` |
| Check now | Alert `Check completed for Phase 5 Healthy` and `UP in 30 ms.` | `12-admin-check-now.png` |
| Edit | Dialog prefilled with the current configuration, saved name `Phase 5 Healthy Edited` appeared in the row | `13-admin-edit-modal.png`, `14-admin-edited.png` |
| Delete | Confirm dialog named the monitor and its logs and incidents, row disappeared after confirmation | `15-admin-delete-confirm.png`, `16-admin-urls-after-delete.png` |

![Paused monitor](phase-5/10-admin-paused.png)

![Resumed monitor](phase-5/11-admin-resumed.png)

![Manual check completed](phase-5/12-admin-check-now.png)

![Edit dialog](phase-5/13-admin-edit-modal.png)

![Edited monitor name](phase-5/14-admin-edited.png)

![Delete confirmation](phase-5/15-admin-delete-confirm.png)

![URL list after delete](phase-5/16-admin-urls-after-delete.png)

## Delete cascade

The unreachable monitor was deleted from the browser. Counts were taken immediately before and after.

| Row | Before | After |
| --- | --- | --- |
| Monitor | 1 | 0 |
| `monitor_checks` for the monitor | 7 | 0 |
| `incidents` for the monitor | 1 | 0 |
| Orphan `monitor_checks` | not applicable | 0 |
| Orphan `incidents` | not applicable | 0 |

```sql
select count(*) from monitor_checks c left join monitors m on m.id = c.monitor_id where m.id is null;
select count(*) from incidents i left join monitors m on m.id = i.monitor_id where m.id is null;
```

## Verification suite

| Command | Result |
| --- | --- |
| `backend pytest -q` | `153 passed, 1 warning in 54.86s` |
| `backend ruff check .` | `All checks passed!` |
| `backend ruff format --check .` | `42 files already formatted` |
| `frontend npx tsc --noEmit` | exit 0, no diagnostics |
| `frontend npm run lint` | `No ESLint warnings or errors` |
| `frontend npm run build` | compiled successfully, 8 of 8 static pages, 7 dynamic routes |

## Final state

| Monitor | URL | Status | Consecutive failures | Active |
| --- | --- | --- | --- | --- |
| Phase 5 Healthy Edited | `http://target:9000/index.html` | UP | 0 | true |
| Phase 5 Keyword Missing | `http://target:9000/keyword.html` | UP | 0 | true |

One incident remains, resolved at `2026-11-14 16:05:31 UTC`.

## Reproduce

1. Copy `.env.example` to `.env` and set `FIRST_ADMIN_PASSWORD` and `JWT_SECRET`.
2. Create the target directory with `index.html` and `keyword.html`. The keyword file must not contain `PAYMENT ENABLED` for the failing phase.
3. Start the stack with the command at the top of this document.
4. Start the target server on the Compose network.

   ```bash
   docker run -d --rm --name phase5-target \
     --network phase5_default --network-alias target \
     -v "$PWD/.audit/phase-5-target":/srv:ro \
     phase5-backend python -m http.server 9000 --bind 0.0.0.0 --directory /srv
   ```

5. Sign in as the seeded admin at `http://localhost:3002/login` and create the three monitors from the table above.
6. Watch the database for the `DEGRADED` to `DOWN` transitions, or run the poller query in a loop.
7. Add `PAYMENT ENABLED` to `keyword.html` and run a check to recover.
8. Create a viewer on the Users page and repeat the viewer checks in a private window.
9. Exercise pause, resume, check now, edit, and delete on the URL list.
10. Compare the dashboard response with the SQL snapshot above.
