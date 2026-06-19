#!/usr/bin/env python3
"""Quality eval harness for building-flutter-apps skill.

For each query in the eval set:
  1. Spawns claude -p <prompt> (answerer) — same command-file + append-system-prompt
     trick as run_trigger_eval.py so headless Claude consults the skill.
  2. Collects the FULL final assistant text response.
  3. Spawns a second claude -p (judge) — NO command file, NO skill injection —
     given the original prompt, expectations checklist, and response text; returns
     strict JSON {"expectations_met": [bool, ...], "notes": "..."}.
  4. Scores: met/total >= pass_threshold => pass.

Reuses parse_skill_md / find_project_root patterns from run_trigger_eval.py
(inlined here; do NOT import that module).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import select
import subprocess
import sys
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


# ── defaults ──────────────────────────────────────────────────────────────────

DEFAULT_APPEND_SYSTEM = (
    "PROTOCOL: Before answering any question, examine the descriptions of all "
    "slash commands available in your skills list. If any command's "
    "description matches the user's question topic (and the question is not "
    "in that command's 'Skip for' exclusion list), your FIRST tool_use of the "
    "turn MUST be the Skill tool with that exact command name. Do not call "
    "Read, Bash, Grep, or any other tool before Skill when a matching command "
    "exists. Reading the underlying SKILL.md file is NOT a substitute — you "
    "must invoke the Skill tool itself. If no command description matches, or "
    "every match is excluded by its Skip-for clause, answer directly without "
    "any tool call. This protocol is mandatory."
)

JUDGE_SYSTEM_PROMPT = (
    "You are a strict evaluator. "
    "You will be given a user prompt, an expected checklist, and an AI assistant response. "
    "For each checklist item, output true if the response satisfies it, false otherwise. "
    "Output ONLY the JSON object — no prose, no markdown, no explanation before or after. "
    "Format: {\"expectations_met\": [bool, ...], \"notes\": \"<one sentence>\"}"
)


# ── helpers ───────────────────────────────────────────────────────────────────

def parse_skill_md(skill_path: Path) -> tuple[str, str, str]:
    """Minimal YAML frontmatter parser for SKILL.md.

    Returns (name, description, body). Avoids external PyYAML dependency.
    """
    text = (skill_path / "SKILL.md").read_text()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        raise ValueError(f"No frontmatter in {skill_path}/SKILL.md")
    header, body = m.group(1), m.group(2)

    name = ""
    description = ""
    in_desc = False
    desc_lines: list[str] = []
    desc_block = False

    for line in header.split("\n"):
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip()
            in_desc = False
        elif line.startswith("description:"):
            rest = line.split(":", 1)[1].strip()
            if rest in (">", ">-", "|", "|-"):
                desc_block = True
                in_desc = True
            else:
                description = rest
                in_desc = False
        elif in_desc and desc_block and (line.startswith(" ") or line.startswith("\t") or line == ""):
            desc_lines.append(line.strip())
        elif in_desc and desc_block:
            in_desc = False
    if desc_block:
        description = " ".join(l for l in desc_lines if l).strip()
    return name, description, body


def find_project_root() -> Path:
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / ".claude").is_dir():
            return parent
    return current


def extract_first_json_object(text: str) -> str | None:
    """Extract the first balanced {...} block from text, handling strings/escapes."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(text[start:], start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


# ── answerer ──────────────────────────────────────────────────────────────────

def run_answerer(
    prompt: str,
    skill_name: str,
    skill_description: str,
    timeout: int,
    workspace_root: str,
    model: str | None = None,
    append_system_prompt: str | None = None,
) -> str:
    """Spawn claude -p and collect the full final assistant text response."""
    unique_id = uuid.uuid4().hex[:8]
    clean_name = f"{skill_name}-skill-{unique_id}"
    project_commands_dir = Path(workspace_root) / ".claude" / "commands"
    project_commands_dir.mkdir(parents=True, exist_ok=True)
    command_file = project_commands_dir / f"{clean_name}.md"

    indented_desc = "\n  ".join(skill_description.split("\n"))
    command_content = (
        f"---\n"
        f"description: |\n"
        f"  {indented_desc}\n"
        f"---\n\n"
        f"# {skill_name}\n\n"
        f"This skill handles: {skill_description}\n"
    )
    command_file.write_text(command_content)

    try:
        cmd = [
            "claude",
            "-p", prompt,
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
        ]
        if model:
            cmd.extend(["--model", model])
        if append_system_prompt:
            cmd.extend(["--append-system-prompt", append_system_prompt])

        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=workspace_root,
            env=env,
        )

        full_text: list[str] = []
        start_time = time.time()
        buffer = ""

        try:
            while True:
                if time.time() - start_time > timeout:
                    print(
                        f"[answerer] timeout after {timeout}s for prompt: {prompt[:60]}...",
                        file=sys.stderr,
                    )
                    break
                if process.poll() is not None:
                    remaining = process.stdout.read()
                    if remaining:
                        buffer += remaining.decode("utf-8", errors="replace")
                    break

                ready, _, _ = select.select([process.stdout], [], [], 1.0)
                if not ready:
                    continue

                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    etype = event.get("type", "")

                    # stream_event path: accumulate text_delta blocks
                    if etype == "stream_event":
                        se = event.get("event", {})
                        se_type = se.get("type", "")
                        if se_type == "content_block_delta":
                            delta = se.get("delta", {})
                            if delta.get("type") == "text_delta":
                                full_text.append(delta.get("text", ""))

                    # assistant message path: collect text content items
                    elif etype == "assistant":
                        message = event.get("message", {})
                        for ci in message.get("content", []):
                            if ci.get("type") == "text":
                                full_text.append(ci.get("text", ""))

                    # result event: final answer text may be here
                    elif etype == "result":
                        result_text = event.get("result", "")
                        if isinstance(result_text, str) and result_text:
                            full_text.append(result_text)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

        return "".join(full_text)
    finally:
        if command_file.exists():
            command_file.unlink()


# ── judge ─────────────────────────────────────────────────────────────────────

def run_judge(
    original_prompt: str,
    expectations: list[str],
    response_text: str,
    workspace_root: str,
    judge_timeout: int = 90,
    judge_model: str | None = None,
) -> tuple[list[bool], str]:
    """Run a second claude -p call to evaluate the response against expectations.

    Returns (expectations_met: list[bool], notes: str).
    On parse failure, returns all-False with a warning note.
    """
    checklist_lines = "\n".join(
        f"{i + 1}. {exp}" for i, exp in enumerate(expectations)
    )
    judge_prompt = (
        f"USER PROMPT:\n{original_prompt}\n\n"
        f"EXPECTATIONS CHECKLIST ({len(expectations)} items):\n{checklist_lines}\n\n"
        f"AI ASSISTANT RESPONSE:\n{response_text}\n\n"
        f"For each numbered expectation, output true if the response satisfies it, "
        f"false otherwise. The output array MUST have exactly {len(expectations)} elements "
        f"in the same order as the checklist. "
        f"Output ONLY the JSON object — no prose, no markdown fences, nothing else.\n"
        f'Format: {{"expectations_met": [bool, ...], "notes": "<one sentence>"}}'
    )

    cmd = [
        "claude",
        "-p", "-",
        "--output-format", "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--append-system-prompt", JUDGE_SYSTEM_PROMPT,
    ]
    if judge_model:
        cmd.extend(["--model", judge_model])

    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=workspace_root,
        env=env,
    )

    # Write prompt to stdin and close it so claude reads EOF
    process.stdin.write(judge_prompt.encode("utf-8"))
    process.stdin.close()

    full_text: list[str] = []
    start_time = time.time()
    buffer = ""

    try:
        while True:
            if time.time() - start_time > judge_timeout:
                print("[judge] timeout", file=sys.stderr)
                break
            if process.poll() is not None:
                remaining = process.stdout.read()
                if remaining:
                    buffer += remaining.decode("utf-8", errors="replace")
                break

            ready, _, _ = select.select([process.stdout], [], [], 1.0)
            if not ready:
                continue

            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="replace")

            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type", "")
                if etype == "stream_event":
                    se = event.get("event", {})
                    if se.get("type") == "content_block_delta":
                        delta = se.get("delta", {})
                        if delta.get("type") == "text_delta":
                            full_text.append(delta.get("text", ""))
                elif etype == "assistant":
                    for ci in event.get("message", {}).get("content", []):
                        if ci.get("type") == "text":
                            full_text.append(ci.get("text", ""))
                elif etype == "result":
                    rt = event.get("result", "")
                    if isinstance(rt, str) and rt:
                        full_text.append(rt)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()

    raw = "".join(full_text)
    json_str = extract_first_json_object(raw)
    if not json_str:
        print(
            f"[judge] WARNING: no JSON object in response. Raw (first 200): {raw[:200]}",
            file=sys.stderr,
        )
        return [False] * len(expectations), "judge parse failed — no JSON object found"

    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"[judge] WARNING: JSON parse error: {e}. Raw: {json_str[:200]}", file=sys.stderr)
        return [False] * len(expectations), f"judge parse failed — {e}"

    met = parsed.get("expectations_met", [])
    notes = parsed.get("notes", "")

    # Coerce to booleans and pad/truncate to match expected length
    met_bool = [bool(v) for v in met]
    if len(met_bool) != len(expectations):
        print(
            f"[judge] WARNING: expectations_met has {len(met_bool)} items, expected {len(expectations)}. Padding/truncating.",
            file=sys.stderr,
        )
        while len(met_bool) < len(expectations):
            met_bool.append(False)
        met_bool = met_bool[: len(expectations)]

    return met_bool, notes


# ── single query worker ───────────────────────────────────────────────────────

def run_single_quality_query(
    item: dict,
    skill_name: str,
    skill_description: str,
    timeout: int,
    workspace_root: str,
    pass_threshold: float,
    model: str | None,
    append_system_prompt: str | None,
    judge_model: str | None,
) -> dict:
    prompt = item["prompt"]
    expectations = item["expectations"]

    response_text = run_answerer(
        prompt=prompt,
        skill_name=skill_name,
        skill_description=skill_description,
        timeout=timeout,
        workspace_root=workspace_root,
        model=model,
        append_system_prompt=append_system_prompt,
    )

    expectations_met, notes = run_judge(
        original_prompt=prompt,
        expectations=expectations,
        response_text=response_text,
        workspace_root=workspace_root,
        judge_timeout=90,
        judge_model=judge_model,
    )

    met = sum(1 for v in expectations_met if v)
    total = len(expectations)
    score = met / total if total > 0 else 0.0
    passed = score >= pass_threshold

    return {
        "id": item.get("id"),
        "prompt": prompt[:120] + ("..." if len(prompt) > 120 else ""),
        "met": met,
        "total": total,
        "score": round(score, 4),
        "pass": passed,
        "expectations_met": expectations_met,
        "notes": notes,
        "response_length": len(response_text),
    }


# ── main eval loop ────────────────────────────────────────────────────────────

def run_quality_eval(
    eval_set: list[dict],
    skill_name: str,
    skill_description: str,
    num_workers: int,
    timeout: int,
    workspace_root: str,
    runs_per_query: int,
    pass_threshold: float,
    model: str | None,
    append_system_prompt: str | None,
    judge_model: str | None,
    verbose: bool,
) -> dict:
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        future_to_info: dict = {}
        for item in eval_set:
            for run_idx in range(runs_per_query):
                future = executor.submit(
                    run_single_quality_query,
                    item,
                    skill_name,
                    skill_description,
                    timeout,
                    workspace_root,
                    pass_threshold,
                    model,
                    append_system_prompt,
                    judge_model,
                )
                future_to_info[future] = (item, run_idx)

        # Aggregate results per query (average across runs if runs_per_query > 1)
        query_results: dict[int, list[dict]] = {}
        for future in as_completed(future_to_info):
            item, _ = future_to_info[future]
            qid = item.get("id", item["prompt"][:40])
            if qid not in query_results:
                query_results[qid] = []
            try:
                query_results[qid].append(future.result())
            except Exception as e:
                print(f"[eval] WARNING: query id={qid} run failed: {e}", file=sys.stderr)
                # Synthesise a failed result
                query_results[qid].append(
                    {
                        "id": item.get("id"),
                        "prompt": item["prompt"][:120],
                        "met": 0,
                        "total": len(item["expectations"]),
                        "score": 0.0,
                        "pass": False,
                        "expectations_met": [False] * len(item["expectations"]),
                        "notes": f"run error: {e}",
                        "response_length": 0,
                    }
                )

    results: list[dict] = []
    for qid, runs in query_results.items():
        # Average score across runs; pass if average score meets threshold
        avg_score = sum(r["score"] for r in runs) / len(runs)
        avg_met = sum(r["met"] for r in runs) / len(runs)
        total_exps = runs[0]["total"]
        passed = avg_score >= pass_threshold
        results.append(
            {
                "id": runs[0]["id"],
                "prompt": runs[0]["prompt"],
                "avg_score": round(avg_score, 4),
                "avg_met": round(avg_met, 2),
                "total_expectations": total_exps,
                "pass": passed,
                "runs": runs,
            }
        )

    # Sort by id for stable output
    results.sort(key=lambda r: (r["id"] is None, r["id"]))

    passed_count = sum(1 for r in results if r["pass"])
    total_count = len(results)
    mean_score = sum(r["avg_score"] for r in results) / total_count if total_count else 0.0

    if verbose:
        for r in results:
            status = "PASS" if r["pass"] else "FAIL"
            print(
                f"  [{status}] id={r['id']} score={r['avg_score']:.2f} "
                f"({r['avg_met']:.1f}/{r['total_expectations']}): {r['prompt'][:70]}",
                file=sys.stderr,
            )

    return {
        "skill_name": skill_name,
        "pass_threshold": pass_threshold,
        "append_system_prompt": append_system_prompt,
        "results": results,
        "summary": {
            "total": total_count,
            "passed": passed_count,
            "failed": total_count - passed_count,
            "mean_expectation_rate": round(mean_score, 4),
        },
    }


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Quality eval harness — checks skill answers against expectation checklists"
    )
    parser.add_argument("--skill-path", required=True, help="Path to skill directory containing SKILL.md")
    parser.add_argument("--eval-set", required=True, help="Path to evals.json")
    parser.add_argument("--workspace-root", default=".",
                        help="cwd for answerer subprocess (must have .claude/)")
    parser.add_argument("--num-workers", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=240, help="Answerer timeout in seconds")
    parser.add_argument("--runs-per-query", type=int, default=1)
    parser.add_argument("--pass-threshold", type=float, default=0.8,
                        help="Fraction of expectations that must be met to pass (default 0.8)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only run the first N queries from the eval set")
    parser.add_argument("--model", default=None, help="Model for answerer claude calls")
    parser.add_argument("--judge-model", default=None, help="Model for judge claude calls (default: same as --model)")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--append-system-prompt",
        default=DEFAULT_APPEND_SYSTEM,
        help="System prompt appended to answerer claude -p call",
    )
    parser.add_argument("--no-append-system-prompt", action="store_true",
                        help="Disable system-prompt injection for the answerer")
    args = parser.parse_args()

    skill_path = Path(args.skill_path)
    if not (skill_path / "SKILL.md").exists():
        print(f"Error: No SKILL.md at {skill_path}", file=sys.stderr)
        sys.exit(1)

    name, description, _ = parse_skill_md(skill_path)

    raw = json.loads(Path(args.eval_set).read_text())
    # evals.json has top-level "evals" array
    eval_set: list[dict] = raw["evals"] if isinstance(raw, dict) and "evals" in raw else raw
    if args.limit:
        eval_set = eval_set[: args.limit]

    append_sys = None if args.no_append_system_prompt else (args.append_system_prompt or None)
    judge_model = args.judge_model or args.model  # fall back to same model as answerer

    workspace_root = args.workspace_root

    if args.verbose:
        print(f"Skill: {name}", file=sys.stderr)
        print(f"Eval queries: {len(eval_set)}", file=sys.stderr)
        print(f"Pass threshold: {args.pass_threshold}", file=sys.stderr)
        print(f"Workspace root: {workspace_root}", file=sys.stderr)
        print(
            f"Append-system-prompt: {'(none)' if not append_sys else append_sys[:100] + '...'}",
            file=sys.stderr,
        )

    output = run_quality_eval(
        eval_set=eval_set,
        skill_name=name,
        skill_description=description,
        num_workers=args.num_workers,
        timeout=args.timeout,
        workspace_root=workspace_root,
        runs_per_query=args.runs_per_query,
        pass_threshold=args.pass_threshold,
        model=args.model,
        append_system_prompt=append_sys,
        judge_model=judge_model,
        verbose=args.verbose,
    )

    if args.verbose:
        s = output["summary"]
        print(
            f"\nSummary: {s['passed']}/{s['total']} passed | "
            f"mean expectation rate: {s['mean_expectation_rate']:.2%}",
            file=sys.stderr,
        )

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
