# Evals

Two harnesses, two intents. Sizes intentionally differ.

| File | Count | Purpose |
|---|---|---|
| `evals.json` | 33 | Full skill-output evals: `prompt` + expected behaviour graded. |
| `trigger-eval.json` | 24 | Trigger-classification evals: `query` + `should_trigger` boolean for skill description gate. |

Adding cases:
- New full eval → append to `evals.json` `evals` array, increment `id`.
- New trigger eval → append `{query, should_trigger}` to `trigger-eval.json`.

Counts need not match. Trigger eval cheap (no model output graded). Full eval
expensive. Trigger coverage broader than full by design.

Codex/GPT evals:

```bash
python3 tool/run_codex_eval.py trigger \
  --skill-path . \
  --eval-set evals/trigger-eval.json \
  --model gpt-5.4-mini \
  --output evals/results/trigger-gpt-5.4-mini.json

python3 tool/run_codex_eval.py quality \
  --skill-path . \
  --eval-set evals/evals.json \
  --model gpt-5.4-mini \
  --output evals/results/quality-gpt-5.4-mini.json
```
