# Explicit types over var

Status: Complete

## Outcome + scope

Release v5.12.2. The analysis profile requires an explicit type instead of `var`, enforced by `flutter_skill_lints` `prefer_type_over_var` (default-enabled again in 0.13.4). `final` and `const` without a type stay allowed. The `flutter_skill_lints` pin rises to `^0.13.4`, the first release with the restored rule. Non-goals: `always_specify_types`, other profile rules.

## Repository context

Owners: `skills/building-flutter-apps/references/analysis-options.md` (profile rules); plugin pins in `analysis_options.yaml`, `references/analysis_options.yaml`, `setup.md`, `core-stack.md`, `README.md` and `tool/`; version strings in `.claude-plugin/`, `.codex-plugin/`, `SKILL.md` and `tool/smoke_test.sh`. Before this change the profile said `prefer_type_over_var` "is forbidden" and that `omit_local_variable_types` stayed off only until explicit local types were removed. No skill example uses `var`, so no example changes.

## Decisions + authorization

Blockers: None
Handoff: Approval
Authority: Owner's correction: ban `var` only, keep inferred `final`, replace the forbidden-rule text, fix any text that prefers `var` or inferred `var` locals, release with version bump, one PR, rebase-merge, tag (approved).

## Acceptance + steps

- [x] `analysis-options.md` requires explicit types instead of `var`, names `prefer_type_over_var` as the enforcer, and keeps untyped `final`/`const` allowed.
- [x] The `omit_local_variable_types` note no longer says the project should move away from explicit local types.
- [x] Every `flutter_skill_lints` pin in the skill, root config and tooling is `^0.13.4`.
- [x] Version 5.12.2 matches in plugin manifests, `SKILL.md` and `tool/smoke_test.sh`; full `python3 .hooks/hard-eng.py check` passes.

## Baseline + execution

Result: Passed
Evidence: Starting revision `98867c6` (main after the Hard Eng a1ec36b5 update); its full check passed 12 of 12.
Execution: One builder; text edits and version bump.

## Risks + recovery

A project still resolving 0.13.3 would lack the rule; the `^0.13.4` pin forces the release that has it. Recovery = follow-up patch.

## ux_reference

N/A — text-only skill guidance; no rendered interface changes.

## Verification

Result: Passed
Evidence: Full `python3 .hooks/hard-eng.py check --plan-stage Ready` passed 12 of 12 (skill-routing, windows-installer-assets, windows-installer-inputs, drift-fixtures, skill-drift, markdown-examples, plugin-hook-smoke, actionlint, secrets-history, shellcheck, zizmor, secrets-files). `tool/run_compatibility_fixture.py` printed `HOSTED_LINT_RESOLUTION_OK flutter_skill_lints=^0.13.4` and `COMPATIBILITY_FIXTURE_OK`. A scratch package using hosted `flutter_skill_lints ^0.13.4` reported `prefer_type_over_var` on top-level, local, `for`-in and `for`-in pattern `var` and nothing on untyped `final` or `const`. Codex adversarial review round 1 found the `^0.13.0` pin still allowed 0.13.3, which lacks the rule; the pin is now `^0.13.4`. Round 2 approved with no findings.
E2E: N/A — no application runtime is deployed by this repository; the smoke, routing and markdown-example checks cover the affected skill files.

Delivery target: Merge
Delivery: Pending — PR checks green, merge to main, tag v5.12.2.
