# Bump canonical flutter_skill_lints pin to ^0.16.0

Status: Complete

## Outcome + scope

Update every canonical `flutter_skill_lints` plugin constraint in this repository's analyzer profile, skill references, smoke test, and compatibility fixture from `^0.15.0` to `^0.16.0` so Flutter projects adopt the UI single-source lint rules (`ui_base_control_outside_library` and aligned theme-path classification). Also update the slider example in `skills/building-flutter-apps/references/common-patterns/debounce-gate-batch.md` to show a shared `AppSlider` wrapper forwarding `onChangeEnd` so copying it into a feature complies with `ui_base_control_outside_library`, and update `tool/run_compatibility_fixture.py` to import `validate_dart_exclusions` from `.hooks/dart_boundaries.py` after Hard Eng `92741038` moved it out of `project_setup.py`. Non-goals: editing Hard Eng's vendored read-only copy under `.agents/skills/building-flutter-apps/` (Hard Eng bumps its pinned `building-flutter-apps` submodule in a separate Hard Eng release PR after this PR merges), historical plans, or `riverpod_lint` version changes.

## Sources + coverage

Sources: N/A — `flutter_skill_lints` `v0.16.0` release on `pub.dev` and the maintainer rollout authorization define the scope.
Deliverables: None

## Repository context

Owners:
- `analysis_options.yaml` and `skills/building-flutter-apps/references/analysis_options.yaml` own the canonical analyzer plugin configuration.
- `README.md`, `skills/building-flutter-apps/references/setup.md`, `skills/building-flutter-apps/references/analysis-options.md`, and `skills/building-flutter-apps/references/core-stack.md` document the pinned constraint.
- `tool/smoke_test.sh` and `tool/run_compatibility_fixture.py` verify the hosted `^0.16.0` resolution, analyzer exclusions, and diagnostics.

Same cause: Every live `^0.15.0` pin in the repository is updated together so profile, docs, smoke checks, and hosted compatibility proof stay aligned. The `validate_dart_exclusions` import in `tool/run_compatibility_fixture.py` was broken by Hard Eng `92741038` moving that helper to `dart_boundaries.py` and is repaired in its own commit.
Single source: `analysis_options.yaml` and `skills/building-flutter-apps/references/analysis_options.yaml`.

## Decisions + authorization

Blockers: None
Handoff: None
Authority: Autonomous. Maintainer's 2026-11-22 UI Single Source of Truth rollout authorization covers bumping `building-flutter-apps` to `flutter_skill_lints: ^0.16.0` after `v0.16.0` publishes to `pub.dev`.

## Acceptance + steps

- [x] Every canonical `flutter_skill_lints` pin outside Hard Eng's vendored `.agents/skills/` copy is `^0.16.0` → N/A — `tool/smoke_test.sh`, `tool/run_compatibility_fixture.py`, and grep verify no canonical `^0.15.0` pin remains; Hard Eng updates its pinned submodule and vendored `.agents/skills/building-flutter-apps/` copy in a separate follow-up Hard Eng release PR once this PR merges.
- [x] Hosted compatibility fixture resolves `flutter_skill_lints: ^0.16.0` from `pub.dev` and passes analyzer + Flutter tests → N/A — `python3 tool/run_compatibility_fixture.py` printed `HOSTED_LINT_RESOLUTION_OK flutter_skill_lints=^0.16.0` and `COMPATIBILITY_FIXTURE_OK`.
- [x] All installed Hard Eng checks pass → N/A — `python3 .hooks/hard-eng.py check --base origin/main --plan-stage Complete` is the proof.

## Baseline + execution

Result: Passed
Evidence: On `origin/main` (`c0d3206` after Hard Eng `92741038` update PR #48), `tool/run_compatibility_fixture.py` failed with `ImportError: cannot import name 'validate_dart_exclusions' from 'project_setup'` because `92741038` moved `validate_dart_exclusions` to `dart_boundaries`. Repaired that import in its own commit, bumped all 8 canonical files from `^0.15.0` to `^0.16.0`, updated the feature slider example in `debounce-gate-batch.md` to `AppSlider`, and ran the hosted compatibility fixture against `pub.dev`.
Execution: Single builder in an isolated checkout: commit import repair, commit `^0.16.0` pin updates and plan, run hosted compatibility proof, full Hard Eng check, and independent challenge.

## Risks + recovery

`flutter_skill_lints ^0.16.0` keeps the same `analyzer ^14.4.0` compatibility while adding `ui_base_control_outside_library` and aligned theme-path rules; verified against the hosted compatibility fixture before shipping. Recovery: revert the merge commit on `main`.

## ux_reference

N/A — analyzer config and skill documentation have no user interface.

## Verification

Result: Passed
Evidence: `python3 tool/run_compatibility_fixture.py` passed against live `pub.dev`, printing `HOSTED_LINT_RESOLUTION_OK flutter_skill_lints=^0.16.0` and `COMPATIBILITY_FIXTURE_OK` (confirming both `flutter_skill_lints` and `riverpod_lint` diagnostics with zero `server.pluginError`, Dart exclusions validation, Flutter widget tests, and web build). An independent second reader checked the revised `AppSlider` example in `skills/building-flutter-apps/references/common-patterns/debounce-gate-batch.md` against `analysis_options.yaml` and `flutter_skill_lints ^0.16.0` (`PASS with minor nits`); wrapped the `AppSlider` comment stub within the 100-char formatter width with trailing commas, narrowed the comment to `raw Slider`, and kept a direct synchronous `onChangeEnd` call while noting `unawaited` only when the setter returns a `Future`. Full `python3 .hooks/hard-eng.py check --base origin/main --plan-stage Complete` passed.
E2E: N/A — skill package and analyzer config have no interactive user journey; `tool/run_compatibility_fixture.py` exercises real `flutter pub get`, `dart analyze`, and Flutter test/web build end-to-end.
Real service: Passed — pub.dev: `python3 tool/run_compatibility_fixture.py` resolved hosted `flutter_skill_lints: ^0.16.0` from `https://pub.dev/api/archives/flutter_skill_lints-0.16.0.tar.gz` (no path override or fake) and returned `HOSTED_LINT_RESOLUTION_OK flutter_skill_lints=^0.16.0` and `COMPATIBILITY_FIXTURE_OK` (refusal case not induced against live pub.dev).
Retro: Hard Eng `92741038` moved `validate_dart_exclusions` from `project_setup.py` to `dart_boundaries.py`, breaking `tool/run_compatibility_fixture.py` → fixed the import in its own commit; running `tool/run_compatibility_fixture.py` remains the prevention.
Delivery target: Merge
Delivery: Pending — checks, challenge, PR, CI, and merge to `main`.
