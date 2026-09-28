# Review method

- Target = identify the requested artifact + comparison base. Use the supplied PR/base; otherwise resolve the branch's intended target from repository evidence. Upstream tracking alone may identify the same branch, not its merge target. Unclear scope → state the gap before drawing conclusions.
- Diff = read full hunks + affected owners/callers. Branch/PR → cumulative diff against its merge-base; commit → requested patch; working tree → staged + unstaged + in-scope untracked files. Include local changes in a branch review only when in scope. Empty diff → no changes to review, not a failed review.
- Intent = compare against the user's request and supplied/linked requirements. Check missing behavior, changed contracts + unsupported additions. Missing requirements → state that limit; do not infer intent from the implementation itself.
- Claims = trace the failure scenario through actual data, state, permissions, ordering or callers. For plans/diagnoses/proof, separate proposed behavior from implemented behavior and claimed results from observed results.
- Tests = apply [Test design + quality](../../he/references/testing.md) to affected tests and claimed proof. Passing gates do not establish requirement coverage, realistic UI behavior or deployed success.
- Finding = precise location + code/evidence fact + triggering condition + concrete impact + smallest useful correction. Rank by impact and likelihood. Remove preference-only, duplicate, speculative and already-disproved candidates; an unresolved question is not a confirmed defect.
- Result = actionable findings first, then material coverage limits + unverified checks. No findings → say so without implying unperformed verification or approval of unknown behavior.
