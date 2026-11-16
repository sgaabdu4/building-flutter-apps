# Hard Eng strict rules fixes

Status: Complete

## Outcome + scope

The skill repository passes Hard Eng's new strict rules and every `flutter_skill_lints` pin is `^0.14.0`; non-goals: no skill behavior change, no version bump, no release.

## Sources + coverage

Sources: N/A — the request is the only source.
Deliverables: None

## Repository context

Owners: `skills/building-flutter-apps/references` (`analysis_options.yaml`, `setup.md`, `analysis-options.md`, `core-stack.md`); the copy under `.agents/skills` is the one Hard Eng installs and stays untouched, `analysis_options.yaml`, `README.md`, `tool/smoke_test.sh`, `tool/run_compatibility_fixture.py`, `hooks/scripts/preflight_audit.sh`, `tool/run_routing_eval.py`.
Same cause: Pin drift: the plugin hook smoke test compares the root `analysis_options.yaml` pin with the pin the test writes; searched the whole repository for `0.13.4` and moved every live copy; `features/explicit-types-over-var/PLAN.md` keeps its old pin as history. Comment blocks: only the two blocks the whole-project pass reports exist.
Single source: The pin is written in the skill references, the root config, the README and two tools; all now name `^0.14.0`, found by searching the repository for the old pin.

## Decisions + authorization

Blockers: None
Handoff: Approval
Authority: Autonomous. The owner asked for one PR that moves the pins and fixes the comment findings and the plugin hook smoke gate; the coordinator reviews and merges.

## Acceptance + steps

- [x] Every live `flutter_skill_lints` pin is `^0.14.0` → N/A — the plugin hook smoke gate compares them and `grep` finds no live `0.13.4`; no unit test can.
- [x] The plugin hook smoke gate passes → N/A — `tool/smoke_test.sh` is the gate itself; its result is in Verification.
- [x] The two comment blocks are one why-line each → N/A — the whole-project comment pass proves it; no unit test can.
- [x] Hard Eng check passes → N/A — the runs in Verification are the proof.

## Baseline + execution

Result: Passed
Evidence: The sealed scan of the base ended with the comment pass refusing 2 blocks and plugin-hook-smoke failing 2 steps when the pins moved.
Execution: One builder, one commit per cause.

## Risks + recovery

Projects that copy the profile resolve `flutter_skill_lints` 0.14.0 or newer, which adds the `avoid_frame_deferral` rule at error level, so a project may see new analyzer errors. Recovery: revert the pin commit.

## ux_reference

N/A — text-only skill guidance; no rendered interface changes.

## Verification

Result: Passed
Evidence: Run 1, the branch with its own hooks: `python3 .hooks/hard-eng.py check --plan-stage Ready` exit 0, 12 of 12 gates PASS (skill-routing, windows-installer-assets, windows-installer-inputs, drift-fixtures, skill-drift, markdown-examples, plugin-hook-smoke, actionlint, secrets-history, zizmor, secrets-files, shellcheck). Run 2, a scratch copy of the branch with Hard Eng develop 80756642 hooks and skills: same command, exit 0, the same 12 gates PASS. Run 3 does not apply: no Dart package. `python3 tool/run_compatibility_fixture.py` with the `^0.14.0` pin exits 1 on this Mac (Flutter 3.50.0): `dart run build_runner build` cannot compile its generator script because `analyzer` 14.4.0 and `source_helper` 1.4.0 define the same extension members. The same run on `origin/main` with the `^0.13.4` pin fails the same way (`$R/logs/BFA-fixture-main.log`), so the failure is not caused by the pin and the hosted lint step was not reached. The final `python3 .hooks/hard-eng.py check` on the Complete plan is recorded in the PR.
E2E: N/A — no application runtime is deployed by this repository; the smoke, routing and markdown-example checks cover the affected skill files.
Real service: N/A — the change calls no outside service.
Retro: plugin-hook-smoke failed on a pin that differed from the root pin → `tool/smoke_test.sh`, the existing gate that compares the pins; the whole-project comment pass refused 2 comment blocks → HE-COMMENT-LINES; the first run of the new plan failed on a missing plan field → the plan template's new fields, now filled.

Delivery target: PR
Delivery: Pending — required remote proof: draft PR, CI and coordinator merge.
