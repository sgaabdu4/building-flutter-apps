# Bring the Flutter skill examples and tooling references up to date

Status: Ready

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

- [ ] Changed Dart examples compile against the pinned stack and satisfy the skill's own lints → `markdown-examples` gate / compatibility fixture.
- [ ] The Dart MCP tool map and docs link match the current dart_mcp_server → upstream README/CHANGELOG.
- [ ] Marionette runs use the debug-gated binding in `lib/main.dart`; the driver-extension entrypoint is described as a separate mode → agrees with Hard Eng `e2e/references/flutter.md`.
- [ ] Delta-sync examples write only changed rows → agrees with `performance.md` and its lint.
- [ ] No removed/no-op analyzer options remain in `analysis_options.yaml`.
- [ ] Examples satisfy the skill's own lints (value objects, imports, preview placement, provider names) → proof package `dart analyze --fatal-infos` + `flutter test`.
- [ ] Duplicated rules have one owner (pause boundaries, Pre-Flight, Dart Decimate, progressive disclosure, hook reminder, snackbar dispatch) and every relative/`#anchor` link resolves → link check.
- [ ] Repository cache fallback covers only offline failures with cached rows → proof tests.
- [ ] `python3 .hooks/hard-eng.py check` passes.

## Baseline + execution

Result: Passed
Evidence: `python3 .hooks/hard-eng.py check --plan-stage Draft` after the Hard Eng update commit `d6949f1`: skill-routing, windows-installer-assets, windows-installer-inputs, drift-fixtures, skill-drift, markdown-examples, plugin-hook-smoke, secrets-files, secrets-history, actionlint, shellcheck and zizmor passed.
Execution: One implementation subagent on branch `fix/skill-audit-2026-10`; the coordinator reviews the diff, then adversarial review and model tests.

## Risks + recovery

A rewritten example could still be wrong for an SDK version the skill pins. Each changed example is checked against that version's source or compiled; recovery is reverting the affected hunk.

## ux_reference

N/A — agent skill text; no product appearance.

## Verification

Result: Pending
Evidence: Pending
E2E: N/A — skill documentation; proof is the repository's contract/example checks plus compile checks of changed examples against the pinned SDKs.

Delivery target: PR
Delivery: Pending — PR checks.
