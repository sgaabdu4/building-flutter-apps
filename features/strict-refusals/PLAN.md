# Teach no next-frame deferral or zero-delay wait

Status: Complete

## Outcome + scope

The skill stops teaching next-frame deferral (`addPostFrameCallback`, `scheduleFrameCallback`, `endOfFrame`) and zero-delay waits (`scheduleMicrotask`, `Future.microtask`, `Future.delayed(Duration.zero)`, `Timer(Duration.zero)`, `Timer.run`, `await null`). Each example starts work where its trigger happens. A new `flutter_skill_lints` rule and a Hard Eng rule will refuse these forms.

Non-goals: the `flutter_skill_lints` version pin in the analysis options template, and the Hard Eng installed copy under `.agents/skills/`.

## Repository context

Owners: `skills/building-flutter-apps/references/` and `evals/evals.json`. The smoke test `tool/smoke_test.sh` asserts some of the wording. The `.agents/skills/building-flutter-apps` copy is installed by Hard Eng updates, so it follows the next update.
Same cause: the old lint advice said to defer work out of `build()`, so each example copied that deferral. The fix is the same in each place: start the work at its trigger.

## Decisions + authorization

Blockers: None
Handoff: Approval
Authority: The user asked for this change and approved commit, push and a PR. No merge.

## Acceptance + steps

- [x] The Post-Frame Callbacks section teaches the Riverpod fix: the notifier decides and the widget reacts through `ref.listen` in `build`, or the event handler does the work. N/A — prose and example text; the Markdown example check and routing check cover it.
- [x] No file of the skill teaches any listed form as a pattern. N/A — a text search over skills, evals and tools finds only two sentences that forbid the forms; no runtime behavior changes.
- [x] Markdown examples pass the repository's example check. N/A — the existing `markdown-examples` gate runs it.

## Baseline + execution

Result: Passed
Evidence: Six sync notifier examples seeded state and then deferred the first load with `Future.microtask`. They now seed only and expose a public `load()` that the action opening the route calls. The pinned lint `avoid_sync_notifier_state_read` flags a `_load` call inside `build()`, so a direct call there is not a fix. One batch helper awaited `Future<void>.value()` to yield. That wait is removed.

## Risks + recovery

The pinned lint message still names `Future.microtask` as the fix. The `flutter_skill_lints` release changes it. The smoke assertion on `notifier-structure.md` stays, because the sentence that forbids relying on `Future.microtask` ordering remains.

## ux_reference

N/A — skill text; no visual interface.

## Verification

Result: Passed
Evidence: Routing check, Markdown example check, drift check and plugin smoke suite passed after the edits.
E2E: N/A — skill text and examples; no runtime journey.
Delivery target: Merge
Delivery: Pending — exact-head CI and review.
