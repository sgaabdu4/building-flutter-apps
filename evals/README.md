# Evals

Three harnesses, three intents. Sizes intentionally differ.

| File | Count | Purpose |
|---|---|---|
| `evals.json` | 45 | Full skill-output evals: `prompt` + expected behaviour graded. |
| `trigger-eval.json` | 38 | Trigger-classification evals: `query` + `should_trigger` boolean for skill description gate. |
| `routing-eval.json` | 30 | Broad invocation/routing evals: trigger decision plus exact Trigger Map refs and forbidden over-reads. |

Adding cases:
- New full eval → append to `evals.json` `evals` array, increment `id`.
- New trigger eval → append `{query, should_trigger}` to `trigger-eval.json`.
- New routing eval → append `{id, query, should_trigger, expected_refs, forbidden_refs, max_refs}` to `routing-eval.json`.

Counts need not match. Trigger and routing evals are cheap. Full output evals
are expensive and should be reserved for behavior regressions. Routing coverage
is the primary check for progressive disclosure and broad skill invocation.

Codex/GPT evals:

```bash
python3 tool/run_codex_eval.py trigger \
  --skill-path . \
  --eval-set evals/trigger-eval.json \
  --model gpt-5.4-mini \
  --output evals/results/trigger-gpt-5.4-mini.json

python3 tool/run_codex_eval.py routing \
  --skill-path . \
  --eval-set evals/routing-eval.json \
  --model gpt-5.4-mini \
  --output evals/results/routing-gpt-5.4-mini.json

python3 tool/run_codex_eval.py quality \
  --skill-path . \
  --eval-set evals/evals.json \
  --model gpt-5.4-mini \
  --output evals/results/quality-gpt-5.4-mini.json
```

Artifacts are compact by default: paths are written relative to the repo or
`$HOME`, and answer/stderr excerpts are omitted. Add `--include-excerpts` only
for temporary local debugging.
