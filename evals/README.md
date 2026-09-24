# Evals

## Read first

- Trigger classification = `trigger-eval.json`.
- Progressive-disclosure routing = `routing-eval.json`.
- Answer policy = `evals.json`.
- Generated outputs = local-only `evals/results/`; never canonical package state.

## Suites

| File | Cases | Contract |
|---|---:|---|
| `evals.json` | 56 | Prompt + graded expectations. |
| `trigger-eval.json` | 44 | Query + activation decision. |
| `routing-eval.json` | 45 | Activation + exact refs + maximum read breadth. |

## Add cases

- Full answer regression → append next `id` under `evals.json` → update count.
- Trigger regression → append `{query, should_trigger}` → update count.
- Routing regression → append `{id, query, should_trigger, expected_refs, forbidden_refs, max_refs}` → update count.
- Routing coverage = primary progressive-disclosure proof.
- Full answer eval = behavior regression only.

## Run

- Live runners = headless `claude -p`; need the Claude CLI on `PATH` and a repo root containing `.claude/`.
- Results = JSON on stdout; `--verbose` = per-case summary on stderr.
- `--model` optional; omit = CLI default.

```bash
mkdir -p evals/results

python3 tool/run_trigger_eval.py \
  --skill-path skills/building-flutter-apps \
  --eval-set evals/trigger-eval.json \
  --verbose > evals/results/trigger.json

python3 tool/run_quality_eval.py \
  --skill-path skills/building-flutter-apps \
  --eval-set evals/evals.json \
  --verbose > evals/results/quality.json

python3 tool/check_skill_routing.py
```

- `routing-eval.json` = no live runner. `check_skill_routing.py` checks statically: named refs exist, expected refs linked from `SKILL.md`, required guard cases present. Never checks which refs a model reads or `max_refs`. Activation only → `run_trigger_eval.py --eval-set evals/routing-eval.json` (reads `query` + `should_trigger`).
- Generated results stay untracked.
