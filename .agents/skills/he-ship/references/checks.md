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

Values above are an example, not universal defaults. Use the actual target, required check names, UI owners and measured budgets. `ci_seconds` measures each named check, not upstream work hidden behind an aggregate; follow [CI ownership](../../he/references/gates.md) when consolidating existing jobs. A required check must conclude `success` on every PR; `skipped` proves nothing and is rejected. Put a path condition on the job's steps, never on the job, and add one step that reports nothing to verify, so a docs-only PR still concludes the check. An empty UI path list explicitly describes a nonvisual project. Missing/invalid policy blocks pushes, Complete plans selecting delivery and ship checks. Pre-push reads the shipping policy of the pushed commit, rejects direct updates to its base and verifies that commit; a full `check --base <ref>` (not `--quick`, `--plan-stage Draft` or `Ready`, a language filter, `--without-dependents`, `--related-tests` or in CI) that passed on a clean tree stands in for the push check only when the push has the same commit and the same base commit as that check (the base of a push = the branch point on a first push or after a rewrite, the old remote tip on a later one), in the same worktree, within 30 minutes of the start of that check; with mutation on, a quick check still runs before the mutation report. `pre_push_seconds` bounds each local gate; a gate with a recorded pass also stops at 3× that time (at least 600 s), so a hung check fails early. A whole run over the budget only warns, because rejecting a passed push discards the proof. The optional `pre_push_mutation_seconds` (default 120, 0 skips) caps the report-only mutation run after the checks pass; it is not part of `pre_push_seconds`. Run the full report with `python3 .hooks/hard-eng.py mutation --base <ref>`. The budget never permits omitting checks. Push to GitHub over HTTPS: an SSH connection can drop while the hook runs, failing the push (exit 141) after checks pass.

A big change (the size rule in `check`'s "Size" line) also needs `python3 .hooks/hard-eng.py challenge` run on the current HEAD before `ship` ready or merge: the other agent reviews it read-only ([challenge](../../code-review/references/challenge.md)). A missing record blocks; a `not done` record passes, and the PR evidence states "independent review not done: <reason>". Small changes skip it.

Installed-scaffold freshness is checked without mutation at `ship` ready and merge; a newer CI-verified revision or unavailable freshness evidence blocks that stage. The end of a reply makes no update-freshness request: it adds a note from the session-start update result (still running, failed or unknown) and never blocks on freshness. The block names the next step: no open update PR → `python3 .hooks/hard-eng.py update-pr` (pushes `hard-eng/update`, opens the "Update Hard Eng" PR and merges it only after all checks on its head pass, no approval; merge denied → rerun with `--no-merge` and give the user the merge command it prints once checks pass); failing → fix it first on that branch in its own worktree; pending → wait for the checks, then rerun `update-pr` to merge it; merged → rebase the task branch on the base branch. This update PR is allowed beside the task's main PR, whatever one-PR habit applies. Reverify affected work afterwards; never advance the revision marker manually. Source development without an installed marker is outside this update check.

For deployment, `delivery` contains existing project verifiers: `{"name":"production","command":["python3","scripts/verify_deployment.py"]}`. Reuse a native project command before adding a script. Each receives `HE_SHIP_REVISION` and `HE_SHIP_PR_URL`; it must inspect the actual deployed state and emit JSON `{"status":"passed","revision":"<observed source revision>"}`. Nonzero exit, missing/wrong revision or absent required commands fail. A script that echoes the expected environment variable proves nothing; validate an old-version failure and current-version success at the deployed boundary. Once `delivery` lists a check, plans use `Delivery target: Deploy` (`Merge` fails the plan check), and a small change without a plan runs the delivery checks too.

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

## PR text

- Form = a reader with one minute gets the point. Order: a `Summary` of ≤5 bullets (what changes for the user) → one line per main change (list or table) → `Before and after` → proof → limits. Headings + bold lead words. Plain simplified English for people, in the style of ASD-STE100: one idea per sentence, ≤20 words, ≤4 sentences per paragraph. Detail that few readers need (each commit, each review run, timing tables, long proof) → a `<details>` block or a link to the plan. `ready` and CI's `pr text` refuse a wall of text: more than 6,000 visible characters, or a visible line over 600. Fenced code blocks, `<details>` blocks, HTML comments and link targets are not visible text.
- `Before and after` part = for each main change one Mermaid diagram of the old flow + one of the new flow; a main change with no old flow shows two or more diagrams of its new flows. Label each diagram with a bold word, such as `**Before**` or `**After**`. Do not start a line with `Before:` or `After:`. The checker reads such a line as a UI evidence label. It refuses a PR that has one of these lines and also the "UI appearance: unchanged" note. Use `flowchart TD`, quoted labels, no backticks inside labels. `ready` refuses fewer than two Mermaid blocks ([what `ready` verifies](#commands--proof-boundaries)).
- A line that starts `Not checked:`, with the answer on that line (a `- ` or `* ` list mark may come first) = what no check covered, such as a platform, device, deploy or installed project; `Not checked: None — <reason>` when nothing.
- UI change whose appearance differs = before and after screenshots ([UI evidence](#ui-evidence-in-the-pr)) with a red ring on each changed thing: draw the ring in the page before you take the screenshot, or on the image afterwards. When stills cannot show the flow, add a video of the whole flow below the pairs, with no `Before:` or `After:` label (the checker needs equal counts of those lines and ignores unlabeled media).
- CI's `pr text` check skips three kinds of PR: the Hard Eng update PR (it keeps its generated text and needs no `Not checked:` line in CI), a PR that the account `dependabot[bot]` or `renovate[bot]` opened (a bot writes its text) and a PR whose base is not the shipping base. It checks every other PR on each push or edit, and applies the [UI evidence](#ui-evidence-in-the-pr) form when the PR changes a `ui_paths` file. Setup installs it beside any GitHub workflow of the project.

## Commands + proof boundaries

From the task checkout, with its actual PR URL and plan (a change `check` reports as `Size: small` ships without a plan: omit `--plan`; delivery scope is Merge and every check still runs, while a big change without a plan is refused):

```sh
python3 .hooks/hard-eng.py ship --plan PLAN.md --pr https://github.com/owner/repo/pull/123 --stage ready
```

`ready` verifies current PR identity, branch/build evidence, required checks, applicable UI evidence, a PR body line that starts `Undo:` and lists the undo steps on that line, two or more Mermaid blocks in the body (the [PR text](#pr-text) `Before and after` part), a `Not checked:` line, and the two size limits of the PR text form. It also refuses a PR head that is behind its base, so two PRs that pass alone cannot break the base together. To recover, rebase on the base, push and wait for the checks again. It also refuses a PR above the HE-PR-COMMITS cap and a PR that GitHub cannot rebase; each refusal names its fix. It prints a warning when the base branch may not require the checks. A queued check on a self-hosted runner that no runner takes shows after `ci_seconds` with its runner labels; GitHub fails it after 24 hours, so rerun `ready` once after `ci_seconds` instead of watching. It is read-only. `merge` runs the same gate before a head-matched rebase merge; squash and merge commits are refused. Invoke it only with existing merge authorization. A queued or pending merge is unfinished. A PR blocked only by a required review nobody but its author can give (sole push collaborator with admin bypass, every head check successful, no change requests or conflicts) passes and merges with `--admin`, reporting the bypass; never run `gh pr merge --admin` directly.

`delivered` requires actual merge/remote proof and, for Deploy, the configured runtime verification. Before cleanup, retain evidence and make sure no other task uses the checkout. Deliberately remove only known generated build/test artifacts; unknown ignored files are retained. Run `cleanup` from the repository's persistent checkout with `--worktree` naming the completed linked worktree. Native guards must pass; the main checkout, the base branch, a task branch another worktree uses, and a changed/dirty/untracked/locked/current checkout or active Git index lock are retained. Cleanup does not manufacture delivery proof. Use `python3 -B` for the cleanup invocation so Python does not create new bytecode artifacts.

Cleanup requires the captured origin URL to remain the fetch and sole push endpoint. Multiple or differing push URLs and initialized submodules are retained for a repository-owned cleanup procedure; the generic command never force-removes them. Dirty submodule checks override Git's ignore settings.

Record returned results at the same relative plan path in the persistent checkout, recovering the plan from the verified merged revision before removal if needed. Preserve unrelated edits there. Source changes invalidate affected build proof; external outages do not erase valid local checks. Remote branch protection remains project-owned: a repository admin requires the checks at the repository's Settings, Rules, Rulesets, New branch ruleset (Require status checks to pass). This implementation does not change server rules or claim to control unrelated clients.
