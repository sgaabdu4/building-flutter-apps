# Work + verification

- Task mode = for a new feature request, reuse the user's stated Human-loop/Autonomous choice; if absent, ask once. Apply only to that task, preserve it on continuation and allow the user to change it. Existing task authorization remains valid; do not restart mode selection for each step. Mode governs participation, not tool permissions or authority for external actions.
- Planning = before new implementation or material scope changes, use [he-plan](../../he-plan/SKILL.md). Existing ready + authorized plan → continue; reviews/explanations alone need no new plan. Readiness and authorization belong to he-plan; completion checks are not a start-of-work barrier.
- Context = read root `PRODUCT.md` + `DESIGN.md` before implementation. Missing/empty → study existing docs, code + relevant interface; fill [PRODUCT](../templates/PRODUCT.md) / [DESIGN](../templates/DESIGN.md) from evidence. Preserve existing content; unknown product/design choices stay explicit.
- Product = actual users, problem, purpose + boundaries per [product.md](https://product.md/). Design = observed tokens/components per [design.md](https://github.com/google-labs-code/design.md/blob/main/docs/spec.md); use [Atomic Design](https://atomicdesign.bradfrost.com/chapter-2/) to describe existing UI, not force a restructure. No visual UI → document the actual interface.
- Isolation = start new implementation in a task branch/worktree before code changes; reuse that task's existing isolation on continuation. Preserve other tasks and shared state. PR delivery is the default; [HE Ship](../../he-ship/SKILL.md) owns verification and safe cleanup after the requested delivery.
- Build = [HE Build](../../he-build/SKILL.md) owns local implementation, verification and Ready for ship in the same plan. [HE Ship](../../he-ship/SKILL.md) owns authorized PR/merge/delivery actions and remote proof. Review-only work stays with its review owner; local Complete does not mean the overall delivery is finished.
- Learning + steering = use [HE Learn](../../he-learn/SKILL.md) for repeated failures or lasting decisions; session/failure checkpoints remind once at those boundaries. Ordinary prompts/tools need no callback. Prefer deterministic prevention; skills are the last resort. Capture accepted durable choices in `docs/adr/` and read applicable ADRs on the next affected task; routine steering stays in the plan. A hook prompt proves neither learning nor prevention.
- Mutation = optional; present changed-function scope, covering tests + estimated runtime; obtain acceptance before running.

## Participation

| Mode | Planning behavior |
| --- | --- |
| Human-loop | Resolve grouped material questions, show the grounded UX and completed plan, then request one combined approval covering plan + UX + execution recommendation. Reuse approval of that proposal; the initial feature request alone is not proposal approval. |
| Autonomous | Study and prepare without routine approval stops; provide concise progress. Still ask unresolved material questions and show/inspect applicable UX references. Choose reversible details within the user's constraints; initial authorization covers proceeding once ready. |

- Neither mode permits inventing user answers, skipping UX/baseline proof or crossing an unauthorized boundary. A mode name alone does not authorize publication, production changes or other external actions beyond the task's agreed delivery scope.
