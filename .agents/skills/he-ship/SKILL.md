---
name: he-ship
description: Deliver a verified build through a task branch and PR, check the intended remote result, and clean up the completed task safely. Use for PR creation, shipping, merging or release/deployment requests; skip planning, implementation and review-only work.
---

# Hard Eng Ship

- Input = [HE Build](../he-build/SKILL.md) local Ready-for-ship evidence (a small change, per `check`'s Size line, has no plan: ship it without `--plan`) + user's delivery scope. Reuse authorization; a skill, plan or green check adds none. Resolve the actual repository, branch/PR and requested environment from the task + project instructions. Missing material authority/target → finish safe preparation, then ask only for that boundary.
- Big change = run `python3 .hooks/hard-eng.py challenge` on the final HEAD before ready or merge; address verified findings, rerun after new commits, and state the result or "independent review not done: <reason>" in the PR ([checks](references/checks.md)). Small changes skip it.
- Contract = [native shipping checks](references/checks.md); configure from repository facts in the existing gate file. Missing configuration/access/proof blocks. Use project-owned release commands and existing Git/`gh`; do not introduce a provider, tracker, upload service or watcher automatically.

```mermaid
flowchart TD
  A[Current build proof + delivery scope] --> B[Task branch + scoped PR with evidence]
  B --> C[Native ready check]
  C -->|Pass + merge authorized| M[Guarded merge]
  C -->|PR-only request| P[Report PR and actual checks]
  M --> D[Verify merged revision + required delivery proof]
  D -->|Pass| K[Guarded task cleanup]
  K --> R[Record actual outcome in same plan]
  C & D -->|Code failure| F[HE Build: fix + affected proof]
  F --> B
  C & D & K -->|Unavailable prerequisite| U[Preserve proof + exact resume condition]
  click C "references/checks.md"
  click M "references/checks.md"
  click K "references/checks.md"
  click F "../he-build/SKILL.md"
```

## Prepare + deliver

- Isolation = reuse this task's branch/worktree + existing PR. If work began in a shared/base checkout, isolate the authorized changes before shipping; preserve unrelated staged/unstaged files. One coordinator owns Git/ref/environment mutations. No blanket staging, history rewrite or branch-rule change.
- Hard Eng update = when shipping reports Hard Eng out of date, follow its named step ([freshness](references/checks.md)): `python3 .hooks/hard-eng.py update-pr` opens the "Update Hard Eng" PR and merges it once its checks pass (rerun it to merge; if the merge is denied, rerun with `--no-merge` and give the user the merge command it prints once checks pass), a failing one is fixed first on its own branch and worktree, then rebase the task branch. This PR is allowed beside the task's one PR and needs no approval.
- Baseline repair = [HE Plan's prerequisite route](../he/references/gates.md#baseline-repair) requires its own delivery through verified main before feature work resumes. Finish the authorized Merge or Deploy target, including current remote CI; a PR-only handoff leaves the dependent feature blocked.
- UI evidence = inspect matching baseline/final route, state and viewport through [E2E](../e2e/SKILL.md). Appearance differs → publish the before/after pair; unchanged → comparison note without duplicate uploads. Use the [contract's formats](references/checks.md#ui-evidence-in-the-pr). Interactions still need their own proof. Missing baseline → recover it in isolation, never invent unchanged appearance. Preserve published proof through cleanup.
- PR = actual problem/result + scoped diff + tests/evidence + material risks. Resolve a matching existing PR before creating one. A failed lookup is unknown, not absence. PR creation does not grant merge authority. Recheck after source changes; handle actionable review findings through existing [Code Review](../code-review/SKILL.md) and HE Build.
- Publication = review the complete outgoing payload against [publication privacy](references/checks.md#publication-privacy) before publishing or updating it.
- Verification = native check on the current PR/revision; pending, skipped required work, an old green run or a successful command with missing proof cannot establish delivery. For Deploy, the configured project check must inspect the intended deployed revision and affected runtime through E2E. No generic health page or local screenshot substitutes for the changed remote behavior.
- Recovery = inspect the actual remote result before retrying interrupted actions. Code/config changes → HE Build + fresh affected/final checks. Delivery-only outages/permissions → preserve local Complete and record the unfinished delivery + exact resume condition. Use the project's scoped recovery procedure; no blind migration retry or rollback.

## Completion + cleanup

- Same plan = local build Complete remains distinct from `Delivery target: PR`, `Merge` or `Deploy` in Verification. An `E2E: Delivery` journey keeps the target Deploy until its configured runtime verifier passes. Retain full pending delivery requirements as prose; replace pending claims only with actual evidence. Never tick remote proof before it exists or create a second state file.
- Cleanup = only after confirmed merge and required delivery proof, through the [guarded cleanup](references/checks.md#commands--proof-boundaries): it owns plan retention, artifact removal and every retained checkout. Uncertain ownership/activity → retain it and report the blocker. No force-removal to make cleanup pass.
- Handoff = PR/revision + current CI result + required release/runtime proof + cleanup outcome + remaining limitations. Reconcile the existing plan and final report with those receipts and the observed installed revision; installed files or local Complete alone do not establish delivered setup. Say submitted, merged or deployed according to what happened. Credentials and publication rights remain external prerequisites.
- Post-merge receipts = final report + native remote evidence. Do not create a follow-up PR solely to replace pre-merge pending delivery prose in the merged plan; that plan records the requirements, not a second delivery ledger.
- Efficiency = reuse matching proof; measure pre-push/CI duration against configured project budgets. Optimize demonstrated setup/critical-path waste at the existing gate owner; retain required checks, latest-tool policy and failure detection. No repeated full review, fixed agent count, score target or unmeasured “fastest” claim. After pushing, do not loop on CI status: enable the PR's auto-merge or the host's PR monitor, continue other work, and read the result once.
