# Evals

Two harnesses, two intents. Sizes intentionally differ.

| File | Count | Purpose |
|---|---|---|
| `evals.json` | 25 | Full skill-output evals: `prompt` + expected behaviour graded. |
| `trigger-eval.json` | 20 | Trigger-classification evals: `query` + `should_trigger` boolean for skill description gate. |

Adding cases:
- New full eval → append to `evals.json` `evals` array, increment `id`.
- New trigger eval → append `{query, should_trigger}` to `trigger-eval.json`.

Counts need not match. Trigger eval cheap (no model output graded). Full eval
expensive. Trigger coverage broader than full by design.
