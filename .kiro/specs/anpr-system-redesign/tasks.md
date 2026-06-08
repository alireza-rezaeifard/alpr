# Implementation Plan: ANPR System Redesign

## Overview

This plan implements the ANPR system redesign in incremental, test-driven steps. The backend is
Python (FastAPI + SQLite), reusing the existing detection pipeline, camera manager, and plate
modules; the frontend is Dart/Flutter (Fluent UI + PlutoGrid + Syncfusion + Riverpod + go_router).

Work proceeds bottom-up: first the schema and pure security/licensing logic, then the FastAPI
dependency chain that wires them in, then the new domain features (watchlists, audit, retention,
export) hooked into the preserved detection/camera/reporting code, and finally the Persian RTL
Flutter client. Each parent task ends with integration that connects new code into the running app.
Property tests are placed next to the logic they validate so correctness is caught early.

## Tasks

- [x] 1. Extend database schema and shared Pydantic models
  - [x] 1.1 Add new tables and config keys to `db.py`
    - Extend the idempotent `init_db()` to create `users`, `revoked_tokens`, `licenses`,
      `watchlists`, `watchlist_entries`, `alerts`, and `audit_log` tables plus the
      `idx_alerts_created`, `idx_audit_ts`, and `idx_wl_entries_norm` indexes
    - Store the retention policy under `app_config` key `retention_days`
    - Reuse the existing connection helpers and `_ensure_column` migration pattern; leave
      `sessions`, `detections`, `cameras`, `app_config` behavior unchanged
    - _Requirements: 1.9, 16.1_

  - [x] 1.2 Add API response envelopes and error model to `schemas.py`
    - Define `LoginResponse`, `UserView`, `LicenseStatus`, `WatchlistView`, `WatchlistEntryView`,
      `AlertView`, `AuditEntryView`, `RetentionConfig`, and the `{ error, code }` error envelope
      with codes (`auth_required`, `auth_failed`, `forbidden`, `license_required`,
      `license_expired`, `license_limit`, `validation_error`, `not_found`, `conflict`)
    - _Requirements: 1.1, 2.7, 3.5_

- [x] 2. Implement authentication core (pure security logic)
  - [x] 2.1 Implement password hashing and session-token functions in `auth/security.py`
    - Implement `hash_password`/`verify_password` using passlib/bcrypt (salted one-way)
    - Implement `create_session_token` (signs `sub`, `role`, `jti`, `iat`, `exp` with HMAC secret)
      and `verify_session_token` (signature, expiry, revocation, account-enabled checks)
    - Implement `revoke_token(jti, exp)` backed by the `revoked_tokens` table
    - _Requirements: 1.1, 1.3, 1.4, 1.5, 1.7_

  - [x] 2.2 Write property test for password hashing
    - **Property 1: Password hashing is a one-way, salted round-trip**
    - **Validates: Requirements 1.3**

  - [x] 2.3 Write property test for valid token round-trip
    - **Property 2: Valid session tokens round-trip to the issuing identity**
    - **Validates: Requirements 1.1, 1.4**

  - [x] 2.4 Write property test for invalid/expired/revoked token rejection
    - **Property 3: Invalid session tokens are always rejected**
    - **Validates: Requirements 1.2, 1.5, 1.7**

  - [x] 2.5 Write property test for disabled-account rejection
    - **Property 4: Disabled accounts cannot authenticate**
    - **Validates: Requirements 1.8**

- [x] 3. Implement RBAC permission resolution
  - [x] 3.1 Implement role→permission mapping and resolver in `auth/rbac.py`
    - Define `Role`, `Permission`, and the `ROLE_PERMISSIONS` matrix (Viewer ⊆ Operator ⊆ Admin,
      Admin holds all permissions)
    - Implement `role_has_permission(role, permission)` as a pure function
    - _Requirements: 2.1, 2.5, 2.6, 2.7_

  - [x] 3.2 Write property test for permission resolution
    - **Property 5: Authorization permits an action exactly when the role holds the permission**
    - **Validates: Requirements 2.2, 2.3, 2.5, 2.6, 2.7**

- [x] 4. Implement licensing core (pure key logic)
  - [x] 4.1 Implement license key decode/validate in `licensing/license_key.py`
    - Implement `decode_license_key(key)` (base64url JSON claims + HMAC verify) returning
      `LicenseClaims` (expiry, camera_limit) or `None`
    - Implement `is_license_valid(now)` true only when an active, unexpired license exists
    - _Requirements: 3.1, 3.2, 3.4_

  - [x] 4.2 Write property test for license key round-trip and validity
    - **Property 8: License keys round-trip and validity respects expiry**
    - **Validates: Requirements 3.1, 3.2, 3.4**

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Wire the security perimeter into FastAPI
  - [x] 6.1 Implement auth/license/permission dependencies in `auth/dependencies.py`
    - Implement `current_user()` (extract Bearer token, verify, load user, raise `401` for
      missing/expired/invalid/revoked/disabled)
    - Implement `require_permission(permission)` factory raising `403` when the role lacks it, and
      ensuring permission-less protected endpoints still depend on `current_user()`
    - Implement `require_license()` raising `license_required`/`license_expired`/`license_limit`
      for detection and camera-start paths
    - _Requirements: 1.4, 1.5, 1.6, 2.2, 2.3, 2.4, 3.3, 3.4, 3.6, 3.7_

  - [x] 6.2 Implement auth router and default-admin bootstrap in `routers/auth.py`
    - Implement `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`
    - On `init_db()` (no users), create one default Admin account
    - Login returns `LoginResponse` with token, role, expiry, and permission set
    - _Requirements: 1.1, 1.2, 1.7, 1.8, 1.9_

  - [x] 6.3 Write unit tests for auth router edge cases
    - Missing-token rejection, default-admin bootstrap, login failure outcomes
    - _Requirements: 1.6, 1.9_

- [x] 7. Implement user and license management services
  - [x] 7.1 Implement user management service and router in `routers/users.py`
    - Implement `POST /api/users` (require username, initial password, role), `GET /api/users`,
      `PATCH /api/users/{id}` (role, enable/disable, password), `DELETE /api/users/{id}`
    - Apply new role permissions to subsequent requests; reject deleting/disabling the last
      enabled Admin
    - Guard with `require_permission("manage_users")`
    - _Requirements: 2.8, 2.9, 2.10_

  - [x] 7.2 Write property test for role-change effect
    - **Property 6: Role changes take effect on subsequent authorization checks**
    - **Validates: Requirements 2.9**

  - [x] 7.3 Write property test for last-admin protection
    - **Property 7: The last enabled Admin cannot be removed**
    - **Validates: Requirements 2.10**

  - [x] 7.4 Write unit test for create-user validation
    - Required username/password/role and role enumeration
    - _Requirements: 2.1, 2.8_

  - [x] 7.5 Implement license service and router in `licensing/service.py` and `routers/licenses.py`
    - Implement `activate_license(key)`, `get_license_status()` (state, expiry, camera limit,
      configured-camera count), and the camera-limit check used by `require_license()`
    - Implement `POST /api/licenses/activate` and `GET /api/licenses/status`, both reachable while
      no license exists
    - _Requirements: 3.1, 3.2, 3.5, 3.6, 3.7_

  - [x] 7.6 Write property test for camera-start license limit
    - **Property 9: Camera starts never exceed the license camera limit**
    - **Validates: Requirements 3.6**

  - [x] 7.7 Write unit test for license status shape and reachability
    - Status fields and no-license reachability of auth/activate/status
    - _Requirements: 3.5, 3.7_

- [~] 8. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Protect and extend camera management and streaming
  - [x] 9.1 Add validation and guards to camera CRUD in `db.py` and `routers/cameras.py`
    - Persist/return camera with assigned id; list with status; update name/URL/skip-frame;
      not-found on unknown id; delete stops processor, closes session, removes record
    - Restrict skip-frame to 1..1000; restore cameras to last-known status on startup
    - Guard with `require_permission("manage_cameras")` and, for start, `require_license()` plus
      the license camera-limit check before the manager's concurrency check
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 3.6_

  - [x] 9.2 Write property test for camera persistence round-trip
    - **Property 10: Camera create/update is a persistence round-trip**
    - **Validates: Requirements 4.1, 4.3**

  - [x] 9.3 Write property test for skip-frame range validation
    - **Property 11: Skip-frame values are accepted exactly within 1..1000**
    - **Validates: Requirements 4.7, 9.6**

  - [x] 9.4 Wire concurrency-limit configuration and guards for the camera manager
    - Add `require_permission("manage_config")`-guarded concurrency-limit setter persisting
      values in 1..64 and rejecting out-of-range; expose start/stop/start-all/stop-all routes
    - Preserve existing `CameraManager` FIFO/error-isolation behavior
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8_

  - [x] 9.5 Write property test for concurrency invariant and FIFO promotion
    - **Property 12: The camera manager never exceeds its concurrency limit and promotes FIFO**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.8**

  - [x] 9.6 Write property test for concurrency-limit range
    - **Property 13: The concurrency limit is accepted exactly within 1..64**
    - **Validates: Requirements 5.6, 5.7**

  - [x] 9.7 Write integration tests for camera/stream side-effects
    - Camera delete/error side-effects (stop processor, close session, promote queue), MJPEG and
      latest-frame delivery behind the view permission, unknown-id not-found
    - _Requirements: 4.5, 5.8, 6.1, 6.2, 6.3_

- [x] 10. Protect network scanner endpoints
  - [x] 10.1 Add auth guards and conflict handling to `routers/scanner.py`
    - Guard scan start/status/stop and test-URL with `current_user()` and the appropriate
      permission; reject starting a scan while one is running with a conflict response
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [x] 10.2 Write integration test for scanner probe/record/stop and conflict
    - Probe/record/stop/test-url flows and scan-already-running conflict
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [x] 11. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Implement plate formatting/classification property coverage (preserved modules)
  - [x] 12.1 Write property test for digit normalization
    - **Property 14: Digit normalization is canonical across scripts**
    - **Validates: Requirements 11.2, 12.7**

  - [x] 12.2 Write property test for pretty-printer output in responses
    - **Property 15: The pretty-printer always yields a Persian plate string included in responses**
    - **Validates: Requirements 11.1, 8.5**

  - [x] 12.3 Write property test for total, structure-driven classification
    - **Property 16: Plate classification is total and structure-driven**
    - **Validates: Requirements 11.3, 11.4, 11.5**

  - [x] 12.4 Write property test for parse/format round-trip
    - **Property 17: Plate parse/format round-trip preserves components**
    - **Validates: Requirements 11.7**

  - [x] 12.5 Write property test for free-zone note
    - **Property 18: Free-zone plates carry the free-zone note**
    - **Validates: Requirements 11.6**

- [ ] 13. Hook detection persistence into watchlist matching and Persian formatting
  - [x] 13.1 Implement watchlist matching logic in `watchlist/matching.py`
    - Implement `normalize_for_match(value)` (digit normalization + separator stripping),
      `find_matches(plate_value, active_entries)` (only non-deleted entries), and
      `create_alert(detection, entry)`
    - _Requirements: 12.4, 12.5, 12.7_

  - [x] 13.2 Implement watchlist CRUD service and routers in `watchlist/service.py` and `routers/watchlists.py`
    - Implement create watchlist (name, list type), add entry (plate value, optional label/reason),
      remove entry, list watchlists, and `GET /api/alerts` returning most-recent-first
    - Guard with `require_permission("manage_watchlists")`; alerts viewable with the view permission
    - _Requirements: 12.1, 12.2, 12.3, 12.6_

  - [x] 13.3 Add watchlist + Persian-format hooks at the detection save point
    - In the `save_detection` path used by image/video/RTSP runs, format the plate via
      `format_plate_persian` and run watchlist matching to create alerts on matches
    - Ensure detections are stored under their originating session and appear in live recent-history
    - _Requirements: 8.3, 8.5, 10.4, 6.4, 12.4_

  - [-] 13.4 Write property test for watchlist entry persistence round-trip
    - **Property 19: Watchlist entry create/remove is a persistence round-trip**
    - **Validates: Requirements 12.1, 12.2, 12.3**

  - [-] 13.5 Write property test for match-on-detection alert creation
    - **Property 20: Detections matching an active watchlist entry raise exactly one referencing alert**
    - **Validates: Requirements 12.4, 12.5, 12.7**

  - [-] 13.6 Write property test for alert ordering
    - **Property 21: Alerts are returned most-recent-first**
    - **Validates: Requirements 12.6**

  - [-] 13.7 Write property test for detection-session persistence
    - **Property 22: Detections are persisted under their originating session**
    - **Validates: Requirements 8.3, 10.4, 6.4**

- [ ] 14. Protect and verify detection endpoints (image/video/RTSP)
  - [-] 14.1 Add auth/permission/license guards to detection routers in `routers/detection.py`
    - Guard image (Req 8), video (Req 9), and RTSP (Req 10) endpoints with `current_user()`,
      `require_permission("run_detection")`, and `require_license()`
    - Enforce video skip-frame 1..1000, undecodable-image validation error, atomic per-image
      persistence (whole request fails if storing detection records fails), and not-found for
      unknown task ids
    - _Requirements: 8.1, 8.2, 8.4, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 10.1, 10.2, 10.3_

  - [x] 14.2 Write integration tests for detection pipeline wiring
    - Image/video/RTSP run wiring, undecodable image, atomic-storage failure, unknown-task
      not-found, video task status/stop/complete
    - _Requirements: 8.1, 8.2, 8.4, 9.1, 9.2, 9.3, 9.4, 9.5, 10.1, 10.2, 10.3_

- [~] 15. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 16. Implement reporting, export, audit, and retention
  - [x] 16.1 Add reporting routers over preserved `db.py` queries in `routers/reports.py`
    - Expose detections list (limit 1..1000, offset, source-type filter, search + total), timeline
      (days 1..90), aggregate stats, source distribution, confidence distribution, and session
      history (most-recent-first), all behind the view permission
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7_

  - [~] 16.2 Write property test for detection query correctness
    - **Property 23: Detection queries return exactly the matching records and total**
    - **Validates: Requirements 13.1**

  - [~] 16.3 Write property test for bounded/complete reporting ranges
    - **Property 24: Reporting range parameters are bounded and complete**
    - **Validates: Requirements 13.2, 13.3**

  - [~] 16.4 Write property test for distribution partitioning
    - **Property 25: Distribution groupings partition the detection set**
    - **Validates: Requirements 13.5, 13.6**

  - [~] 16.5 Write property test for session-history ordering
    - **Property 26: Session history is returned most-recent-first**
    - **Validates: Requirements 13.7**

  - [x] 16.6 Implement CSV export in `export/csv_export.py` and `routers/export.py`
    - Implement `build_detection_csv(rows)` with fixed header (timestamp, source type, DTRB text,
      Persian plate, confidence), camera-name column when any row is camera-sourced, and
      header-only output for empty results; expose `GET /api/export/detections`
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

  - [~] 16.7 Write property test for export content and camera-name rule
    - **Property 27: Export reflects matches, required fields, and the camera-name rule**
    - **Validates: Requirements 14.1, 14.2, 14.3, 14.4**

  - [x] 16.8 Implement append-only audit logging in `audit/service.py` and `routers/audit.py`
    - Implement `write_audit(user, action, resource, outcome)` called at login/logout and on
      create/update/delete of cameras, users, watchlists, licenses; implement `list_audit(limit)`
      (limit>0 returns that many, limit==0 returns all, most-recent-first); expose no update/delete
    - Guard the audit-read endpoint with `require_permission("view_audit")`
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5_

  - [~] 16.9 Write property test for audit append completeness
    - **Property 28: Auditable actions always append a complete audit entry**
    - **Validates: Requirements 15.1, 15.2**

  - [~] 16.10 Write property test for audit retrieval limit/ordering
    - **Property 29: Audit retrieval honors limit and most-recent-first ordering**
    - **Validates: Requirements 15.3, 15.4**

  - [~] 16.11 Write unit test for audit immutability
    - Reject any modify/delete of existing audit rows
    - _Requirements: 15.5_

  - [x] 16.12 Implement retention policy and pruning in `retention/policy.py`, `retention/service.py`, `routers/retention.py`
    - Implement `set_retention_policy(days)` (persist days>0, reject days<=0), `retention_cutoff`,
      and `prune_detections(now)` (delete older than cutoff when policy active, retain all when
      none); expose `GET/PUT /api/config/retention` behind `require_permission("manage_config")`
    - _Requirements: 16.1, 16.2, 16.3, 16.4_

  - [~] 16.13 Write property test for retention pruning
    - **Property 30: Retention pruning removes exactly the records older than the cutoff**
    - **Validates: Requirements 16.1, 16.2, 16.3, 16.4**

- [x] 17. Assemble the FastAPI app and wire all routers
  - [x] 17.1 Compose the app and lifespan in `api.py`
    - Include all routers (auth, users, licenses, cameras, detection, scanner, watchlists, alerts,
      reports, export, audit, retention), run `init_db()` + default-admin bootstrap + camera
      restore on startup, and schedule the retention pruning background task
    - _Requirements: 1.9, 4.6, 16.2_

- [~] 18. Checkpoint - Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 19. Build the Persian RTL Flutter client foundation
  - [x] 19.1 Configure RTL/Persian app shell and dependencies in `flutter_app/`
    - Add Fluent UI, PlutoGrid, Syncfusion, Riverpod, go_router, dio deps; set `Directionality.rtl`,
      Persian locale, and the Vazirmatn font globally; build the shared Fluent scaffold with a
      Persian `NavigationPane`
    - _Requirements: 17.1, 17.2, 17.3_

  - [x] 19.2 Implement Dart models and the `PersianFormat` helper in `lib/data/models/`
    - Implement immutable models (`UserAuth`, `LicenseStatus`, `Watchlist`, `Alert`, `AuditEntry`,
      `Session`, etc.) with `fromJson`/`toJson`, and a `PersianFormat` helper for Persian-digit
      number/date/time formatting
    - _Requirements: 17.4_

  - [~] 19.3 Write Dart property test for Persian-locale formatting round-trip
    - **Property 31: Persian-locale formatting round-trips numbers and dates**
    - **Validates: Requirements 17.4**

  - [x] 19.4 Implement the Dio API client, token interceptor, and auth state
    - Implement the Dio client with a Bearer-token interceptor that attaches the stored token and,
      on `401`, clears it and triggers a redirect to login; implement `authProvider`/`sessionProvider`
    - _Requirements: 18.2, 18.3_

  - [~] 19.5 Implement go_router redirect guard and login flow
    - Configure `go_router` `redirect` consulting `authProvider` to force unauthenticated users to
      `/login`; on successful auth store the token and navigate to the dashboard; route navigation
      preserves the authenticated session
    - _Requirements: 18.1, 18.2, 18.5_

  - [~] 19.6 Write widget tests for routing, RTL, and the 401 interceptor
    - RTL root layout, redirect/login flow, and 401-clears-token-and-redirects behavior
    - _Requirements: 17.2, 18.1, 18.2, 18.3, 18.5_

- [ ] 20. Build feature screens with permission-aware controls
  - [x] 20.1 Implement repositories and controllers for each feature
    - Implement repositories wrapping the Dio client and Riverpod controllers for auth, cameras,
      detection, reports, watchlists/alerts, users, licenses, audit, and settings
    - _Requirements: 18.4, 18.5_

  - [~] 20.2 Implement tabular and analytics screens
    - Build Cameras, Detections/History, Sessions, Watchlists & Alerts, Users, and Audit screens
      using PlutoGrid (sorting/column controls); build Dashboard and Analytics with Syncfusion
      charts/gauges; add the export button on the history screen
    - _Requirements: 17.5, 17.6_

  - [~] 20.3 Implement detection, live monitoring, license, and settings screens with permission gating
    - Build Detection (image/video/RTSP), Live Monitoring (MJPEG), License (activate/status), and
      Settings (concurrency/retention) screens; hide or disable controls whose action the current
      role lacks based on the permission set returned at login
    - _Requirements: 6.1, 6.2, 18.4_

  - [~] 20.4 Write widget tests for grids, charts, and permission gating
    - PlutoGrid presence on tabular screens, Syncfusion chart/gauge presence on analytics, and
      permission-gated control visibility per role
    - _Requirements: 17.5, 17.6, 18.4_

- [~] 21. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP; they cover unit,
  property, and integration/widget tests.
- Each task references specific requirements (granular clauses) for traceability.
- Property tests use Hypothesis (backend) and a Dart property approach (frontend), run a minimum of
  100 examples, and carry a `Feature: anpr-system-redesign, Property {n}` tag comment.
- Property tests touching the database use a temporary SQLite fixture; those touching the camera
  manager use a mocked processor so logic is tested without real RTSP I/O or ML inference.
- Checkpoints provide incremental validation breaks; the detection pipeline, camera manager, and
  plate modules are preserved and only wrapped/hooked rather than rewritten.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "3.1", "4.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4", "2.5", "3.2", "4.2"] },
    { "id": 3, "tasks": ["6.1"] },
    { "id": 4, "tasks": ["6.2", "7.1", "7.5"] },
    { "id": 5, "tasks": ["6.3", "7.2", "7.3", "7.4", "7.6", "7.7", "9.1", "9.4", "10.1"] },
    { "id": 6, "tasks": ["9.2", "9.3", "9.5", "9.6", "9.7", "10.2", "13.1", "13.2"] },
    { "id": 7, "tasks": ["13.3", "12.1", "12.2", "12.3", "12.4", "12.5"] },
    { "id": 8, "tasks": ["13.4", "13.5", "13.6", "13.7", "14.1"] },
    { "id": 9, "tasks": ["14.2", "16.1", "16.6", "16.8", "16.12"] },
    { "id": 10, "tasks": ["16.2", "16.3", "16.4", "16.5", "16.7", "16.9", "16.10", "16.11", "16.13"] },
    { "id": 11, "tasks": ["17.1"] },
    { "id": 12, "tasks": ["19.1", "19.2"] },
    { "id": 13, "tasks": ["19.3", "19.4"] },
    { "id": 14, "tasks": ["19.5", "20.1"] },
    { "id": 15, "tasks": ["19.6", "20.2", "20.3"] },
    { "id": 16, "tasks": ["20.4"] }
  ]
}
```
