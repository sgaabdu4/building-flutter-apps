# Teach no next-frame deferral or zero-delay wait

Status: Draft

## Outcome + scope

The skill stops teaching next-frame deferral (`addPostFrameCallback`, `scheduleFrameCallback`, `endOfFrame`) and zero-delay waits (`scheduleMicrotask`, `Future.microtask`, `Future.delayed(Duration.zero)`, `Timer(Duration.zero)`, `Timer.run`, `await null`). Each example starts work where its trigger happens. A new `flutter_skill_lints` rule and a Hard Eng rule will refuse these forms.

Non-goals: the `flutter_skill_lints` version pin in the analysis options template, and the Hard Eng installed copy under `.agents/skills/`.

## Repository context

Owners: `skills/building-flutter-apps/references/` and `evals/evals.json`. The smoke test `tool/smoke_test.sh` asserts some of the wording. The `.agents/skills/building-flutter-apps` copy is installed by Hard Eng updates, so it follows the next update.

## Decisions + authorization

Blockers: None
Handoff: Approval
Authority: The user asked for this change and approved commit, push and a PR. No merge.

## Acceptance + steps

- [ ] The Post-Frame Callbacks section teaches the Riverpod fix: the notifier decides and the widget reacts through `ref.listen` in `build`, or the event handler does the work.
- [ ] No file of the skill teaches any listed form as a pattern.
- [ ] Markdown examples compile under the repository's example check.

## Baseline + execution

Result: Pending
Evidence: Pending

## Risks + recovery

Smoke assertions and evals that name the old forms change with the text. Keep each assertion's intent.

## ux_reference

N/A — skill text; no visual interface.

## Verification

Result: Pending
Evidence: Pending
E2E: N/A — skill text and examples; no runtime journey.
Delivery target: Merge
Delivery: Pending
