# Format skill references with Biome 2.6

Status: Complete

## Outcome + scope

Every reference file in the skill matches Biome 2.6 Markdown formatting, so Hard Eng's `shipped-format` check passes on the files it ships. The upstream drift check passes again after reviewing the one changed upstream skill. Non-goals: other wording changes, `SKILL.md` (Biome 2.6.2 flattens nested YAML front matter, which fails `claude plugin validate`), and new rules.

## Repository context

Owners: `skills/building-flutter-apps/references/*.md`; drift rule d5 in `tool/check_drift.sh`; upstream lock in `tool/upstream/flutter_skills.lock.json`. Biome 2.6.0 (2026-10-21) pads Markdown table columns, and d5 matched the Core Stack table header with single spaces. Upstream `dart-use-pattern-matching` changed on 2026-10-13: it now says when to use object destructuring.

## Decisions + authorization

Blockers: None
Handoff: Approval
Authority: The user asked on 2026-10-21 to fix every Biome finding and switch nothing off. Decided: adopt the upstream destructuring guidance as two sentences in `dart-patterns-records.md`, then refresh the lock.

## Acceptance + steps

- [x] Biome 2.6.2 reports no format change in `skills/building-flutter-apps` except `SKILL.md`, and a second run changes nothing → `biome format` with the shipped settings.
- [x] d5 still finds the Core Stack table with padded cells → `bash tool/check_drift_test.sh` (28 passed) and `bash tool/check_drift.sh` (13 rules passed).
- [x] The upstream lock matches `flutter/skills` main → `ruby tool/check_upstream_flutter_skills.rb`.

## Baseline + execution

Result: Passed
Evidence: Routing, drift fixtures, drift rules, Markdown examples and plugin smoke test passed on `main` 9852374.
Execution: One builder.

## Risks + recovery

Padded tables make reference files larger. Revert the commits to restore the old layout and lock.

## ux_reference

N/A — agent skill text; no product appearance.

## Verification

Result: Passed
Evidence: Skill routing OK; drift fixtures 28 passed; drift rules 13 passed; Markdown examples clean; plugin smoke test 48 passed; upstream lock current.
E2E: N/A — skill documentation; proof is the repository checks.

Delivery target: Merge
Delivery: Pending — PR into `main` with its checks green.
