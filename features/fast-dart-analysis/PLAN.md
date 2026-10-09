# Fast analysis in the edit loop

Status: Complete

## Outcome + scope

Release v5.12.1. Builder agents analyze only the files they edited while fixing, and run one package-root `dart analyze --fatal-infos` before handoff. A full or cold run took minutes per small fix. Non-goals: changing the final package-root rule, the pre-flight audit hook, or the plugin pins.

## Repository context

Owners: `skills/building-flutter-apps/SKILL.md` Pre-Flight and `references/analysis-options.md`. Measured on Dart 3.13.4, Flutter 3.47.5, Dart MCP server 1.2.0: a cold package-root run took 114-150 s on a ~1,100-file app; a folder run took 3.4 s only because it loaded no plugins; a single-file run took 14 s cold; a warm MCP `analyze_files` call took about 1.5 s with plugin lints.

## Decisions + authorization

Blockers: None
Handoff: Approval
Authority: User asked for the guidance change, a patch release and a merge.

## Acceptance + steps

- [x] Edit-loop rule covers MCP `analyze_files` (trailing-slash root, cold-start gap), the named-file `dart analyze` fallback, and the once-before-handoff package-root run → `analysis-options.md#edit-loop`.
- [x] Pre-Flight no longer asks for a package-root run after every write batch → `SKILL.md`.
- [x] Version 5.12.1 matches in plugin manifests, SKILL.md and `tool/smoke_test.sh`.

## Baseline + execution

Result: Passed
Evidence: routing check, markdown examples check and the 48-check smoke test pass on the branch.
Execution: One builder; text edits and version bump.

## Risks + recovery

An agent that trusts a cold MCP "No errors" would miss plugin lints; the rule tells it not to, and the final package-root run covers it.

## ux_reference

N/A — no visual surface.

## Verification

Result: Passed
Evidence: `python3 tool/check_skill_routing.py` exit 0; `ruby tool/verify_markdown_examples.rb` exit 0; `bash tool/smoke_test.sh` PASS 48 FAIL 0.
E2E: N/A — guidance text; proof is the checks above.

Delivery target: Merge
Delivery: Pending - PR checks green, merge to main, tag v5.12.1.
