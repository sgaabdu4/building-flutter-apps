#!/usr/bin/env python3
"""Project-local trigger eval for building-flutter-apps skill.

Forked from ~/.claude/skills/skill-creator/scripts/run_eval.py.

Difference: injects `--append-system-prompt` into the `claude -p` call so
headless mode evaluates available slash-command descriptions before answering
from training data. The default headless behaviour answers Flutter questions
directly without consulting the skill, which makes pure-description triggering
impossible (optimizer ceiling ~3/7). The injected prompt does NOT name our
skill — it instructs Claude to consult available commands and honour each
command's Skip-for clause, so negative queries (React/BLoC/GetX/etc.) stay
clean while positive queries trigger.
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


def parse_skill_md(skill_path: Path) -> tuple[str, str, str]:
    """Minimal YAML frontmatter parser for SKILL.md.

    Returns (name, description, body). Avoids the external PyYAML dependency
    and the ``scripts.utils`` import path used by the upstream script.
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
        # Other top-level keys: ignore
    if desc_block:
        description = " ".join(l for l in desc_lines if l).strip()
    return name, description, body


def find_project_root() -> Path:
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / ".claude").is_dir():
            return parent
    return current


def run_single_query(
    query: str,
    skill_name: str,
    skill_description: str,
    timeout: int,
    project_root: str,
    model: str | None = None,
    append_system_prompt: str | None = None,
) -> bool:
    unique_id = uuid.uuid4().hex[:8]
    clean_name = f"{skill_name}-skill-{unique_id}"
    project_commands_dir = Path(project_root) / ".claude" / "commands"
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
            "-p", query,
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
            stderr=subprocess.DEVNULL,
            cwd=project_root,
            env=env,
        )

        triggered = False
        start_time = time.time()
        buffer = ""
        pending_tool_name: str | None = None
        accumulated_json = ""

        try:
            while True:
                if time.time() - start_time > timeout:
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

                    if event.get("type") == "stream_event":
                        se = event.get("event", {})
                        se_type = se.get("type", "")

                        if se_type == "content_block_start":
                            cb = se.get("content_block", {})
                            if cb.get("type") == "tool_use":
                                tool_name = cb.get("name", "")
                                if tool_name in ("Skill", "Read"):
                                    pending_tool_name = tool_name
                                    accumulated_json = ""
                                else:
                                    return False

                        elif se_type == "content_block_delta" and pending_tool_name:
                            delta = se.get("delta", {})
                            if delta.get("type") == "input_json_delta":
                                accumulated_json += delta.get("partial_json", "")
                                if clean_name in accumulated_json:
                                    return True

                        elif se_type in ("content_block_stop", "message_stop"):
                            if pending_tool_name:
                                return clean_name in accumulated_json
                            if se_type == "message_stop":
                                return False

                    elif event.get("type") == "assistant":
                        message = event.get("message", {})
                        for content_item in message.get("content", []):
                            if content_item.get("type") != "tool_use":
                                continue
                            tool_name = content_item.get("name", "")
                            tool_input = content_item.get("input", {})
                            if tool_name == "Skill" and clean_name in tool_input.get("skill", ""):
                                triggered = True
                            elif tool_name == "Read" and clean_name in tool_input.get("file_path", ""):
                                triggered = True
                            return triggered

                    elif event.get("type") == "result":
                        return triggered
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

        return triggered
    finally:
        if command_file.exists():
            command_file.unlink()


def run_eval(
    eval_set: list[dict],
    skill_name: str,
    description: str,
    num_workers: int,
    timeout: int,
    project_root: Path,
    runs_per_query: int = 1,
    trigger_threshold: float = 0.5,
    model: str | None = None,
    append_system_prompt: str | None = None,
) -> dict:
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        future_to_info = {}
        for item in eval_set:
            for run_idx in range(runs_per_query):
                future = executor.submit(
                    run_single_query,
                    item["query"],
                    skill_name,
                    description,
                    timeout,
                    str(project_root),
                    model,
                    append_system_prompt,
                )
                future_to_info[future] = (item, run_idx)

        query_triggers: dict[str, list[bool]] = {}
        query_items: dict[str, dict] = {}
        for future in as_completed(future_to_info):
            item, _ = future_to_info[future]
            query = item["query"]
            query_items[query] = item
            if query not in query_triggers:
                query_triggers[query] = []
            try:
                query_triggers[query].append(future.result())
            except Exception as e:
                print(f"Warning: query failed: {e}", file=sys.stderr)
                query_triggers[query].append(False)

    results: list[dict] = []
    for query, triggers in query_triggers.items():
        item = query_items[query]
        trigger_rate = sum(triggers) / len(triggers)
        should_trigger = item["should_trigger"]
        if should_trigger:
            did_pass = trigger_rate >= trigger_threshold
        else:
            did_pass = trigger_rate < trigger_threshold
        results.append({
            "query": query,
            "should_trigger": should_trigger,
            "trigger_rate": trigger_rate,
            "triggers": sum(triggers),
            "runs": len(triggers),
            "pass": did_pass,
        })

    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    return {
        "skill_name": skill_name,
        "description": description,
        "append_system_prompt": append_system_prompt,
        "results": results,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Trigger eval with system-prompt injection")
    parser.add_argument("--eval-set", required=True)
    parser.add_argument("--skill-path", required=True)
    parser.add_argument("--description", default=None)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--runs-per-query", type=int, default=1)
    parser.add_argument("--trigger-threshold", type=float, default=0.5)
    parser.add_argument("--model", default=None)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--append-system-prompt",
        default=DEFAULT_APPEND_SYSTEM,
        help="System prompt appended to claude -p. Empty string disables.",
    )
    parser.add_argument("--no-append-system-prompt", action="store_true",
                        help="Disable system-prompt injection (parity with upstream run_eval.py)")
    args = parser.parse_args()

    eval_set = json.loads(Path(args.eval_set).read_text())
    skill_path = Path(args.skill_path)

    if not (skill_path / "SKILL.md").exists():
        print(f"Error: No SKILL.md found at {skill_path}", file=sys.stderr)
        sys.exit(1)

    name, original_description, _ = parse_skill_md(skill_path)
    description = args.description or original_description
    project_root = find_project_root()
    append_sys = None if args.no_append_system_prompt else (args.append_system_prompt or None)

    if args.verbose:
        print(f"Skill: {name}", file=sys.stderr)
        print(f"Description ({len(description)} chars): {description[:140]}…", file=sys.stderr)
        print(f"Append-system-prompt: {'(none)' if not append_sys else append_sys[:140] + '…'}", file=sys.stderr)

    output = run_eval(
        eval_set=eval_set,
        skill_name=name,
        description=description,
        num_workers=args.num_workers,
        timeout=args.timeout,
        project_root=project_root,
        runs_per_query=args.runs_per_query,
        trigger_threshold=args.trigger_threshold,
        model=args.model,
        append_system_prompt=append_sys,
    )

    if args.verbose:
        summary = output["summary"]
        print(f"Results: {summary['passed']}/{summary['total']} passed", file=sys.stderr)
        for r in output["results"]:
            status = "PASS" if r["pass"] else "FAIL"
            rate_str = f"{r['triggers']}/{r['runs']}"
            print(f"  [{status}] rate={rate_str} expected={r['should_trigger']}: {r['query'][:70]}", file=sys.stderr)

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
