# Dart MCP E2E Testing


## Read first

1. Use Dart MCP before shell. Shell fallback only for project cmds MCP cannot run.
2. Use requested device class, app entrypoint, env, actors, accounts, data.
3. Select by semantics/text/tooltips/central `ValueKey`; no coordinate-tap primary selectors.
4. Wait on observable UI/backend state, never blind sleep.
5. Verify source-of-truth via admin/API/CLI/read model for remote/shared state.
6. Keep the target app and host driver separate. The target may use Flutter and app code. The host driver must stay in its host-side API and Dart code.
7. Label every run `clean` or `preserved` and record that state in its receipt.

## Trigger

Signals: E2E testing, Dart MCP, flutter_driver, integration_test, source-of-truth verification


https://docs.flutter.dev/ai/mcp-server

Runtime E2E means real app behavior on a real simulator/device. Static review, screenshots without interactions, widget tests, or one-device happy paths do not prove sync/collaboration/cloud behavior.

## Rules — NEVER Violate

1. MUST use Dart MCP tools before terminal commands.
2. MUST run on the asked device class. iOS request means iOS simulator/device; Android request means Android emulator/device.
3. MUST test the requested app entrypoint/config. Do not switch environments.
4. MUST define actors, devices, accounts, and test data before running remote/shared-state flows.
5. MUST use stable text, semantics, tooltips, or `ValueKey` selectors from the widget tree. NEVER coordinate-tap as the primary selector.
6. MUST wait for semantic UI state or backend/source-of-truth state. NEVER rely on blind sleeps.
7. MUST capture logs after each major flow segment and after every failure.
8. MUST run fail -> fix -> restart/relaunch -> rerun failed segment -> rerun downstream impacted segments.
9. MUST verify source-of-truth state with an admin/API/CLI/read model when remote data is involved.
10. MUST stop app processes and clean test data at end.
11. MUST verify a central widget key registry exists before adding E2E selectors. Default: `lib/core/testing/app_widget_keys.dart` or existing project equivalent.
12. MUST use a deterministic E2E entrypoint when the app needs runtime overrides or Flutter Driver/MCP connectivity. Default: `lib/main_dev.dart` or existing project equivalent.
13. MUST reject an unknown scenario before executing any valid journey; silent fallback to a default scenario is forbidden.
14. MUST fail the run when asserted logs contain a critical error, even if the driver/process exits 0.
15. MUST capture evidence while the app is running on the asserted screen; a screenshot after exit, crash, or navigation away proves nothing.
16. MUST prove the host driver separately with analysis and a host-side compile check before the full target run.
17. MUST wait for a closed modal's old key to be absent before opening another modal that reuses that key.
18. MUST treat native prompts as platform UI. Flutter widget-tree state alone cannot prove a file picker, permission prompt, keyboard, or share sheet completed.
19. MUST write one terminal receipt per scenario. A timeout, lost process, missing receipt, pending timer, pending future, subscription, or callback is a failed or incomplete run.

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

## Planning Matrix

Choose the smallest matrix that proves the feature:

| Feature kind | Required runtime proof |
|---|---|
| Local-only UI/form | One app instance, create/edit/delete/error/empty, relaunch if persisted |
| Remote CRUD | One app instance plus source-of-truth verification after create/update/delete |
| Sync/realtime/cache invalidation | Writer app + observer app, observer updates without manual refresh |
| Collaboration/team/chat/shared document | Two actors or two app instances minimum; ownership/member/removal/destructive paths |
| Invite/code/link/token/slug/order generated remotely | Verify generated value in source of truth, then UI shows same value after mutation |
| Permissions/auth gates | Allowed actor succeeds, denied/revoked actor sees blocked or fallback state |
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
9. On failure, capture logs, patch smallest failing area, hot restart/relaunch, rerun failed + impacted segments.
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

Flutter's current integration-test documentation keeps the app test under
`integration_test/`. When `flutter drive` is used, the host adapter belongs in
`test_driver/`, and the target and host files are separate processes. See the
[integration test guide](https://docs.flutter.dev/testing/integration-tests) and
the [Flutter drive command source](https://github.com/flutter/flutter/blob/master/packages/flutter_tools/lib/src/commands/drive.dart).

## App and host-driver boundary

The app target may import `dart:ui`, Flutter widgets, rendering, material, the
app package, and feature code. The host driver may import `dart:async`,
`dart:io`, `package:test`, `package:flutter_driver` host APIs, or the official
`integration_test_driver` adapter. Its own code and helper closure MUST NOT
import `dart:ui`, `package:flutter/rendering.dart`,
`package:flutter/widgets.dart`, `package:flutter/material.dart`, or the app
package. Do not place app widgets, providers, repositories, or platform plugin
code in `test_driver/`.

Prove the boundary before running the device flow:

```text
dart analyze test_driver
dart compile exe test_driver/<scenario>_test.dart
flutter drive --driver=test_driver/<scenario>_test.dart \
  --target=integration_test/<scenario>_test.dart
```

The compile step must use the project's resolved package configuration. If a
driver needs a Flutter-only helper, move that helper into the target
`integration_test/` file and send only serializable results to the host.

## Clean and preserved restart states

These are different tests and must never be inferred from a screenshot.

`clean` means the exact app installation and its local data were removed by the
platform tool before launch. Verify the app process is gone, the app container
or data directory is gone, and no old test record is present before launch. A
new install must create the container again. Record the platform command and
the verification result. Do not use a generic cache clear when the requirement
is a clean install.

`preserved` means the same installation and local data remain. Do not uninstall,
clear storage, reset the simulator, or recreate the test account between the
write and relaunch phases. Assert the saved record before and after relaunch,
and record an app/data identity at both points.

The current `flutter drive` contract includes `--keep-app-running` and
`--use-existing-app`. The first controls whether Flutter stops the app after
the driver finishes. The second connects to an already running VM service. They
do not, by themselves, prove that app data was preserved. The current command
does not expose `--no-uninstall-first`, so do not add that flag to a command.
Use the platform's documented uninstall or data-reset command only for the
explicit `clean` phase. Capture the exact Flutter tool version and command in
the receipt.

## Gestures, modals, and native prompts

- Scroll a keyed or semantically named scrollable. Wait until the target item is
  visible before the gesture, and assert the target text or state after it.
- Dismiss the keyboard, snackbar, sheet, and old dialog before the next phase.
  After closing a dialog, issue `waitForAbsent(oldDialogKey)` before reusing its
  key for a new dialog. This prevents a stale route from satisfying the next
  `waitFor`.
- Use the current driver or Dart MCP gesture API with an explicit duration and
  pointer update frequency when it supports them. For an API that exposes a
  frequency for a stationary long press or drag, use about 60 Hz. The official
  [`FlutterDriver.scroll`](https://api.flutter.dev/flutter/flutter_driver/FlutterDriver/scroll.html)
  API defaults to 60 Hz, while `FlutterDriver` does not expose a long-press
  frequency argument. Do not invent an unsupported flag or make a coordinate
  and timing guess the primary proof.
- A file chooser, permission prompt, keyboard, share sheet, or other native
  surface is outside the Flutter widget tree. Use the platform automation path,
  then assert the returned file or permission state in the app. File filters
  must contain a real extension, MIME type, or platform UTI. An empty filter
  group is not an accepted file type.

## Scenario receipts and cleanup

Keep one machine-readable manifest for the run. Give each scenario a stable id,
a unique run id, and an explicit parent or child link. Store the requested
state, expected outcome, direct assertion, actual outcome, source-of-truth
check, cleanup result, and terminal status. Compute totals from the manifest and
terminal child receipts, not from handwritten totals. Write a child receipt only
after its direct assertion passes. Aggregate only after every child scenario has
a terminal receipt. Unknown scenario ids fail before execution.

```json
{
  "runId": "run-<unique-id>",
  "scenario": "shared-item",
  "restartState": "preserved",
  "steps": [
    {"id": "create-parent", "parentId": null, "status": "passed"},
    {"id": "create-child", "parentId": "create-parent", "status": "passed"}
  ],
  "totals": {"expected": 2, "completed": 2},
  "status": "passed",
  "cleanup": "passed"
}
```

Validate unique ids, parent-child links, computed totals, and terminal status
before writing the receipt. A UI counter, a screenshot, or a wrapper exit code
of zero is not enough to prove a scenario completed. Keep complete app, native,
driver, and backend logs for the run. A process exit without a terminal receipt,
a lost receipt, an incomplete log, or an unexplained pending async handle is
`incomplete` and fails the run. Critical Flutter, Dart, native, backend,
plugin, Riverpod, and driver errors fail the run even when the process exits
successfully. Cancel or await timers, futures, stream subscriptions, and
callbacks that belong to the scenario before cleanup.

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
- Observer or revoked actor sees correct fallback/empty/blocked state
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
- Deleted/revoked records are gone or marked inactive as designed.
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
- Sensitivity probe = run one invalid scenario and prove a non-zero/test failure before trusting valid cases.
- Selector proof = assert the selected element/state before and after the gesture; a completed tap command alone is insufficient.
- Screenshot subject = exact tested screen + expected state + current app process; wrong/blank/home-screen media = `FAIL`.
- Runner success + critical Flutter/native/backend log = `FAIL`; parse and assert logs before final exit.

## Failure Triage

- Assertion in logs: fix state/lifecycle first.
- Backend write fail: check datasource id contract, auth/permission, environment, and payload schema.
- Observer stale: check event contract, exact subscriptions, source-of-truth refetch, provider invalidation/sync, and actor permissions.
- Widget not tappable: inspect tree, add deterministic key/semantics, retest.
- Generated value stale: force source-of-truth refresh after mutation and before navigation/success.
- Revoked actor still sees detail: clear selected state, route fallback, invalidate/refetch affected providers.
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
9. Invalid-scenario sensitivity probe failed as expected.
10. Every delivered screenshot/recording was opened and matched to the asserted screen and state.
