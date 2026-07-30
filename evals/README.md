# Evals

## Read first

- Trigger classification = `trigger-eval.json`.
- Progressive-disclosure routing = `routing-eval.json`.
- Answer policy = `evals.json`.
- Generated outputs = local-only `evals/results/`; never canonical package state.

## Suites

| File | Cases | Contract |
|---|---:|---|
| `evals.json` | 52 | Prompt + graded expectations. |
| `trigger-eval.json` | 44 | Query + activation decision. |
| `routing-eval.json` | 42 | Activation + exact refs + maximum read breadth. |

## Add cases

- Full answer regression → append next `id` under `evals.json` → update count.
- Trigger regression → append `{query, should_trigger}` → update count.
- Routing regression → append `{id, query, should_trigger, expected_refs, forbidden_refs, max_refs}` → update count.
- Routing coverage = primary progressive-disclosure proof.
- Full answer eval = behavior regression only.

## Run

```bash
python3 tool/run_codex_eval.py trigger \
  --skill-path skills/building-flutter-apps \
  --eval-set evals/trigger-eval.json \
  --model luna-5.6 \
  --reasoning-effort xhigh \
  --output evals/results/trigger-luna-5.6-xhigh.json

python3 tool/run_codex_eval.py routing \
  --skill-path skills/building-flutter-apps \
  --eval-set evals/routing-eval.json \
  --model luna-5.6 \
  --reasoning-effort xhigh \
  --output evals/results/routing-luna-5.6-xhigh.json

python3 tool/run_codex_eval.py quality \
  --skill-path skills/building-flutter-apps \
  --eval-set evals/evals.json \
  --model luna-5.6 \
  --reasoning-effort xhigh \
  --output evals/results/quality-luna-5.6-xhigh.json
```

Temporary debugging → add `--include-excerpts`; generated results stay untracked.
