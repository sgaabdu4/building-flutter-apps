#!/usr/bin/env python3
"""Codex-native eval harness for the building-flutter-apps skill.

Runs three project-local eval modes:

- quality: ask Codex to answer with the local skill, then judge the answer
  against each case's expectation checklist.
- trigger: ask Codex to classify whether the skill description should trigger.
- routing: ask Codex whether to invoke and which Trigger Map refs to read.

This intentionally stays independent from the Claude-oriented harnesses so the
same eval files can be exercised with OpenAI model ids such as gpt-5.4-mini.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any


DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_PASS_THRESHOLD = 0.8


JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "expectations_met": {
            "type": "array",
            "items": {"type": "boolean"},
        },
        "notes": {"type": "string"},
    },
    "required": ["expectations_met", "notes"],
    "additionalProperties": False,
}


TRIGGER_SCHEMA = {
    "type": "object",
    "properties": {
        "triggered": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["triggered", "reason"],
    "additionalProperties": False,
}


ROUTING_SCHEMA = {
    "type": "object",
    "properties": {
        "triggered": {"type": "boolean"},
        "refs": {
            "type": "array",
            "items": {"type": "string"},
        },
        "reason": {"type": "string"},
    },
    "required": ["triggered", "refs", "reason"],
    "additionalProperties": False,
}


def parse_skill_md(skill_path: Path) -> tuple[str, str, str]:
    text = (skill_path / "SKILL.md").read_text()
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not match:
        raise ValueError(f"No frontmatter found in {skill_path / 'SKILL.md'}")

    header, body = match.groups()
    name = ""
    desc_lines: list[str] = []
    in_description = False

    for line in header.splitlines():
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip().strip('"')
            in_description = False
            continue
        if line.startswith("description:"):
            raw = line.split(":", 1)[1].strip()
            in_description = raw in {">", ">-", "|", "|-"}
            if not in_description:
                desc_lines.append(raw.strip('"'))
            continue
        if in_description:
            if line and not line.startswith(" ") and ":" in line:
                in_description = False
            else:
                desc_lines.append(line.strip())

    description = " ".join(part for part in desc_lines if part).strip()
    if not name or not description:
        raise ValueError("SKILL.md must include name and description frontmatter")
    return name, description, body


def load_eval_items(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        return list(data.get("evals", []))
    if isinstance(data, list):
        return list(data)
    raise ValueError(f"Unsupported eval file shape: {path}")


def extract_first_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        char = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : idx + 1])
                except json.JSONDecodeError:
                    return None
    return None


def parse_tokens(stderr: str) -> int | None:
    match = re.search(r"tokens used\s+([\d,]+)", stderr, re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def timeout_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def public_path(path: Path, *, base: Path) -> str:
    resolved = path.resolve()
    base = base.resolve()
    try:
        relative = resolved.relative_to(base)
        return "." if str(relative) == "." else str(relative)
    except ValueError:
        pass

    home = Path.home().resolve()
    try:
        return "$HOME/" + str(resolved.relative_to(home))
    except ValueError:
        return str(resolved)


def sanitize_text(text: str) -> str:
    return text.replace(str(Path.home()), "$HOME")


def sanitize_json(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, list):
        return [sanitize_json(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize_json(item) for key, item in value.items()}
    return value


def codex_exec(
    prompt: str,
    *,
    model: str,
    cwd: Path,
    timeout: int,
    output_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    schema_path: str | None = None
    try:
        cmd = [
            "codex",
            "exec",
            "--model",
            model,
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--color",
            "never",
        ]
        if output_schema is not None:
            with tempfile.NamedTemporaryFile("w", suffix=".schema.json", delete=False) as f:
                json.dump(output_schema, f)
                schema_path = f.name
            cmd.extend(["--output-schema", schema_path])
        cmd.append("-")

        start = time.time()
        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                timeout=timeout,
                env=os.environ.copy(),
            )
            duration = time.time() - start
            return {
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "duration_seconds": round(duration, 2),
                "tokens_used": parse_tokens(proc.stderr),
            }
        except subprocess.TimeoutExpired as error:
            duration = time.time() - start
            stdout = timeout_text(error.stdout)
            stderr = timeout_text(error.stderr)
            stderr = f"{stderr}\nTIMEOUT after {timeout}s".strip()
            return {
                "returncode": 124,
                "stdout": stdout,
                "stderr": stderr,
                "duration_seconds": round(duration, 2),
                "tokens_used": parse_tokens(stderr),
            }
    finally:
        if schema_path:
            Path(schema_path).unlink(missing_ok=True)


def build_answer_prompt(skill_path: Path, user_prompt: str) -> str:
    return f"""This is a skill-output evaluation, not a workspace mutation.

Use the local skill at:
{skill_path}

Read SKILL.md first. If SKILL.md routes this request to specific references,
read only the relevant referenced files before answering. Do not edit files.
Answer the user's Flutter/Dart request directly and concisely. Include only the
code snippets or review notes needed for the request. Prefer compact,
expectation-covering examples over full app dumps.

User prompt:
{user_prompt}
"""


def build_judge_prompt(
    original_prompt: str,
    expectations: list[str],
    response_text: str,
) -> str:
    checklist = "\n".join(f"{idx + 1}. {item}" for idx, item in enumerate(expectations))
    return f"""You are grading an answer to a Flutter/Dart skill eval.

Return JSON only. For each expectation, mark true only when the answer clearly
satisfies it. The expectations_met array must have exactly {len(expectations)}
booleans in the same order.

User prompt:
{original_prompt}

Expectation checklist:
{checklist}

Answer:
{response_text}
"""


def run_quality_case(
    item: dict[str, Any],
    *,
    skill_path: str,
    model: str,
    judge_model: str,
    timeout: int,
    judge_timeout: int,
    pass_threshold: float,
    include_excerpts: bool,
) -> dict[str, Any]:
    expectations = list(item["expectations"])
    answer = codex_exec(
        build_answer_prompt(Path(skill_path), item["prompt"]),
        model=model,
        cwd=Path(skill_path),
        timeout=timeout,
    )
    if answer["returncode"] != 0:
        result = {
            "id": item.get("id"),
            "pass": False,
            "met": 0,
            "total": len(expectations),
            "score": 0.0,
            "expectations_met": [False] * len(expectations),
            "notes": "answerer command failed",
            "response_length": len(answer["stdout"]),
            "duration_seconds": answer["duration_seconds"],
            "tokens_used": answer["tokens_used"],
            "returncode": answer["returncode"],
        }
        if include_excerpts:
            result["prompt"] = item["prompt"]
            result["response_excerpt"] = answer["stdout"][-1200:]
            result["stderr_excerpt"] = answer["stderr"][-1200:]
        return result

    judge = codex_exec(
        build_judge_prompt(item["prompt"], expectations, answer["stdout"]),
        model=judge_model,
        cwd=Path(skill_path),
        timeout=judge_timeout,
        output_schema=JUDGE_SCHEMA,
    )
    parsed = extract_first_json_object(judge["stdout"])
    raw_met = parsed.get("expectations_met") if isinstance(parsed, dict) else None
    if not isinstance(raw_met, list) or len(raw_met) != len(expectations):
        expectations_met = [False] * len(expectations)
        notes = "judge returned invalid JSON shape"
    else:
        expectations_met = [bool(value) for value in raw_met]
        notes = str(parsed.get("notes", "")).strip() if isinstance(parsed, dict) else ""

    met = sum(1 for value in expectations_met if value)
    score = met / len(expectations) if expectations else 0.0
    result = {
        "id": item.get("id"),
        "pass": score >= pass_threshold,
        "met": met,
        "total": len(expectations),
        "score": round(score, 4),
        "expectations_met": expectations_met,
        "notes": notes,
        "response_length": len(answer["stdout"]),
        "duration_seconds": round(answer["duration_seconds"] + judge["duration_seconds"], 2),
        "tokens_used": (answer["tokens_used"] or 0) + (judge["tokens_used"] or 0),
        "answer_tokens_used": answer["tokens_used"],
        "judge_tokens_used": judge["tokens_used"],
        "judge_returncode": judge["returncode"],
    }
    if include_excerpts:
        result["prompt"] = item["prompt"]
        result["response_excerpt"] = answer["stdout"][-1200:]
        result["judge_stderr_excerpt"] = judge["stderr"][-1200:]
    return result


def build_trigger_prompt(skill_name: str, description: str, query: str) -> str:
    return f"""Decide whether Codex should invoke this skill before answering.

Skill name:
{skill_name}

Skill description:
{description}

User query:
{query}

Return JSON only:
{{"triggered": true|false, "reason": "<short reason>"}}
"""


def extract_trigger_map(skill_body: str) -> str:
    match = re.search(r"## Trigger Map\n(?P<body>.*?)(?:\n## |\Z)", skill_body, re.S)
    if not match:
        return ""
    return match.group("body").strip()


def build_routing_prompt(
    skill_name: str,
    description: str,
    trigger_map: str,
    query: str,
) -> str:
    return f"""Decide whether Codex should invoke this skill and, if invoked, which
Trigger Map references it should read before acting.

Use exact relative Markdown paths from the Trigger Map, such as
`references/state-management/async-mutations.md`. Prefer the narrowest matching
row. Scenario/subsystem rows own incidental stack/file words. Do not include
bulky parent refs when a scenario row exists. Return no refs when the skill
should not trigger.

Skill name:
{skill_name}

Skill description:
{description}

Trigger Map:
{trigger_map}

User query:
{query}

Return JSON only:
{{"triggered": true|false, "refs": ["references/..."], "reason": "<short reason>"}}
"""


def trigger_map_aliases(trigger_map: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", trigger_map):
        ref = target.split("#", 1)[0].strip().removeprefix("./")
        if not ref or "://" in ref:
            continue
        aliases[ref] = ref
        aliases[Path(ref).name] = ref
        aliases[f"references/{Path(ref).name}"] = ref
    return aliases


def normalized_refs(value: Any, aliases: dict[str, str] | None = None) -> set[str]:
    if not isinstance(value, list):
        return set()
    refs: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        ref = item.strip().strip("`").strip()
        ref = ref.removeprefix("./")
        ref = ref.split("#", 1)[0]
        if aliases:
            ref = aliases.get(ref, ref)
        if ref:
            refs.add(ref)
    return refs


def run_routing_case(
    item: dict[str, Any],
    *,
    skill_name: str,
    description: str,
    trigger_map: str,
    skill_path: str,
    model: str,
    timeout: int,
    include_excerpts: bool,
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    parsed: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    for _ in range(2):
        result = codex_exec(
            build_routing_prompt(skill_name, description, trigger_map, item["query"]),
            model=model,
            cwd=Path(skill_path),
            timeout=timeout,
            output_schema=ROUTING_SCHEMA,
        )
        attempts.append(result)
        parsed = extract_first_json_object(result["stdout"])
        if isinstance(parsed, dict):
            break

    assert result is not None
    triggered = bool(parsed.get("triggered")) if isinstance(parsed, dict) else False
    aliases = trigger_map_aliases(trigger_map)
    refs = normalized_refs(parsed.get("refs"), aliases) if isinstance(parsed, dict) else set()
    reason = str(parsed.get("reason", "")).strip() if isinstance(parsed, dict) else "invalid JSON"

    should_trigger = bool(item["should_trigger"])
    expected_refs = set(item.get("expected_refs", []))
    forbidden_refs = set(item.get("forbidden_refs", []))
    max_refs = int(item.get("max_refs", 4))

    missing_refs = sorted(expected_refs - refs)
    forbidden_selected = sorted(forbidden_refs & refs)
    too_many_refs = len(refs) > max_refs
    refs_when_skipped = bool(refs) if not should_trigger else False

    passed = (
        triggered == should_trigger
        and not missing_refs
        and not forbidden_selected
        and not too_many_refs
        and not refs_when_skipped
        and result["returncode"] == 0
    )

    output = {
        "id": item.get("id"),
        "should_trigger": should_trigger,
        "triggered": triggered,
        "pass": passed,
        "refs": sorted(refs),
        "expected_refs": sorted(expected_refs),
        "missing_refs": missing_refs,
        "forbidden_selected": forbidden_selected,
        "too_many_refs": too_many_refs,
        "duration_seconds": round(sum(attempt["duration_seconds"] for attempt in attempts), 2),
        "tokens_used": sum((attempt.get("tokens_used") or 0) for attempt in attempts),
        "returncode": result["returncode"],
        "attempts": len(attempts),
        "reason": reason,
    }
    if include_excerpts:
        output["query"] = item["query"]
        output["stdout_excerpt"] = result["stdout"][-1200:]
        output["stderr_excerpt"] = result["stderr"][-1200:]
    return output


def run_trigger_case(
    item: dict[str, Any],
    *,
    skill_name: str,
    description: str,
    skill_path: str,
    model: str,
    timeout: int,
    trigger_threshold: float,
    runs_per_query: int,
    include_excerpts: bool,
) -> dict[str, Any]:
    triggered_runs: list[bool] = []
    reasons: list[str] = []
    total_duration = 0.0
    total_tokens = 0

    for _ in range(runs_per_query):
        result = codex_exec(
            build_trigger_prompt(skill_name, description, item["query"]),
            model=model,
            cwd=Path(skill_path),
            timeout=timeout,
            output_schema=TRIGGER_SCHEMA,
        )
        total_duration += result["duration_seconds"]
        total_tokens += result["tokens_used"] or 0
        parsed = extract_first_json_object(result["stdout"])
        triggered = bool(parsed.get("triggered")) if isinstance(parsed, dict) else False
        reason = str(parsed.get("reason", "")).strip() if isinstance(parsed, dict) else "invalid JSON"
        triggered_runs.append(triggered)
        reasons.append(reason)

    trigger_rate = sum(triggered_runs) / len(triggered_runs)
    should_trigger = bool(item["should_trigger"])
    passed = trigger_rate >= trigger_threshold if should_trigger else trigger_rate < trigger_threshold
    result = {
        "case_index": item.get("_case_index"),
        "should_trigger": should_trigger,
        "pass": passed,
        "trigger_rate": trigger_rate,
        "triggers": sum(triggered_runs),
        "runs": len(triggered_runs),
        "duration_seconds": round(total_duration, 2),
        "tokens_used": total_tokens,
    }
    if include_excerpts:
        result["query"] = item["query"]
        result["reasons"] = reasons
    return result


def run_pool(
    fn: Any,
    items: list[dict[str, Any]],
    *,
    num_workers: int,
    kwargs: dict[str, Any],
) -> list[dict[str, Any]]:
    if num_workers == 1:
        return [fn(item, **kwargs) for item in items]

    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(fn, item, **kwargs) for item in items]
        for future in as_completed(futures):
            results.append(future.result())
    return results


def summarize_quality(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for item in results if item["pass"])
    expectations = sum(item["total"] for item in results)
    met = sum(item["met"] for item in results)
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "expectations_met": met,
        "expectations_total": expectations,
        "mean_expectation_rate": round(met / expectations, 4) if expectations else 0.0,
        "duration_seconds": round(sum(item["duration_seconds"] for item in results), 2),
        "tokens_used": sum(item.get("tokens_used") or 0 for item in results),
    }


def summarize_trigger(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for item in results if item["pass"])
    false_negatives = sum(
        1 for item in results if item["should_trigger"] and not item["pass"]
    )
    false_positives = sum(
        1 for item in results if not item["should_trigger"] and not item["pass"]
    )
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "false_negatives": false_negatives,
        "false_positives": false_positives,
        "duration_seconds": round(sum(item["duration_seconds"] for item in results), 2),
        "tokens_used": sum(item.get("tokens_used") or 0 for item in results),
    }


def summarize_routing(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for item in results if item["pass"])
    false_negatives = sum(
        1 for item in results if item["should_trigger"] and not item["triggered"]
    )
    false_positives = sum(
        1 for item in results if not item["should_trigger"] and item["triggered"]
    )
    routing_misses = sum(
        1 for item in results if item["should_trigger"] and item["missing_refs"]
    )
    over_reads = sum(
        1
        for item in results
        if item["forbidden_selected"] or item["too_many_refs"]
    )
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "false_negatives": false_negatives,
        "false_positives": false_positives,
        "routing_misses": routing_misses,
        "over_reads": over_reads,
        "duration_seconds": round(sum(item["duration_seconds"] for item in results), 2),
        "tokens_used": sum(item.get("tokens_used") or 0 for item in results),
    }


def filter_items(items: list[dict[str, Any]], limit: int | None, ids: str | None) -> list[dict[str, Any]]:
    if ids:
        selected = {int(part) for part in ids.split(",") if part.strip()}
        items = [item for item in items if item.get("id") in selected]
    if limit is not None:
        items = items[:limit]
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description="Run building-flutter-apps evals with Codex")
    parser.add_argument("mode", choices=["quality", "trigger", "routing"])
    parser.add_argument("--skill-path", required=True)
    parser.add_argument("--eval-set", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--num-workers", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--judge-timeout", type=int, default=180)
    parser.add_argument("--pass-threshold", type=float, default=DEFAULT_PASS_THRESHOLD)
    parser.add_argument("--trigger-threshold", type=float, default=0.5)
    parser.add_argument("--runs-per-query", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--ids", default=None, help="Comma-separated quality eval ids")
    parser.add_argument("--output", default=None)
    parser.add_argument("--include-excerpts", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    skill_path = Path(args.skill_path).resolve()
    eval_path = Path(args.eval_set).resolve()
    skill_name, description, skill_body = parse_skill_md(skill_path)
    items = filter_items(load_eval_items(eval_path), args.limit, args.ids)
    for index, item in enumerate(items, 1):
        item["_case_index"] = index

    if args.mode == "quality":
        results = run_pool(
            run_quality_case,
            items,
            num_workers=args.num_workers,
            kwargs={
                "skill_path": str(skill_path),
                "model": args.model,
                "judge_model": args.judge_model or args.model,
                "timeout": args.timeout,
                "judge_timeout": args.judge_timeout,
                "pass_threshold": args.pass_threshold,
                "include_excerpts": args.include_excerpts,
            },
        )
        results.sort(key=lambda item: (item.get("id") is None, item.get("id")))
        summary = summarize_quality(results)
    elif args.mode == "trigger":
        results = run_pool(
            run_trigger_case,
            items,
            num_workers=args.num_workers,
            kwargs={
                "skill_name": skill_name,
                "description": description,
                "skill_path": str(skill_path),
                "model": args.model,
                "timeout": args.timeout,
                "trigger_threshold": args.trigger_threshold,
                "runs_per_query": args.runs_per_query,
                "include_excerpts": args.include_excerpts,
            },
        )
        summary = summarize_trigger(results)
    else:
        results = run_pool(
            run_routing_case,
            items,
            num_workers=args.num_workers,
            kwargs={
                "skill_name": skill_name,
                "description": description,
                "trigger_map": extract_trigger_map(skill_body),
                "skill_path": str(skill_path),
                "model": args.model,
                "timeout": args.timeout,
                "include_excerpts": args.include_excerpts,
            },
        )
        results.sort(key=lambda item: (item.get("id") is None, item.get("id")))
        summary = summarize_routing(results)

    output = {
        "runner": "codex",
        "mode": args.mode,
        "model": args.model,
        "judge_model": args.judge_model or args.model if args.mode == "quality" else None,
        "skill_name": skill_name,
        "skill_path": public_path(skill_path, base=Path.cwd()),
        "eval_set": public_path(eval_path, base=Path.cwd()),
        "summary": summary,
        "results": results,
    }

    output = sanitize_json(output)
    text = json.dumps(output, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text + "\n")
    if args.verbose:
        print(json.dumps(summary, indent=2), file=sys.stderr)
    print(text)


if __name__ == "__main__":
    main()
