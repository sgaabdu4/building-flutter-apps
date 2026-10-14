# Native shipping checks

Load for configuring or running HE Ship. The initial verifier supports GitHub PRs whose head and base belong to `origin`; fork PRs and other providers are unsupported. Missing `gh`, authentication or configuration is a blocker. The checks use real Git/`gh` responses and trusted project commands. Fixture responses are only test evidence, not hosted delivery proof.

## Publication privacy

- Audience = establish the destination and who can read it before recording tracked content or publishing. General merge/publish authorization does not authorize disclosure of private context.
- Public shared tooling = use public repository facts or accurately labeled synthetic reproductions. Exclude private consumer/client identifiers, personal data, private task/commit IDs, internal URLs, local paths and private operational logs/screenshots. Keep real private evidence within its authorized audience; do not relabel it as synthetic.
- Review = inspect the complete payload: diff, plans/decisions/fixtures, filenames, branch/commit text, PR titles/bodies/comments, links, logs and attachments. Sanitize descriptions and evidence before publication. A passing secret scan cannot establish privacy.
- Disclosure = stop further exposure, sanitize current text within existing authority and report remaining history/copies. Current-text cleanup does not erase Git/edit history, notifications or copies; history rewriting requires separate authorization.

## Project contract

Add `shipping` to the existing `hard-eng.gates.json` from observed repository requirements:

```json
{
  "shipping": {
    "base": "main",
    "checks": ["hard-eng"],
    "ui_paths": ["web/**"],
    "ci_seconds": 180,
    "pre_push_seconds": 180,
    "delivery": []
  }
}
```

Values above are an example, not universal defaults. Use the actual target, required check names, UI owners and measured budgets. `ci_seconds` measures each named check, not upstream work hidden behind an aggregate; follow [CI ownership](../../he/references/gates.md) when consolidating existing jobs. A required check must conclude `success` on every PR; `skipped` proves nothing and is rejected. Put a path condition on the job's steps, never on the job, and add one step that reports nothing to verify, so a docs-only PR still concludes the check. An empty UI path list explicitly describes a nonvisual project. Missing/invalid policy blocks pushes, Complete plans selecting delivery and ship checks. Pre-push rejects direct updates to the configured base and still verifies the actual pushed commit. `pre_push_seconds` bounds each local gate; a gate with a recorded pass also stops at 3× that time (at least 600 s), so a hung check fails early. A whole run over the budget only warns, because rejecting a passed push discards the proof. The budget never permits omitting checks. Push to GitHub over HTTPS: an SSH connection can drop while the hook runs, failing the push (exit 141) after checks pass.

A big change (the size rule in `check`'s "Size" line) also needs `python3 .hooks/hard-eng.py challenge` run on the current HEAD before `ship` ready or merge: the other agent reviews it read-only ([challenge](../../code-review/references/challenge.md)). A missing record blocks; a `not done` record passes, and the PR evidence states "independent review not done: <reason>". Small changes skip it.

Installed-scaffold freshness is checked without mutation at shipping, and a newer CI-verified revision or unavailable freshness evidence blocks it. The end of a reply makes no update-freshness request: it adds a note from the session-start update result (still running, failed or unknown) and never blocks on freshness. The block names the next step: no open update PR → `python3 .hooks/hard-eng.py update-pr` (pushes `hard-eng/update`, opens the "Update Hard Eng" PR and merges it only after all checks on its head pass, no approval; merge denied → rerun with `--no-merge` and give the user the merge command it prints once checks pass); failing → fix it first on that branch in its own worktree; pending → wait for the checks, then rerun `update-pr` to merge it; merged → rebase the task branch on the base branch. This update PR is allowed beside the task's main PR, whatever one-PR habit applies. Reverify affected work afterwards; never advance the revision marker manually. Source development without an installed marker is outside this update check.

For deployment, `delivery` contains existing project verifiers: `{"name":"production","command":["python3","scripts/verify_deployment.py"]}`. Reuse a native project command before adding a script. Each receives `HE_SHIP_REVISION` and `HE_SHIP_PR_URL`; it must inspect the actual deployed state and emit JSON `{"status":"passed","revision":"<observed source revision>"}`. Nonzero exit, missing/wrong revision or absent required commands fail. A script that echoes the expected environment variable proves nothing; validate an old-version failure and current-version success at the deployed boundary.

Keep one declaration in the existing plan's Verification section:

```text
Delivery target: Deploy
Delivery: Pending — production verification and cleanup remain required.
```

Allowed targets: `PR`, `Merge`, `Deploy`. Local build acceptance stays in the existing checklist; full remote requirements stay explicitly pending until proven. No new plan Status values or unchecked future-delivery checkbox that prevents the necessary pre-push Complete gate.

## UI evidence in the PR

For changes matching `ui_paths`, compare the actual baseline and final appearance at the same route, state and viewport. Publish a before/after pair only when appearance differs, using distinct, inspected GitHub attachments. Use one pair per route, state or viewport that changed. The verifier needs at least one pair, equal counts of `Before:` and `After:`, and no repeated URL:

```markdown
Before: ![Before](https://github.com/user-attachments/assets/actual-before-id)
After: ![After](https://github.com/user-attachments/assets/actual-after-id)
```

When the installed `gh pr create` or `gh pr edit` supports `--attach`, upload
images or videos directly; a browser upload is not a prerequisite. For video,
keep its local Markdown reference as the only content in its paragraph in the
body file:

```markdown
Before:

![](evidence/before.mp4)

After:

![](evidence/after.mp4)
```

Create or update the PR with that body and both local files:

```sh
gh pr create --title "Title" --body-file pr-body.md \
  --attach evidence/before.mp4 --attach evidence/after.mp4
gh pr edit https://github.com/owner/repo/pull/123 --body-file pr-body.md \
  --attach evidence/before.mp4 --attach evidence/after.mp4
```

GitHub CLI rewrites each video reference to a standalone GitHub asset URL, so
the published body has the same labels followed by raw URLs. The verifier
accepts those URLs only under `Before:` or `After:`; image Markdown and mixed
image/video pairs remain supported.

When appearance is unchanged, omit the duplicate attachments and record one comparison note instead:

```text
UI appearance: unchanged — inspected the baseline and final dashboard at the same state and viewport; no visible difference.
```

Describe the actual comparison, not an assumed result. Missing proof is not unchanged appearance. This declaration cannot accompany labeled Before/After attachments and does not waive behavior tests. Distinct URLs or different file bytes alone do not establish a visible difference.

The verifier checks the declaration or attachment availability/media type; E2E owns inspection of the actual comparison and behavior. Keep baseline/final context in the PR; do not upload sensitive content or fabricate a missing baseline.

## Commands + proof boundaries

From the task checkout, with its actual PR URL and plan (a change `check` reports as `Size: small` ships without a plan: omit `--plan`; delivery scope is Merge and every check still runs, while a big change without a plan is refused):

```sh
python3 .hooks/hard-eng.py ship --plan PLAN.md --pr https://github.com/owner/repo/pull/123 --stage ready
```

`ready` verifies current PR identity, branch/build evidence, required checks and applicable UI evidence. It is read-only. `merge` runs the same gate before a head-matched rebase merge; squash and merge commits are refused. Invoke it only with existing merge authorization. A queued or pending merge is unfinished. A PR blocked only by a required review nobody but its author can give (sole push collaborator with admin bypass, every head check successful, no change requests or conflicts) passes and merges with `--admin`, reporting the bypass; never run `gh pr merge --admin` directly.

`delivered` requires actual merge/remote proof and, for Deploy, the configured runtime verification. Before cleanup, retain evidence and make sure no other task uses the checkout. Deliberately remove only known generated build/test artifacts; unknown ignored files are retained. Run `cleanup` from the repository's persistent checkout with `--worktree` naming the completed linked worktree. Native guards must pass; the main checkout, the base branch, a task branch another worktree uses, and a changed/dirty/untracked/locked/current checkout or active Git index lock are retained. Cleanup does not manufacture delivery proof. Use `python3 -B` for the cleanup invocation so Python does not create new bytecode artifacts.

Cleanup requires the captured origin URL to remain the fetch and sole push endpoint. Multiple or differing push URLs and initialized submodules are retained for a repository-owned cleanup procedure; the generic command never force-removes them. Dirty submodule checks override Git's ignore settings.

Record returned results at the same relative plan path in the persistent checkout, recovering the plan from the verified merged revision before removal if needed. Preserve unrelated edits there. Source changes invalidate affected build proof; external outages do not erase valid local checks. Remote branch protection remains project-owned; this implementation does not change server rules or claim to control unrelated clients.
