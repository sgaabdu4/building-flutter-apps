# One case file for the theme-path rule

Status: Complete

## Outcome + scope

Add `tool/test_fixtures/theme_paths.json`: paths, each marked a theme or token file or not, so Hard Eng's `is_theme_path` and the Flutter lint plugin's theme-file rule are tested against the same rows. Non-goals: no skill text change, no new tool, no release, no change to any lint rule.

## Sources + coverage

Sources: N/A — the request is the only source, the Hard Eng single-source plan of the Hard Eng repository (Decision 11), which says the cases live once in this repository.
Reviewer: N/A — one small source.
Deliverables: None

## Repository context

Owners: `tool/test_fixtures/` holds this repository's test inputs; `.hooks/ui_rules.py` in the Hard Eng repository owns the rule (`is_theme_path`), and the lint plugin repository owns its Dart copy. Each rule has one case list: this file.
Same cause: N/A — new file; no earlier fix of two copies of the case list.
Single source: the case list for the theme-path rule has this one owner; Hard Eng and the plugin read it, and neither keeps its own list. Searched `tool/` and `skills/` for `theme`, `_tokens.dart` and `core/theme`: no other case list found in this repository.

## Decisions + authorization

Blockers: None
Handoff: Approval
Authority: Human-loop. The coordinator asked for this file on 2026-11-18 for the Hard Eng single-source plan (Decision 11), with PRs in this owned repository approved.

## Acceptance + steps

- [x] The case file holds a row for each theme word as a folder and as a last name word, the plus split, tailwind config names, the plugin's old forms and near misses that must be false → N/A — a data file with no behaviour of its own; the proof here is that the file parses, its paths are unique and every row equals `is_theme_path` of Hard Eng develop aaff1503 (78 rows, 0 differences). The consumer tests are not part of this change and are pending: Hard Eng adds its test `test_theme_path_cases_from_the_flutter_skill` and moves its submodule pin to this commit, and the lint plugin adds its own test and pin, each in its own repository.

## Baseline + execution

Result: Passed
Evidence: main at a66aed1; the rows were built from `is_theme_path` with each value written by intent first, then compared with the function: 78 rows, 0 differences.
Execution: One builder; one file and this plan.

## Risks + recovery

A later change to `is_theme_path` fails Hard Eng's test until its rows follow; the plugin pins this repository's revision, so it moves on its own pin. Recovery: change the row and both pins together.

## ux_reference

N/A — a data file; no interface changes.

## Verification

Result: Passed
Evidence: `python3 .hooks/hard-eng.py check --base origin/main --plan-stage Ready` passed all 12 checks on the case file and this plan. The file parses as JSON with 78 rows; every row equals `is_theme_path` of Hard Eng develop aaff1503. The consumer tests (Hard Eng and the plugin) are pending in their own repositories and are not proved by this change.
E2E: N/A — a data file with no runtime; the two consumers' tests read it.
Real service: N/A — no outside service is called.
Retro: The first check refused a plan with no source list that still held a coverage row; the row went. Nothing else repeated, so no new rule.

Delivery target: Merge
Delivery: Pending — required remote proof.
