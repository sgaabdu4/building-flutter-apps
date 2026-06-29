# GPT-5.4 Mini Eval Decisions

Date: 2026-06-29

## Decisions

- Kept the existing local Codex eval harness. It already runs `codex exec --model gpt-5.4-mini`, stores JSON artifacts, and matches the repo's skill workflow.
- Reduced eval-token load without weakening grading: `evals/evals.json` now uses `expected_output: "See expectations."`; the grader already uses `prompt` + `expectations`.
- Shortened the always-loaded `SKILL.md` frontmatter description from 218 to 130 tokens while preserving the trigger/skip contract.
- Expanded broad coverage to 45 quality cases and 38 trigger cases. New direct coverage includes accessibility/semantics/touch-target rules, plus positive and negative trigger cases.
- Compact result artifacts by default. `tool/run_codex_eval.py` now writes repo-relative or `$HOME` paths and omits duplicated prompts, reasons, response excerpts, and stderr excerpts unless `--include-excerpts` is used.
- Corrected current Core Stack constraints checked against Pub package metadata on 2026-06-29: Riverpod packages, `json_annotation`, `json_serializable`, `go_router`, and `hive_ce_generator`.
- Fixed reference routing issues: broken local anchors in common-pattern cross-links and `extensions-utilities.md`; added missing `## Read first` to a directly routed reference.
- Kept all repo artifacts free of absolute user home paths. Public proof files use relative paths or `$HOME`.

## Proof

- Core skill/eval files are lower-token after compaction while preserving broad coverage. Current key counts: `SKILL.md` 8,715; `evals/evals.json` 9,231; `evals/trigger-eval.json` 1,855; result JSON total 23,152.
- `evals/evals.json`: 45 cases, unique IDs, JSON-valid.
- `evals/trigger-eval.json`: 38 cases, 25 positive / 13 negative, JSON-valid.
- `evals/results/trigger-short-description-gpt-5.4-mini.json`: 38/38 passed, no false positives or negatives after shortening the description.
- `evals/results/quality-analyzer-final-gpt-5.4-mini.json`: ID 39 passed 1/1 with 7/7 checklist items.
- `evals/results/quality-analyzer-a11y-final-gpt-5.4-mini.json`: IDs 39 and 45 passed 2/2; ID 45 had 7/7 checklist items.
- `evals/results/quality-route-a11y-analyzer-gpt-5.4-mini.json`: IDs 39, 43, and 45 passed 3/3 after route/a11y/analyzer edits.
- Earlier GPT quality proof remains split across broad and targeted reruns. That is intentional: failed intermediate runs document the gaps that were fixed.
- Link audit: no missing local Markdown files or anchors after route fixes.
- PII audit: no absolute user-home paths or user-name path strings remain in repo artifacts.

## Boundary

This file records current evidence, not certainty. No push was performed. The skill remains intentionally Flutter/Riverpod/Freezed/GoRouter/Hive-focused; unrelated React, Next.js, SwiftUI, Kotlin, GetX, BLoC, shelf, and pure-Dart CLI work stays in the trigger skip set.
