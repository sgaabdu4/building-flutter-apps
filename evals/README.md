# Evals

Two harnesses, two intents. They are intentionally different sizes.

| File | Count | Purpose |
|---|---|---|
| `evals.json` | 25 | Full skill-output evals: each case has a `prompt` + expected behaviour the skill is graded on. |
| `trigger-eval.json` | 20 | Trigger-classification evals: each case has a `query` + boolean `should_trigger` for the skill description gate. |

Adding cases:
- New full eval → append to `evals.json`'s `evals` array, increment `id`.
- New trigger eval → append a `{query, should_trigger}` entry to `trigger-eval.json`.

The counts do not need to match. A trigger eval is much cheaper than a full
eval (no model output graded), so trigger coverage is broader than full
coverage by design.
