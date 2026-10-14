# Explicit types over var

Status: Ready

## Outcome + scope

Release v5.12.2. The analysis profile requires an explicit type instead of `var`, enforced by `flutter_skill_lints` `prefer_type_over_var` (default-enabled again in 0.13.4). `final` and `const` without a type stay allowed. Non-goals: `always_specify_types`, plugin pins, other profile rules.

## Repository context

Owners: `skills/building-flutter-apps/references/analysis-options.md` (profile rules); version strings in `.claude-plugin/`, `.codex-plugin/`, `SKILL.md` and `tool/smoke_test.sh`. Before this change the profile said `prefer_type_over_var` "is forbidden" and that `omit_local_variable_types` stayed off only until explicit local types were removed. No skill example uses `var`, so no example changes.

## Decisions + authorization

Blockers: None
Handoff: Approval
Authority: Owner's correction: ban `var` only, keep inferred `final`, replace the forbidden-rule text, fix any text that prefers `var` or inferred `var` locals, release with version bump, one PR, rebase-merge, tag (approved).

## Acceptance + steps

- [ ] `analysis-options.md` requires explicit types instead of `var`, names `prefer_type_over_var` as the enforcer, and keeps untyped `final`/`const` allowed.
- [ ] The `omit_local_variable_types` note no longer says the project should move away from explicit local types.
- [ ] Version 5.12.2 matches in plugin manifests, `SKILL.md` and `tool/smoke_test.sh`; full `python3 .hooks/hard-eng.py check` passes.

## Baseline + execution

Result: Passed
Evidence: Starting revision `98867c6` (main after the Hard Eng a1ec36b5 update); its full check passed 12 of 12.
Execution: One builder; text edits and version bump.

## Risks + recovery

Projects pinned below `flutter_skill_lints` 0.13.4 lack the rule; `^0.13.0` resolves to 0.13.4 on a fresh resolve. Recovery = follow-up patch.

## ux_reference

N/A - text-only skill guidance; no rendered interface changes.

## Verification

Result: Pending
Evidence: Pending the full check.
E2E: N/A - no application runtime is deployed by this repository; the smoke, routing and markdown-example checks cover the affected skill files.

Delivery target: Merge
Delivery: Pending - PR checks green, merge to main, tag v5.12.2.
