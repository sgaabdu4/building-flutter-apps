# Hard Eng scaffold rollout

Status: Complete

## Outcome + scope

Adopt released Hard Eng `7eebdaf3` and refresh project-owned dependencies. Non-goals: skill guidance changes, Hard Eng-managed files and CI tool pins owned by the scaffold.

## Repository context

Owners: `.hooks/`, `.agents/skills/` (managed copies from the Hard Eng source), `hard-eng.gates.json` and `.github/workflows/ci.yml`. The repository has no application dependency manifest: the two pnpm manifests under `.agents/skills/` are updater-managed copies, `skills/building-flutter-apps/assets/inno-bundle-pubspec.yaml` is skill content and `tool/upstream/flutter_skills.lock.json` is the upstream drift lock.

## Decisions + authorization

Blockers: None
Handoff: Approval
Authority: The user authorized one combined scaffold adoption and dependency refresh PR, merged to `main` after its required checks pass.

## Acceptance + steps

- [x] The supported updater installs `7eebdaf3` in an isolated commit and `.hooks/hard-eng-source.json` records that revision.
- [x] Setup validation holds: `packages` is empty so no `depends_on` review applies, and the only workflow `check` call passes `--base "$BASE_SHA"` from the pull request base or push-before SHA.
- [x] Dependencies: no project-owned manifest exists to upgrade; managed skill packages and scaffold-owned action pins stay unchanged.
- [x] The full local gate passes against `origin/main`.

## Baseline + execution

Result: Passed
Evidence: Branch was level with `origin/main` `cf3f7ef` at Hard Eng `2e246601`. The updater created commit `eeee28a` (8 managed files) recording `7eebdaf3`; its scaffold-only check passed in 66 s. Latest action releases: `actions/checkout` v7.0.1 and `actions/cache` v6.1.0 match the pins.
Execution: Single builder; updater commit first, then this plan.

## Risks + recovery

`pnpm/setup` v3.0.0 is released, but the Hard Eng CI migration pins v2.1.0; bumping it here would diverge from the scaffold owner. Recovery: adopt it when the Hard Eng source moves the pin.

## ux_reference

N/A — scaffold and tooling update with no visual interface.

## Verification

Result: Passed
Evidence: `check --base origin/main` passed all 12 configured checks in 22 s (Draft stage: 24 s): routing, Windows asset/input contracts, 28 drift fixtures, 13 live drift rules, Markdown examples, plugin/hook smoke, both secret scans, Actionlint, Zizmor and ShellCheck.
E2E: N/A — skill repository with no user journey; proof is the native check suite locally, at pre-push and in hosted CI.
Delivery target: Merge
Delivery: Pending — native pre-push, exact-head CI and squash merge to `main`.
