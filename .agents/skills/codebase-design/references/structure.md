# Ownership + public contracts

- Evidence = accepted behavior + actual owner, callers and dependencies. Identify knowledge leaking into callers: policy, storage shape, ordering, state, errors or repeated coordination.
- Change = delete an unnecessary concept, consolidate behavior or deepen the existing owner's interface. A renamed pass-through wrapper does not hide complexity; an internal test shortcut alone does not justify a new public seam.
- Contract = meaningful entry points, inputs/results, invariants, errors + side effects. Show a real caller before/after; name what callers no longer need to know.
- Alternatives = compare materially different contracts only when the trade-off matters. Judge caller simplicity, hidden policy, coupling + migration cost; do not manufacture options for a settled local change.
- Proof = trace affected callers, stored data, keys/caches, routes + integration boundaries. Verify preserved public behavior and the failure the old structure permitted. Report the selected owner, removed complexity + unresolved trade-offs.
