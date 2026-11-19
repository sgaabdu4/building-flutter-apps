# Fix four plain errors in the skill text

Status: Ready

## Outcome + scope

Fix four plain errors in the skill text: the key rule that contradicts its own example, the mutation name credited to the Riverpod docs, the `flutter_skill_lints` pin that lags the lints README, and the error handler rule that leaves a Crashlytics app with no uncaught error reports. Non-goals: no other skill text change, no new rule, no release.

## Sources + coverage

Sources: N/A — the owner's list of four fixes; each fix cites its own source in the PR.
Reviewer: N/A — four small text edits with an independent verification already done.
Deliverables: None

## Repository context

Owners: `skills/building-flutter-apps/references` holds the skill text; `tool/smoke_test.sh` and `tool/run_compatibility_fixture.py` hold the pin used by the checks; the root and reference `analysis_options.yaml` and `README.md` show the pin to users.
Same cause: the pin had 19 copies in 8 files; all moved together in one commit. The old pin text in `features/hard-eng-strict-fixes/PLAN.md` is history and stays.
Single source: N/A — each fix edits the one line that states the rule.

## Decisions + authorization

Blockers: None
Handoff: Approval
Authority: The owner approved fixing plain errors in this owned repository.

## Acceptance + steps

- [x] The key rule allows `ValueKey` and `ObjectKey` built inline from stable data and bans `UniqueKey` and `GlobalKey` in `build()` → N/A — prose; the example at line 29 now agrees with the rule.
- [x] The mutation name is a project rule, and the Riverpod docs alternatives are stated → N/A — prose with no executable example.
- [x] Every `flutter_skill_lints` pin is `^0.15.0` → N/A — the plugin hook smoke gate and the compatibility fixture compare the pin; `grep` finds no live `0.14.0` pin.
- [x] The error handler rule lets `Crash.init` set the Crashlytics handlers and still bans other hand-wired handlers → N/A — prose; `common-patterns.md` and `error-reporting.md` now agree.

## Baseline + execution

Result: Passed
Evidence: main at 81c9e29; no open PR in this repository.
Execution: One builder; one commit for each fix.

## Risks + recovery

A project that copies the profile resolves `flutter_skill_lints` 0.15.x, whose analyzer needs match 0.14 (`analyzer ^14.4.0`). Recovery: revert the pin commit.

## ux_reference

N/A — skill text; no interface changes.

## Verification

Result: Pending
Evidence: Pending — local gate run.
E2E: N/A — prose and a version pin; no runtime journey.
Real service: N/A — no outside service is called.
Retro: Pending

Delivery target: Merge
Delivery: Pending — required remote proof.
