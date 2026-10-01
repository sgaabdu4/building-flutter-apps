# Bring the Flutter skill examples and tooling references up to date

Status: Complete

## Outcome + scope

The skill's code examples, versions, links and rules match the current SDKs/packages and agree with each other and with Hard Eng's shared rules. Fixes the findings of the 2026-10-01 multi-model skill audit, each re-verified against its primary source before editing. The package also meets the `writing-great-skills` checklist: one owner per rule, every reference routed, one-line comments in examples.

Non-goals: new features, restyling passing text, or changing unrelated guidance.

## Repository context

Owners: `skills/building-flutter-apps/SKILL.md` + `references/`; checks in `tool/` (routing, drift, markdown examples, compatibility fixture) and `hard-eng.gates.json`.

## Decisions + authorization

Blockers: None
Handoff: Approval
Authority: Autonomous. The user asked to make every recommended audit change, review it, run adversarial review with GPT-6 Astra, test with GPT-6 Luna and Sonnet 5.5, and open a PR.

## Acceptance + steps

- [x] Changed Dart examples compile against the pinned stack and satisfy the skill's own lints → `markdown-examples` gate / compatibility fixture.
- [x] The Dart MCP tool map and docs link match the current dart_mcp_server → upstream README/CHANGELOG.
- [x] Marionette runs use the debug-gated binding in `lib/main.dart`; the driver-extension entrypoint is described as a separate mode → agrees with Hard Eng `e2e/references/flutter.md`.
- [x] Delta-sync examples write only changed rows → agrees with `performance.md` and its lint.
- [x] `analysis_options.yaml` keeps every option `flutter_skill_lints` requires (`missing_return: error`, `require_trailing_commas`) → its `cfg_strict_analysis`/`cfg_required_lints` rules stay satisfied.
- [x] Examples satisfy the skill's own lints (value objects, imports, preview placement, provider names) → proof package `dart analyze --fatal-infos` + `flutter test`.
- [x] Duplicated rules have one owner (pause boundaries, Pre-Flight, Dart Decimate, progressive disclosure, hook reminder, snackbar dispatch) and every relative/`#anchor` link resolves → link check.
- [x] Repository cache fallback covers only offline failures with cached rows → proof tests.
- [x] Realtime features keep a datasource/service subscription-wiring test beside the reaction test → injected events cannot hide missing wiring.
- [x] `python3 .hooks/hard-eng.py check` passes.

## Baseline + execution

Result: Passed
Evidence: `python3 .hooks/hard-eng.py check --plan-stage Draft` after the Hard Eng update commit `d6949f1`: skill-routing, windows-installer-assets, windows-installer-inputs, drift-fixtures, skill-drift, markdown-examples, plugin-hook-smoke, secrets-files, secrets-history, actionlint, shellcheck and zizmor passed.
Execution: One implementation subagent on branch `fix/skill-audit-2026-10`; the coordinator reviews the diff, then adversarial review and model tests.

## Risks + recovery

A rewritten example could still be wrong for an SDK version the skill pins. Each changed example is checked against that version's source or compiled; recovery is reverting the affected hunk.

## ux_reference

N/A — agent skill text; no product appearance.

## Verification

Result: Passed
Evidence: `python3 .hooks/hard-eng.py check` passed. Changed examples compiled in a proof package on the pinned stack: `dart analyze` clean with `flutter_skill_lints` and `riverpod_lint`, and `flutter test` passed, including the offline-fallback cases. GPT-6 Astra adversarial review approved after three rounds and approved a confirmation pass on `99faa73`–`408b8fa`. GPT-6 Luna (max) found three issues: the analyzer options and the subscription-wiring test were restored in `99faa73`. Its `HttpException` fallback suggestion was declined because the skill's lint allows only `SocketException` in repositories, and `package:http` 1.6.0 rethrows `HttpException` as `ClientException` (`io_client.dart:228`). Sonnet 5.5 (high) passed; its one note was fixed in `408b8fa`.
E2E: N/A — skill documentation; proof is the repository's contract/example checks plus compile checks of changed examples against the pinned SDKs.

Delivery target: PR
Delivery: Pending — PR checks.
