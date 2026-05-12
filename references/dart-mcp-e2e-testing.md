# Dart MCP E2E Testing

Dart MCP first. Shell fallback only for project commands that MCP cannot run.

## Trigger

Signals: E2E testing, Dart MCP, flutter_driver, integration_test, source-of-truth verification
Before generating code in this area, output verbatim: `Reading: dart-mcp-e2e-testing.md`


https://docs.flutter.dev/ai/mcp-server

Runtime E2E means real app behavior on a real simulator/device. Static review, screenshots without interactions, widget tests, or one-device happy paths do not prove sync/collaboration/cloud behavior.

## Rules — NEVER Violate

1. MUST use Dart MCP tools before terminal commands.
2. MUST run on the asked device class. iOS request means iOS simulator/device; Android request means Android emulator/device.
3. MUST test the real app entrypoint/config the user asked for. Do not silently switch environments.
4. MUST define actors, devices, accounts, and test data before running remote/shared-state flows.
5. MUST use stable text, semantics, tooltips, or `ValueKey` selectors from the widget tree. NEVER coordinate-tap as the primary selector.
6. MUST wait for semantic UI state or backend/source-of-truth state. NEVER rely on blind sleeps.
7. MUST capture logs after each major flow segment and after every failure.
8. MUST run fail -> fix -> restart/relaunch -> rerun failed segment -> rerun downstream impacted segments.
9. MUST verify source-of-truth state with an admin/API/CLI/read model when remote data is involved.
10. MUST stop app processes and clean test data at end.
11. MUST verify a central widget key registry exists before adding E2E selectors. Default: `lib/core/testing/app_widget_keys.dart` or existing project equivalent.
12. MUST use a deterministic E2E entrypoint when the app needs runtime overrides or Flutter Driver/MCP connectivity. Default: `lib/main_dev.dart` or existing project equivalent.

## Tool Map

| Goal | Tool |
|------|------|
| Set project roots | `mcp_dart_add_roots` |
| Analyze code | `mcp_dart_analyze_files` |
| Auto-fix analyzable issues | `mcp_dart_dart_fix` |
| Format Dart | `mcp_dart_dart_format` |
| List devices | `mcp_dart_list_devices` |
| Launch app | `mcp_dart_launch_app` |
| Run tests | `mcp_dart_run_tests` |
| Hot restart | `mcp_dart_hot_restart` |
| List running apps | `mcp_dart_list_running_apps` |
| Fetch app logs | `mcp_dart_get_app_logs` |
| Inspect widget tree | `mcp_dart_get_widget_tree` |
| Get selected widget | `mcp_dart_get_selected_widget` |
| Pick widget in app | `mcp_dart_set_widget_selection_mode` |
| Stop app | `mcp_dart_stop_app` |
| Remove roots | `mcp_dart_remove_roots` |

## Fast Path

```mermaid
graph LR
  A[add_roots] --> B[analyze_files]
  B --> C[list_devices]
  C --> D[launch app instances]
  D --> E[drive flow]
  E --> F[verify UI + logs]
  F --> G{remote/shared state?}
  G -->|yes| H[verify source of truth + observer]
  G -->|no| I[next segment]
  H --> I
  I --> J{failure?}
  J -->|yes| K[fix + restart/relaunch + rerun segment/downstream]
  K --> E
  J -->|no| L[run tests]
  L --> M[cleanup + stop apps]
```

## Planning Matrix

Choose the smallest matrix that proves the feature:

| Feature kind | Required runtime proof |
|---|---|
| Local-only UI/form | One app instance, create/edit/delete/error/empty, relaunch if persisted |
| Remote CRUD | One app instance plus source-of-truth verification after create/update/delete |
| Sync/realtime/cache invalidation | Writer app + observer app, observer updates without manual refresh |
| Collaboration/team/chat/shared document | Two actors or two app instances minimum; ownership/member/removal/destructive paths |
| Invite/code/link/token/slug/order generated remotely | Verify generated value in source of truth, then UI shows same value after mutation |
| Permissions/auth gates | Allowed actor succeeds, denied/removed actor sees blocked or fallback state |
| Offline/retry/persistence | Disconnect or simulate failure when feasible, relaunch, retry, and verify no duplicate writes |

## End-to-End Loop

1. Add project root once.
2. Analyze before launch. Fix clear compile/analyzer issues first.
3. List devices and pick the requested simulator/device class.
4. Launch every app instance needed for the matrix.
5. Get widget tree before interacting on each screen. Select by stable text/semantics/key.
6. Start from a known state: signed-out/signed-in actor, clean route, known backend/source-of-truth data.
7. Run one segment at a time: setup, create, observe, update, observe, destructive/remove, relaunch, cleanup.
8. After each segment, verify UI state, logs, and remote/source-of-truth state when applicable.
9. On failure, capture logs, patch the smallest root cause, hot restart or relaunch, rerun the failed segment and downstream impacted segments.
10. After all runtime flows pass, run relevant unit/widget tests.
11. Clean test data, sign out if needed, stop all app processes.

## E2E Entrypoint

Use the production app bootstrap, but make test-only startup explicit:

```dart
import 'package:flutter_driver/driver_extension.dart';
import 'package:my_app/main.dart' as app;

const forceSignedOut = bool.fromEnvironment('E2E_FORCE_SIGNED_OUT');

Future<void> main() async {
  enableFlutterDriverExtension();
  await app.runAppRoot(overrides: [
    if (forceSignedOut) authProvider.overrideWith(SignedOutAuthNotifier.new),
  ]);
}
```

Rules:

- Keep test-only overrides out of `main.dart`.
- Prefer `--dart-define` flags for known app states: signed out, onboarding incomplete, update required, disabled notifications.
- Do not mock the feature under test in the E2E entrypoint.
- Launch the target file explicitly: `flutter run -t lib/main_dev.dart`.

## Journey Checklist Template

Copy this per feature.

- Entry route opens from cold launch
- Auth/account state is known
- Empty/loading/error states render
- Primary create path works
- Source of truth contains created data
- Observer sees create without manual refresh when shared/sync applies
- Update/edit path works
- Observer sees update without manual refresh when shared/sync applies
- Delete/remove/leave/revoke path works
- Observer or removed actor sees correct fallback/empty/blocked state
- Generated values shown in UI equal source-of-truth values
- Back/deep-link/reopen path works
- Persisted data survives app restart when persistence applies
- No new critical logs, assertions, unhandled exceptions, or permission errors
- Test data cleaned

## Multi-Actor / Sync Protocol

Use this for teams, squads, chat, shared documents, shared lists, invitations, realtime dashboards, multiplayer, collaborative editing, or any remote state expected to appear elsewhere.

1. Actor A creates parent resource.
2. Verify parent in source of truth.
3. Actor B joins/gets access.
4. Verify membership/access in source of truth.
5. Actor A creates child/shared item.
6. Actor B sees item without manual refresh.
7. Actor A updates/renames/reorders/status-changes item.
8. Actor B sees exact update without manual refresh.
9. Actor B performs allowed mutation.
10. Actor A sees it without manual refresh.
11. Actor A removes Actor B or deletes child/parent.
12. Actor B sees blocked/empty/fallback state without stale detail screen.
13. Relaunch both apps and verify final state still correct.
14. Clean all created data.

## Source-of-Truth Verification

Use the project's real backend/admin read path, local database inspector, CLI, emulator API, or service SDK. Keep this generic; do not bake one vendor into the skill.

Verify:

- IDs used by the app match transport/source-of-truth IDs where required.
- Generated fields, counters, order indexes, invites, slugs, and membership rows are current.
- Deleted/removed records are actually gone or marked inactive as designed.
- Observer permissions match final state.
- No duplicate records were created by retry/relaunch.

## Harness Quality

- Every phase starts from a known screen and account.
- Close overlays, dialogs, keyboards, snackbars, and sheets before the next phase.
- Prefer `ValueKey`, semantics labels, exact visible text, or tooltip selectors.
- Add deterministic keys from the central key registry when a real user-visible selector is ambiguous.
- No inline string `ValueKey`s in widgets/tests/E2E harnesses.
- Record screenshots only as evidence after behavior checks; screenshots are not the test by themselves.
- Logs are part of assertions: check for critical errors even when UI looks correct.
- Test data names include a run id/timestamp so cleanup is safe.

## Failure Triage

- Assertion in logs: fix state/lifecycle first.
- Backend write fail: check datasource id contract, auth/permission, environment, and payload schema.
- Observer stale: check event contract, exact subscriptions, source-of-truth refetch, provider invalidation/sync, and actor permissions.
- Widget not tappable: inspect tree, add deterministic key/semantics, retest.
- Generated value stale: force source-of-truth refresh after mutation and before navigation/success.
- Removed actor still sees detail: clear selected state, route fallback, and invalidate/refetch affected providers.
- Duplicate data after retry/relaunch: fix idempotency, mutation pending state, and cleanup.

## Exit Criteria

1. All target journeys pass on the requested device class.
2. Remote/shared flows pass with writer + observer app instances when applicable.
3. Source-of-truth verification matches UI.
4. Create/update/delete/remove/relaunch paths pass.
5. No new critical log errors.
6. Relevant tests pass after final runtime fix pass.
7. Test data cleaned.
8. All app processes stopped.

## Recap

1. MUST use Dart MCP tools (hot restart, screenshot, tap, input, log inspection) before falling back to shell commands — shell fallback is only for project commands MCP cannot run.
2. MUST wait for semantic UI state or backend/source-of-truth state — NEVER use blind `sleep` or fixed-duration waits. Waits must be conditional on observable state.
3. MUST verify source-of-truth state with an admin/API/CLI/read model when remote data is involved. UI-only verification is insufficient for sync/collaboration/cloud behavior.

