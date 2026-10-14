# Hard Eng a1ec36b5 update

Status: Complete

## Outcome + scope

The repo runs Hard Eng `a1ec36b5` installed by the supported updater, and CI provisions Bun for the check as this release requires. Out of scope: the `building-flutter-apps` skill content under `skills/`, and dependency updates.

## Repository context

Owners: `.hooks/hard-eng-source.json` and the updater commit (installed revision); `.hooks/` and `.agents/skills/` (scaffold); `.github/workflows/ci.yml` (CI invocation of the check). The updater reported `ci.yml runs Hard Eng without setting up Bun`; `ci.yml` is a custom workflow, so the release template's Bun steps are applied by hand: `oven-sh/setup-bun`, the `bun x` mise launcher, and no pnpm bootstrap or tool cache.

## Decisions + authorization

Blockers: None
Handoff: Approval
Authority: Agent-loop under the owner's Hard Eng flow: `update-pr` opens and merges the prepared update once checks pass.

## Acceptance + steps

- [x] Installed revision is `a1ec36b5` → `.hooks/hard-eng-source.json` shows `a1ec36b57391c0a46570c40f6e0466b77f4684e2` after the supported updater.
- [x] CI provisions Bun before the check → `ci.yml` uses `oven-sh/setup-bun` and the `bun x` mise launcher.
- [x] Repository checks pass on the updated scaffold → `python3 .hooks/hard-eng.py check` exits 0.

## Baseline + execution

Result: Passed
Evidence: Starting revision `e7a9a59` (Hard Eng `02f02959`); the updater verified and committed `a1ec36b5` locally on the first run.
Execution: Single builder; scaffold-only update plus the CI Bun migration.

## Risks + recovery

New gate rules could flag existing files; a Bun launcher fault would fail CI before merge. Recovery = revert the PR.

## ux_reference

N/A — tooling only; no rendered interface changes.

## Verification

Result: Passed
Evidence: Full `python3 .hooks/hard-eng.py check --plan-stage Ready` passed on `a1ec36b5` with the Bun workflow (12 checks passed, 0 failed: skill-routing, windows-installer-assets, windows-installer-inputs, drift-fixtures, skill-drift, markdown-examples, plugin-hook-smoke, actionlint, secrets-history, shellcheck, secrets-files, zizmor).
E2E: N/A — no application runtime is deployed by this repository; the native contract checks cover the affected interface.

Delivery target: Merge
Delivery: Pending — PR merged into main with the required checks passing.
