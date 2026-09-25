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

python3 tool/run_routing_eval.py \
  --skill-path skills/building-flutter-apps \
  --eval-set evals/routing-eval.json \
  --verbose > evals/results/routing.json

python3 tool/check_skill_routing.py
```

- `run_routing_eval.py` = live routing. Temp command carries the full `SKILL.md` body; refs = `references/...` files the model reads (`Read`/`Bash`) or cites in its answer. Pass = activation matches `should_trigger` + every `expected_refs` hit + no `forbidden_refs` + ref count ≤ `max_refs` + run completed. `Edit`/`Write` are disallowed during the run.
- `--limit N` (routing, quality) = first N cases only; use for a cheap smoke run.
- `check_skill_routing.py` = static, no model: named refs exist, expected refs linked from `SKILL.md`, required guard cases present.
- Generated results stay untracked.
