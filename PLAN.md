# Claude/Codex tooling and Hard Eng adoption

Status: Complete

## Outcome + scope

Publish Claude/Codex-only plugin support, pnpm tool commands and the released Hard Eng scaffold in the existing PR. Preserve the skill's behavior, native checks, upstream provenance and Windows settlement proof.

## Repository context

Owners: `skills/building-flutter-apps`, supported plugin manifests, `hooks`, `tool`, `.github/workflows` and `hard-eng.gates.json`. This is a skill repository with native script checks and no application dependency manifest.

## Decisions + authorization

Blockers: None; the observed scanner findings are repaired and affected native checks pass.
Handoff: Approval
Authority: The user authorized the combined cleanup, repository adoption, verification and merge in one PR. Preserve prerequisite commit `b48590e` through a merge commit.

## Acceptance + steps

- [x] Retire unsupported plugin registrations and use pnpm launchers with the specific Dart Decimate build allowance; supported plugin smoke assertions and the native launcher proof pass.
- [x] Install the released scaffold through its current setup entry point; record the exact source revision and retain shared AGENTS instructions without CLAUDE aliases.
- [x] Run the existing native repository checks through one gate owner; retain the upstream drift and Windows settlement assertions.
- [x] Repair the observed shell/workflow scanner findings without suppressions or assertion loss.
- [x] Verify local gates and review the public diff; retain prerequisite ancestry for the existing PR's merge commit.

## Baseline + execution

Result: Passed
Evidence: Commit `b48590e` passed Repository checks (27 s), Upstream flutter/skills drift (5 s) and Windows settlement (34 s). Its plugin smoke suite passed 48 checks and drift fixtures passed 28 checks. Fresh setup correctly refused the absent application manifest before writes; the explicit script-only gate contract supplies the existing checks.
Execution: One builder owns this branch; an independent reviewer checks the final adoption delta. Coordinate any heavy verification with the rollout coordinator.

## Risks + recovery

Preserve each native assertion and conditional Windows workflow when integrating the gate runner. Keep the prerequisite commit in branch ancestry. A failed gate blocks delivery; retain the task branch and repair the existing owner.

## ux_reference

N/A — agent tooling and repository checks; no application UI changes.

## Verification

Result: Passed
Evidence: Setup installed `1a1f86094fb7ceb36fd7abb7a400d056354bc1f8`; 159 scaffold files match released bytes and no CLAUDE aliases exist. The first adoption check exposed shell/workflow scanner findings, repaired in `c923fdd`. The combined Ready and final Complete checks passed all 12 checks: existing native assertions (48 smoke, 28 drift fixtures), secret scans, actionlint, zizmor and shellcheck. Complete elapsed 20.94 s against the 180 s budget. The separate upstream drift check passed. Independent review confirmed preserved assertions and equivalent shell/Windows repairs; its cache-path finding was fixed and re-reviewed so bootstrap and the native runner use the same stores with fresh version resolution.
E2E: Passed — current setup installed the exact release and all 48 smoke assertions passed, including clean/violating hook journeys. The unchanged Windows installer assets passed the baseline settlement run; the updated workflow still requires current-head hosted settlement proof before merge.
Delivery target: Merge
Delivery: Pending — current Repository checks, upstream drift and Windows settlement results, guarded merge commit and main-branch verification remain required.
