# System and module statecharts

This document records the four TLA+ and TLC statechart verifications against `main` (`1572bf2`).

To regenerate any chart from its spec, view, and config in the scratch folder, run `statechart` with a fresh `--out` directory:

```sh
TLA2TOOLS=.../tools/tla2tools.jar JAVA=/opt/homebrew/opt/openjdk@17/bin/java \
  ~/.gemini/config/plugins/pstack/skills/statechart/scripts/statechart \
  <SPEC.tla> --config <SPEC.cfg> --view <VIEW.ts> --out <OUT_DIR>
```

---

## 1. Monitor health, 2-strike rule, and incident lifecycle

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
  }
  class lg0 tan
  class lg1 teal
  class lg2 yellow
  class lg3 orange
  class lg4 purple
  s0: Not Created
  state "Active" as s1 {
    s2: Pending Check
    s3: Healthy (UP)
    s4: 1st Strike (DEGRADED)
    s5: Incident Open (DOWN)
  }
  s6: Paused (Pending)
  [*] --> s0
  s0 --> s2: admin creates monitor
  s2 --> s6: admin pauses (resets to pending)
  s2 --> s3: probe succeeds
  s2 --> s4: 1st failure (5s retry scheduled)
  s6 --> s0: admin deletes monitor
  s6 --> s2: admin resumes (resets to pending, due now)
  s3 --> s2: admin edits target (resets to pending)
  s3 --> s6: admin pauses (resets to pending)
  s3 --> s4: 1st failure (5s retry scheduled)
  s4 --> s2: admin edits target (resets to pending)
  s4 --> s6: admin pauses (resets to pending)
  s4 --> s3: probe succeeds
  s4 --> s5: 2nd failure (opens incident, sends DOWN email)
  s5 --> s2: admin edits target (resets to pending, resolves incident)
  s5 --> s6: admin pauses (resets to pending, resolves incident)
  s5 --> s3: probe succeeds (resolves incident, sends UP email)
  s1 --> s0: admin deletes monitor
  class s0 tan
  class s2 teal
  class s3 teal
  class s4 yellow
  class s5 orange
  class s6 purple
```

### Verification summary
- **Model size.** TLC reached 6 states and 24 steps. The chart draws 6 states and 17 arrows, and skips 4 steps that stay in one chart state.
- **Rules that hold.** `TypeOK`, `OpenIncidentOnlyWhenActiveDown`, `ActiveDownHasOpenIncident`, `ActiveDownRequiresTwoFailures`, `DegradedRequiresOneFailure`, `PendingHasNoIncident`, `PausedResetsToPending`, and `NoDeadlock`.
- **Lifecycle behavior.** Pausing, resuming, or editing target fields runs `plan_lifecycle_transition` and `_apply_lifecycle_transition` in `backend/app/api/v1/monitors.py`, which set `current_status` to `PENDING`, reset `consecutive_failures` to `0`, and resolve open incidents.
- **Model scope.** Models a single monitor lifecycle. Leaves out multi-monitor concurrency, time-series `monitor_checks` logging, `ssl_days_remaining` caching, and `HEAD` keyword warnings.

---

## 2. Scheduler and CheckRunner concurrency

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

### Verification summary
- **Model size.** TLC reached 24 states and 82 steps. The chart draws 6 states and 15 arrows, skips 16 self-loop steps, and hides 26 steps in the view.
- **Rules that hold.** `TypeOK`, `IdleHasNoInflight`, `NoStaleWrite`, `NotifyOnlyAfterCommit`, and `NoDeadlock`.
- **Hidden in chart.** `RejectWhenUnavailable`, `RejectConcurrentRun` (`CheckAlreadyRunning`, HTTP `409`), and `AdminEditsTarget` outside `probing`.
- **Model scope.** Models single-process `CheckRunner` admission, `TargetSnapshot` validation, and `WITH FOR UPDATE` commit guards. Leaves out `asyncio.Semaphore(20)` queuing across monitors, dedicated SSL thread-pool timeouts, the 1 MiB response body cap in `prober.py`, and multi-process replica races.

---

## 3. Auth, token versioning, and RBAC guardrails

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

### Verification summary
- **Model size.** TLC reached 47 states and 240 steps. The chart draws 9 states and 20 arrows, skips 124 self-loop steps, and hides 47 steps in the view.
- **Rules that hold.** `TypeOK`, `AlwaysOneActiveAdmin`, `InactiveUserNeverAuthenticates`, `StaleTokensNeverAuthenticate`, and `NoDeadlock`.
- **Hidden in chart.** Bootstrap admin role changes (`AdminDemoteOrDeactivateA` and `AdminRestoreA`), re-login while a valid cookie already exists, deactivating a logged-out user, and reactivating directly into a pre-existing valid token state.
- **Model scope.** Models two users (the seeded admin and a second user), cookie and bearer logout behavior, `token_version` invalidation, the `users_admin_guard` last-admin check, and SSR route guards. Leaves out JWT expiration, legacy tokens without `ver`, bcrypt validation, and `COOKIE_SECURE` startup checks.

---

## 4. Notification settings, encrypted secrets, and email delivery

**Source modules:**
- [`backend/app/notifications/config.py`](../backend/app/notifications/config.py)
- [`backend/app/notifications/settings_store.py`](../backend/app/notifications/settings_store.py)
- [`backend/app/notifications/secrets.py`](../backend/app/notifications/secrets.py)
- [`backend/app/notifications/service.py`](../backend/app/notifications/service.py)
- [`backend/app/notifications/transports.py`](../backend/app/notifications/transports.py)
- [`backend/app/api/v1/notifications.py`](../backend/app/api/v1/notifications.py)
- [`frontend/src/app/(app)/settings/page.tsx`](../frontend/src/app/(app)/settings/page.tsx)
- [`frontend/src/components/settings/notification-settings-view.tsx`](../frontend/src/components/settings/notification-settings-view.tsx)
- [`frontend/src/components/settings/notification-provider-fields.tsx`](../frontend/src/components/settings/notification-provider-fields.tsx)

```mermaid
---
title: "Notification Settings, Encrypted Secrets and Email Delivery"
---
stateDiagram-v2
  state "Legend" as legend {
    lg0: unconfigured
    lg1: readyDisabled
    lg2: readyEnabled
    lg3: recovery
  }
  class lg0 tan
  class lg1 blue
  class lg2 teal
  class lg3 yellow
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
    s11: Secret Unreadable (Form Closed)
    s12: Recovery Form Open (Warning Banner)
  }
  [*] --> s1
  s1 --> s2: admin opens /settings
  s2 --> s1: admin leaves /settings
  s2 --> s4: admin saves credentials (alerts off)
  s2 --> s7: admin saves credentials (alerts on)
  s4 --> s5: admin sends test email (204)
  s7 --> s8: incident opens or resolves (email sent)
  s7 --> s9: incident email fails (logged, check kept)
  s11 --> s12: admin opens /settings (200 warning, re-enter secret)
  s8 --> s9: incident email fails (logged, check kept)
  s8 --> s7: admin sends test email (204)
  s9 --> s8: incident opens or resolves (email sent)
  s9 --> s7: admin sends test email (204)
  s12 --> s4: admin re-enters secret and saves (alerts off)
  s12 --> s7: admin re-enters secret and saves (alerts on)
  s12 --> s11: admin leaves /settings
  s3 --> s7: admin saves credentials (alerts on) or admin enables alerts (keeps secret)
  s3 --> s11: JWT_SECRET rotates
  s6 --> s4: admin saves credentials (alerts off) or admin disables alerts (keeps secret)
  s6 --> s11: JWT_SECRET rotates
  class s1 tan
  class s2 tan
  class s4 blue
  class s5 blue
  class s7 teal
  class s8 teal
  class s9 teal
  class s11 yellow
  class s12 yellow
```

### Verification summary
- **Model size.** TLC reached 34 states and 184 steps. The chart draws 9 states and 19 arrows, skips 26 self-loop steps, and hides 68 steps in the view.
- **Rules that hold.** `TypeOK`, `NoAlertSentWhenDisabled`, `NoSendWhenUnconfiguredOrUndecryptable`, `SettingsPageLoadsAfterJwtRotation`, `UndecryptableIsNeverConfigured`, and `NoDeadlock`.
- **Recovery behavior.** When `JWT_SECRET` rotates, `GET /api/v1/notifications/settings` calls `load_notification_settings_snapshot` to return non-secret fields with `configured` set to `false` and `unreadable_secrets` populated. The `/settings` page renders a warning banner so an admin can re-enter the secret and save, while `POST /api/v1/notifications/test` (`HTTP 503`) and `DatabaseNotifier` refuse delivery until recovery finishes.
- **Hidden in chart.** `SendTestEmail` when returning `HTTP 502` or `503` without changing state, `WorkerIncidentAlert` when skipped, and no-op saves that keep `enabled` unchanged.
- **Model scope.** Leaves out per-provider field validation (`smtp`, `brevo`, `mailgun`, `mailtrap`), switching providers while another provider's secret is unreadable, and direct `PATCH /api/v1/notifications/settings` requests that omit a replacement secret (`HTTP 422`).
