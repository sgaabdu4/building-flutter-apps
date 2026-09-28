# Non-I/O boundary imports

Status: Complete

## Outcome + scope

Clarify the existing storage rule so an explicit `dart:io` show-only import can expose HTTP constants and exception types without exposing storage or transport APIs. Preserve all storage ownership and widget dependency requirements.

## Repository context

Owner: `skills/building-flutter-apps/references/architecture.md` rule 10. Exception mapping already belongs to the data layer in `state-management-lifecycle.md`. The analyzer companion owns executable enforcement and existing regression fixtures.

## Decisions + authorization

Blockers: None. Remote delivery remains pending below.
Handoff: Approval
Authority: The user authorized correction of genuine strict-profile contradictions. The coordinator approved exactly the four resolved symbols `HttpHeaders`, `HttpStatus`, `SocketException` and `FileSystemException`. No broader I/O exception or new plugin version is required for immutable skill-pin delivery.

## Acceptance + steps

- [x] Rule 10 identifies the exact show-only exception and retains broad, hide and additional-symbol import refusals.
- [x] The companion analyzer accepts the four allowed symbols and rejects actual I/O exposure through the existing architecture regression owner.
- [x] Existing skill smoke checks, native gates and independent review pass.

## Baseline + execution

Result: Passed
Evidence: Rule 10's literal all-import prohibition conflicts with valid HTTP constant use and the existing boundary exception mapper; no storage operation is involved. Canonical main `933a8548` was clean. This isolated clarification preserves version 5.12.0 and uses the existing smoke/gate owners. The supported updater initially refused an otherwise exact managed instruction block missing one final generated newline. Exact prior-source comparison proved there was no unique content; restoring that byte cleared all prewrite ownership checks. The supported updater then installed released Hard Eng `be0638f8` in isolated commit `f78f8f3`. Its normal Draft check passed all 12 configured native checks on the repaired implementation.

## Risks + recovery

Do not allow broad imports, hidden exports, arbitrary symbols or storage calls. Do not move transport or persistence into another owner merely to satisfy the detector. The Hard Eng source owner will pin the merged skill change with the corrected analyzer release.

## ux_reference

N/A — scoped engineering guidance has no visual interface.

## Verification

Result: Passed
Evidence: All 12 native checks passed: routing, Windows asset/input contracts, drift fixtures and live drift, Markdown examples, 48 plugin/hook smoke cases, both secret scans, Actionlint, Zizmor and ShellCheck. Independent review confirmed the wording and bounded companion matcher. The companion architecture regressions passed in a 103-test focused run; a separate native installed-SDK replay accepted the explicit and prefixed safe imports and rejected broad, hide, File, Directory, Process and HttpClient exposure.
E2E: Passed — resolved analyzer safe/unsafe imports and existing 48-check skill smoke.
Delivery target: Merge
Delivery: Pending — native pre-push, exact-head CI, merge and immutable source-pin handoff.
