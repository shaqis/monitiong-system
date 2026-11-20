# System & Module Statecharts

This document summarizes the four TLA+ / TLC statecharts and verified findings for the systems and modules in this repository.

---

## 1. Monitor Health, 2-Strike Rule & Incident Lifecycle

**Source modules:**
- [`backend/app/worker/state.py`](../backend/app/worker/state.py)
- [`backend/app/worker/checker.py`](../backend/app/worker/checker.py)
- [`backend/app/worker/scheduler.py`](../backend/app/worker/scheduler.py)
- [`backend/app/api/v1/monitors.py`](../backend/app/api/v1/monitors.py)
- [`backend/app/api/v1/dashboard.py`](../backend/app/api/v1/dashboard.py)
- [`frontend/src/components/monitors/status-badge.tsx`](../frontend/src/components/monitors/status-badge.tsx)

```mermaid
---
title: "Monitor Health, 2-Strike Rule and Incident Lifecycle"
---
stateDiagram-v2
  state "Legend" as legend {
    lg0: empty
    lg1: healthy
    lg2: warning
    lg3: incident
    lg4: paused
    lg5: Breaks ActiveDownHasOpenIncident or ActiveDownRequiresTwoFailures or DegradedRequiresOneFailure
    lg6: Path to the ActiveDownHasOpenIncident or ActiveDownRequiresTwoFailures or DegradedRequiresOneFailure bug
  }
  class lg0 tan
  class lg1 teal
  class lg2 yellow
  class lg3 orange
  class lg4 purple
  class lg5 breaks
  class lg6 bugPath
  s0: Not Created
  state "Active" as s1 {
    s2: Pending Check
    s3: Healthy (UP)
    s4: 1st Strike (DEGRADED)
    s5: Incident Open (DOWN)
    s6: Resumed as DEGRADED (0 strikes)
    s7: Resumed as DOWN (no incident)
  }
  state "Paused" as s8 {
    s9: Paused (Pending)
    s10: Paused (was DEGRADED)
    s11: Paused (was UP)
    s12: Paused (was DOWN)
  }
  [*] --> s0
  s0 --> s2: admin creates monitor
  s2 --> s9: admin pauses
  s2 --> s3: probe succeeds
  s2 --> s4: 1st failure (5s retry scheduled)
  s9 --> s2: admin resumes (due now)
  s3 --> s4: 1st failure (5s retry scheduled)
  s3 --> s11: admin pauses
  s4 --> s3: probe succeeds
  s4 --> s10: admin pauses
  s4 --> s5: 2nd failure (opens incident, sends DOWN email)
  s10 --> s6: admin resumes (due now)
  s11 --> s3: admin resumes (due now)
  s5 --> s3: probe succeeds (resolves incident, sends UP email)
  s5 --> s12: admin pauses (resolves incident silently)
  s12 --> s7: admin resumes (due now)
  s6 --> s3: probe succeeds
  s6 --> s4: 1st failure (5s retry scheduled)
  s7 --> s3: probe succeeds
  s7 --> s4: 1st failure (5s retry scheduled)
  s1 --> s0: admin deletes monitor
  s8 --> s0: admin deletes monitor
  classDef breaks fill:#ffecee,stroke:#e72e3b,stroke-width:2.5px,color:#cd2834
  class s0 tan
  class s0 bugPath
  class s2 teal
  class s2 bugPath
  class s3 teal
  class s4 yellow
  class s4 bugPath
  class s5 orange
  class s5 bugPath
  class s6 yellow
  class s6 breaks
  class s6 bugPath
  class s7 orange
  class s7 breaks
  class s7 bugPath
  class s9 purple
  class s10 purple
  class s10 bugPath
  class s11 purple
  class s12 purple
  class s12 bugPath
```

### Verification Summary
- **Model size:** 11 states, 43 steps (chart draws 11 states and 21 arrows).
- **Rules that hold:** `TypeOK`, `OpenIncidentOnlyWhenActiveDown`, `PendingHasNoIncident`, `NoDeadlock`.
- **Broken rules (replayed and confirmed against backend code):**
  - `DegradedRequiresOneFailure` (at `Resumed as DEGRADED (0 strikes)`): `0. Not Created` -> `1. admin creates monitor` -> `2. 1st failure (5s retry scheduled)` -> `3. admin pauses` -> `4. admin resumes (due now)`. Pausing resets `consecutive_failures = 0` without resetting `current_status`, so resuming leaves an active monitor in `DEGRADED` with `0` failures.
  - `ActiveDownHasOpenIncident` & `ActiveDownRequiresTwoFailures` (at `Resumed as DOWN (no incident)`): `0. Not Created` -> `1. admin creates monitor` -> `2. 1st failure (5s retry scheduled)` -> `3. 2nd failure (opens incident, sends DOWN email)` -> `4. admin pauses (resolves incident silently)` -> `5. admin resumes (due now)`. Pausing resolves the open incident and resets `consecutive_failures = 0` without resetting `current_status`, so resuming leaves an active monitor counted as `DOWN` in `/dashboard/summary` and `/monitors?status=down` with `0` failures and no open incident.
- **Hidden in chart:** `EditTarget` resets (which reset any existing monitor to `Pending Check` / `Paused (Pending)` and resolve open incidents) and `PauseMonitor` from `Resumed as DEGRADED` / `Resumed as DOWN`.
- **Model scope:** Models a single monitor lifecycle; leaves out multi-monitor concurrency, time-series `monitor_checks` logging, `ssl_days_remaining` caching, and `HEAD`+keyword warning validation.

---

## 2. Scheduler & CheckRunner Concurrency

**Source modules:**
- [`backend/app/worker/scheduler.py`](../backend/app/worker/scheduler.py)
- [`backend/app/worker/checker.py`](../backend/app/worker/checker.py)
- [`backend/app/worker/prober.py`](../backend/app/worker/prober.py)
- [`backend/app/api/v1/monitors.py`](../backend/app/api/v1/monitors.py)

```mermaid
---
title: "Scheduler and CheckRunner Concurrency"
---
stateDiagram-v2
  state "Legend" as legend {
    lg0: idle
    lg1: probing
    lg2: stale
    lg3: notifying
    lg4: unavailable
  }
  class lg0 teal
  class lg1 blue
  class lg2 yellow
  class lg3 purple
  class lg4 tan
  s0: Idle (Monitor Active)
  s1: Probing (Snapshot Valid)
  s2: Idle (Monitor Deleted)
  s3: Idle (Monitor Paused)
  s4: Probing (Stale Target or Inactive)
  s5: Post-Commit Notifying (Lock Held)
  [*] --> s0
  s0 --> s1: scheduler or check-now acquires lock and starts probe
  s0 --> s2: admin deletes monitor
  s0 --> s3: admin pauses monitor
  s1 --> s4: admin edits target mid-flight or admin deletes monitor or admin pauses monitor
  s1 --> s5: probe commits incident transition
  s1 --> s0: probe commits check (no incident transition)
  s2 --> s0: admin resumes or creates monitor
  s3 --> s0: admin resumes or creates monitor
  s3 --> s2: admin deletes monitor
  s4 --> s0: record aborts (MonitorChanged, Paused, or NotFound)
  s5 --> s0: notification completes or fails (lock released)
  s4 --> s2: record aborts (MonitorChanged, Paused, or NotFound)
  s4 --> s3: record aborts (MonitorChanged, Paused, or NotFound)
  s5 --> s2: notification completes or fails (lock released)
  s5 --> s3: notification completes or fails (lock released)
  class s0 teal
  class s1 blue
  class s2 tan
  class s3 tan
  class s4 yellow
  class s5 purple
```

### Verification Summary
- **Model size:** 24 states, 82 steps (chart draws 6 states and 15 arrows).
- **All rules hold:** `TypeOK`, `IdleHasNoInflight`, `NoStaleWrite`, `NotifyOnlyAfterCommit`, `NoDeadlock`.
- **Hidden in chart:** `RejectWhenUnavailable`, `RejectConcurrentRun` (`CheckAlreadyRunning` 409), and `AdminEditsTarget` outside `probing`.
- **Model scope:** Models single-process `CheckRunner` admission, `TargetSnapshot` validation, and `WITH FOR UPDATE` commit guards; leaves out `asyncio.Semaphore(20)` queuing across multiple monitors, dedicated SSL thread-pool timeouts, `prober.py` 1 MiB body streaming cap, and multi-process replica races.

---

## 3. Auth, Token Versioning & RBAC Guardrails

**Source modules:**
- [`backend/app/db/seed.py`](../backend/app/db/seed.py)
- [`backend/app/api/v1/auth.py`](../backend/app/api/v1/auth.py)
- [`backend/app/api/v1/users.py`](../backend/app/api/v1/users.py)
- [`backend/app/core/deps.py`](../backend/app/core/deps.py)
- [`backend/app/core/security.py`](../backend/app/core/security.py)
- [`frontend/src/lib/auth-context.tsx`](../frontend/src/lib/auth-context.tsx)
- [`frontend/src/lib/server-session.ts`](../frontend/src/lib/server-session.ts)
- [`frontend/src/lib/api.ts`](../frontend/src/lib/api.ts)
- [`frontend/src/app/(app)/users/page.tsx`](../frontend/src/app/(app)/users/page.tsx)
- [`frontend/src/app/(app)/settings/page.tsx`](../frontend/src/app/(app)/settings/page.tsx)

```mermaid
---
title: "Auth, Token Versioning and RBAC Guardrails"
---
stateDiagram-v2
  state "Legend" as legend {
    lg0: bootstrap
    lg1: loggedOut
    lg2: viewer
    lg3: admin
    lg4: blocked
  }
  class lg0 tan
  class lg1 purple
  class lg2 blue
  class lg3 teal
  class lg4 yellow
  s0: Unseeded Database
  s1: Admin Seeded (No Second User)
  s2: No Valid Session
  s3: Account Deactivated (All Auth Rejected)
  state "Admin Session" as s4 {
    s5: Admin on Dashboard
    s6: Admin on Users or Settings
  }
  state "Viewer Session" as s7 {
    s8: Viewer on Dashboard
    s9: Viewer on Admin Route (Pending Guard)
  }
  s10: Cookie Cleared (Bearer Token Still Valid)
  [*] --> s0
  s0 --> s1: startup seeds initial admin
  s1 --> s2: admin creates admin account or admin creates viewer account
  s2 --> s5: user signs in (cookie and bearer issued)
  s2 --> s8: user signs in (cookie and bearer issued)
  s3 --> s2: admin reactivates user
  s5 --> s8: admin demotes user to viewer
  s5 --> s6: opens /users or /settings
  s8 --> s5: admin promotes user to admin
  s6 --> s9: admin demotes user to viewer
  s10 --> s5: user signs in (cookie and bearer issued)
  s10 --> s2: admin resets password (token_version bumped)
  s10 --> s8: user signs in (cookie and bearer issued)
  s9 --> s8: viewer redirected to /dashboard
  s9 --> s6: admin promotes user to admin
  s4 --> s3: admin deactivates user
  s4 --> s2: admin resets password (token_version bumped)
  s4 --> s10: user logs out (cookie cleared only)
  s7 --> s3: admin deactivates user
  s7 --> s2: admin resets password (token_version bumped)
  s7 --> s10: user logs out (cookie cleared only)
  class s0 tan
  class s1 tan
  class s2 purple
  class s3 yellow
  class s5 teal
  class s6 teal
  class s8 blue
  class s9 blue
  class s10 purple
```

### Verification Summary
- **Model size:** 47 states, 240 steps (chart draws 9 states and 20 arrows).
- **All rules hold:** `TypeOK`, `AlwaysOneActiveAdmin`, `InactiveUserNeverAuthenticates`, `StaleTokensNeverAuthenticate`, `NoDeadlock`.
- **Hidden in chart:** Bootstrap admin role changes (`AdminDemoteOrDeactivateA` / `AdminRestoreA`), re-login while a valid cookie already exists, deactivating an already logged-out user, and reactivating directly into a pre-existing active token state.
- **Model scope:** Models two users (`admin` seed + second user), cookie vs. bearer logout semantics, `token_version` invalidation, the `users_admin_guard` last-admin check, and SSR route guards; leaves out JWT expiration, legacy tokens without `ver`, bcrypt validation, and `COOKIE_SECURE` startup checks.

---

## 4. Notification Settings, Encrypted Secrets & Email Delivery

**Source modules:**
- [`backend/app/notifications/config.py`](../backend/app/notifications/config.py)
- [`backend/app/notifications/settings_store.py`](../backend/app/notifications/settings_store.py)
- [`backend/app/notifications/secrets.py`](../backend/app/notifications/secrets.py)
- [`backend/app/notifications/service.py`](../backend/app/notifications/service.py)
- [`backend/app/notifications/transports.py`](../backend/app/notifications/transports.py)
- [`backend/app/api/v1/notifications.py`](../backend/app/api/v1/notifications.py)
- [`frontend/src/app/(app)/settings/page.tsx`](../frontend/src/app/(app)/settings/page.tsx)
- [`frontend/src/app/(app)/error.tsx`](../frontend/src/app/(app)/error.tsx)

```mermaid
---
title: "Notification Settings, Encrypted Secrets and Email Delivery"
---
stateDiagram-v2
  state "Legend" as legend {
    lg0: unconfigured
    lg1: readyDisabled
    lg2: readyEnabled
    lg3: broken
    lg4: Breaks SettingsPageLoadsAfterJwtRotation
    lg5: Path to the SettingsPageLoadsAfterJwtRotation bug
  }
  class lg0 tan
  class lg1 blue
  class lg2 teal
  class lg3 orange
  class lg4 breaks
  class lg5 bugPath
  state "Unconfigured (Env Fallback)" as s0 {
    s1: Settings Page Closed
    s2: Settings Page Open
  }
  state "Configured, Alerts Off" as s3 {
    s4: Saved in DB (Alerts Off)
    s5: Test Email Accepted (204)
  }
  state "Configured, Alerts On" as s6 {
    s7: Saved in DB (Alerts On)
    s8: Incident Email Sent
    s9: Provider Error Logged (Check Kept)
  }
  state "JWT Rotated (Undecryptable)" as s10 {
    s11: Secret Undecryptable (Re-login Needed)
    s12: Settings Page Crashes (503)
  }
  [*] --> s1
  s1 --> s2: admin opens /settings
  s2 --> s1: admin leaves /settings
  s2 --> s4: admin saves credentials (alerts off)
  s2 --> s7: admin saves credentials (alerts on)
  s4 --> s5: admin sends test email (204)
  s7 --> s8: incident opens or resolves (email sent)
  s7 --> s9: incident email fails (logged, check kept)
  s11 --> s12: admin opens /settings (503 load failure)
  s8 --> s9: incident email fails (logged, check kept)
  s8 --> s7: admin sends test email (204)
  s9 --> s8: incident opens or resolves (email sent)
  s9 --> s7: admin sends test email (204)
  s12 --> s11: closes error page
  s3 --> s7: admin saves credentials (alerts on) or admin enables alerts (keeps secret)
  s3 --> s11: JWT_SECRET rotates
  s6 --> s4: admin saves credentials (alerts off) or admin disables alerts (keeps secret)
  s6 --> s11: JWT_SECRET rotates
  classDef breaks fill:#ffecee,stroke:#e72e3b,stroke-width:2.5px,color:#cd2834
  class s1 tan
  class s1 bugPath
  class s2 tan
  class s2 bugPath
  class s4 blue
  class s4 bugPath
  class s5 blue
  class s7 teal
  class s8 teal
  class s9 teal
  class s11 orange
  class s11 bugPath
  class s12 orange
  class s12 breaks
  class s12 bugPath
```

### Verification Summary
- **Model size:** 34 states, 189 steps (chart draws 9 states and 17 arrows).
- **Rules that hold:** `TypeOK`, `NoAlertSentWhenDisabled`, `NoSendWhenUnconfiguredOrUndecryptable`, `NoDeadlock`.
- **Broken rule (replayed and confirmed against backend code):**
  - `SettingsPageLoadsAfterJwtRotation` (at `Settings Page Crashes (503)`): `0. Unconfigured (Env Fallback) / Settings Page Closed` -> `1. admin opens /settings` -> `2. admin saves credentials (alerts off)` -> `3. JWT_SECRET rotates` -> `4. admin opens /settings (503 load failure)`. `GET /api/v1/notifications/settings` attempts to decrypt the active provider's stored secret and raises `HTTP 503`, causing the Next.js `/settings` Server Component to render `error.tsx` instead of the settings form where the admin could re-enter the secret.
- **Hidden in chart:** `SendTestEmail` when returning `502`/`503` without changing state, `WorkerIncidentAlert` when skipped, and no-op saves that keep the same `enabled` value.
- **Model scope:** Leaves out per-provider field validation (`smtp`, `brevo`, `mailgun`, `mailtrap`), switching providers while an unused provider's secret is undecryptable, and direct `PATCH /api/v1/notifications/settings` API calls outside the UI.
