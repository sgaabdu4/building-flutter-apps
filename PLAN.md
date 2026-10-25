# Hard Eng update and upstream preview guidance

Status: Complete

## Outcome + scope

Publish the verified Hard Eng update and incorporate the reviewed upstream widget-preview guidance in the existing PR. Refresh the native upstream snapshot without changing its source, inventory or failure behavior. Preserve all existing checks and preview safety rules.

## Repository context

Owners: `skills/building-flutter-apps`, supported plugin manifests, `hooks`, `tool`, `.github/workflows` and `hard-eng.gates.json`. This is a skill repository with native script checks and no application dependency manifest.
Same cause: the upstream drift job detected changed preview guidance. Compare the official source with the installed SDK, repair the existing reference, then regenerate its snapshot.

## Decisions + authorization

Blockers: None; source comparison, independent review and all required local checks passed. Remote delivery remains pending.
Handoff: Ready for ship
Authority: The user authorized synchronization, required tooling updates and necessary check repairs through main. Keep this repair in the current tooling PR.

## Acceptance + steps

- [x] Preview guidance matches the official constructor, theme and transform contracts. N/A — prose semantics need source comparison; no executable example changed. Independent review verified `super.transform().toBuilder()` and `build()` against the SDK.
- [x] The snapshot retains all 25 official skills and matches current content. N/A — live upstream state requires the existing native comparison command, not a synthetic behavior test; that comparison passed.
- [x] Retain all checks and safety boundaries. N/A — the native plan parser does not discover shell test names; the existing `tool/check_drift_test.sh` suite passed all 28 drift fixtures, alongside 48 smoke assertions and 12 required native gates.

## Baseline + execution

Result: Passed
Starting baseline: the repository check passed on the tooling PR, but upstream drift failed because `flutter-add-widget-preview` changed. That failure required this repair. The repaired native snapshot comparison and all 12 local native gates now pass.
Evidence: Commit `b48590e` passed Repository checks (27 s), Upstream flutter/skills drift (5 s) and Windows settlement (34 s). Its plugin smoke suite passed 48 checks and drift fixtures passed 28 checks. Fresh setup correctly refused the absent application manifest before writes; the explicit script-only gate contract supplies the existing checks.
Execution: One builder owns this branch. Independent review checked the official content hash, SDK APIs, public payload and plan. All 12 existing native gates passed after required tool preparation completed.

## Risks + recovery

Preserve each native assertion and conditional Windows workflow when integrating the gate runner. Keep the prerequisite commit in branch ancestry. A failed gate blocks delivery; retain the task branch and repair the existing owner.

## ux_reference

N/A — agent tooling and repository checks; no application UI changes.

## Verification

Result: Passed
Current repair: official source and SDK comparison passed independent review. The native snapshot update and subsequent upstream comparison passed. All 12 native gates passed, including 28 drift fixtures and 48 smoke assertions. The unchanged native gate initially exhausted its 180-second tool setup limit; the existing native provisioning owner completed the same latest tools with a bounded 900-second preparation, then the unchanged gate passed. Final pre-push and current PR/main CI remain pending. The following adoption evidence is historical.
Evidence: Setup installed `1a1f86094fb7ceb36fd7abb7a400d056354bc1f8`; 159 scaffold files match released bytes and no CLAUDE aliases exist. The first adoption check exposed shell/workflow scanner findings, repaired in `c923fdd`. The combined Ready and final Complete checks passed all 12 checks: existing native assertions (48 smoke, 28 drift fixtures), secret scans, actionlint, zizmor and shellcheck. Complete elapsed 20.94 s against the 180 s budget. The separate upstream drift check passed. Independent review confirmed preserved assertions and equivalent shell/Windows repairs; its cache-path finding was fixed and re-reviewed so bootstrap and the native runner use the same stores with fresh version resolution.
E2E: N/A — this prose and snapshot repair adds no runtime journey. Historical adoption proof passed all 48 smoke assertions and Windows settlement. Windows assets and their path-filtered workflow remain unchanged; current native fixture and smoke suites are still required.
Delivery target: Merge
Delivery: Pending — current Repository checks and upstream drift, guarded merge and exact main CI remain required.
