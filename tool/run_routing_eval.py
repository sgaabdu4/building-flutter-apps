#!/usr/bin/env python3
"""Routing eval for the building-flutter-apps skill.

Runs each `routing-eval.json` case through headless `claude -p` with the skill
installed as a temporary project command, the same mechanism as
run_trigger_eval.py. Unlike the trigger eval, the command body carries the full
SKILL.md body behind a `Base directory for this skill:` line, so the Trigger
Map is visible once the Skill tool fires and relative `references/...` links
resolve the way they do for an installed skill.

The whole stream is consumed. Refs are collected from:
  - read: `Read` tool calls (and `Bash` commands) that touch `references/...`
  - cited: `references/...` paths or known `.md` ref basenames in the answer

Each case is scored on read + cited refs against `should_trigger`,
`expected_refs`, `forbidden_refs` and `max_refs`. Ref normalization and scoring
follow the retired Codex runner's routing mode. Helpers are inlined; do NOT
import the sibling runners.
"""

from __future__ import annotations

import argparse
import codecs
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
from typing import Any, Iterable


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
    "any tool call. This protocol is mandatory. When a skill routes you to "
    "reference files, name the exact reference paths you relied on."
)

# The eval runs inside this repo; keep the model from editing the working tree.
DISALLOWED_TOOLS = "Edit,Write,NotebookEdit"

FILE_PATH_RE = re.compile(r"[\w./-]+\.[A-Za-z]\w*")
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


# ── skill helpers ─────────────────────────────────────────────────────────────

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


def reference_aliases(skill_body: str) -> dict[str, str]:
    """Map every spelling of a SKILL.md reference link to its canonical path.

    Canonical = `references/<sub>/<name>.<ext>`. Markdown refs also get the
    bare basename and the path without the `references/` prefix; other files
    (e.g. `analysis_options.yaml`) do not, since a bare mention usually means
    the project's own file.
    """
    aliases: dict[str, str] = {}
    for target in LINK_RE.findall(skill_body):
        ref = target.split("#", 1)[0].strip().removeprefix("./")
        if not ref.startswith("references/"):
            continue
        aliases[ref] = ref
        if ref.endswith(".md"):
            aliases[ref.removeprefix("references/")] = ref
            aliases[Path(ref).name] = ref
    return aliases


def normalized_refs(value: Any, aliases: dict[str, str] | None = None) -> set[str]:
    if not isinstance(value, (list, set, tuple)):
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


# ── ref detection ─────────────────────────────────────────────────────────────

def ref_from_path(raw: str, skill_path: Path, workspace_root: Path, skill_name: str) -> str | None:
    """Return `references/...` for a path that points into the skill, else None."""
    raw = raw.strip()
    if not raw:
        return None
    if raw.startswith(("references/", "./references/")):
        rel = raw.removeprefix("./")
    else:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = workspace_root / path
        try:
            rel = path.resolve().relative_to(skill_path.resolve()).as_posix()
        except ValueError:
            # Another install of the same skill (plugin cache, ~/.claude/skills).
            text = path.as_posix()
            marker = f"/{skill_name}/references/"
            idx = text.find(marker)
            if idx < 0:
                return None
            rel = text[idx + len(skill_name) + 2:]
    if rel.startswith("references/") and Path(rel).suffix:
        return rel
    return None


def refs_in_text(text: str, aliases: dict[str, str], *, allow_aliases: bool = True) -> set[str]:
    """Find `references/...` paths (and, optionally, known `.md` aliases) in text."""
    found: list[str] = []
    for match in FILE_PATH_RE.findall(text):
        idx = match.find("references/")
        if idx >= 0 and (idx == 0 or match[idx - 1] == "/"):
            found.append(match[idx:])
        elif allow_aliases and match.removeprefix("./") in aliases:
            found.append(match)
    return normalized_refs(found, aliases)


def scan_events(
    events: Iterable[dict],
    *,
    clean_name: str,
    skill_name: str,
    skill_path: Path,
    workspace_root: Path,
    aliases: dict[str, str],
) -> dict[str, Any]:
    """Derive trigger, read refs and cited refs from stream-json events."""
    skill_md = (skill_path / "SKILL.md").resolve()
    triggered = False
    completed = False
    invocations: list[str] = []
    read: set[str] = set()
    texts: list[str] = []

    for event in events:
        etype = event.get("type")
        if etype == "assistant":
            for block in event.get("message", {}).get("content", []) or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    texts.append(str(block.get("text", "")))
                    continue
                if block.get("type") != "tool_use":
                    continue
                name = block.get("name", "")
                tool_input = block.get("input") or {}
                if name == "Skill":
                    skill = str(tool_input.get("skill", ""))
                    invocations.append(skill)
                    if skill_name in skill:
                        triggered = True
                elif name == "Read":
                    file_path = str(tool_input.get("file_path", ""))
                    if clean_name in file_path:
                        triggered = True
                    elif file_path and (workspace_root / Path(file_path).expanduser()).resolve() == skill_md:
                        triggered = True
                    ref = ref_from_path(file_path, skill_path, workspace_root, skill_name)
                    if ref:
                        read.add(ref)
                elif name == "Bash":
                    read |= refs_in_text(str(tool_input.get("command", "")), aliases, allow_aliases=False)
        elif etype == "result":
            completed = True
            result_text = event.get("result")
            if isinstance(result_text, str):
                texts.append(result_text)

    return {
        "triggered": triggered,
        "completed": completed,
        "skill_invocations": invocations,
        "read_refs": normalized_refs(read, aliases),
        "cited_refs": refs_in_text("\n".join(texts), aliases),
    }


def score_case(item: dict, scan: dict[str, Any], duration_seconds: float) -> dict[str, Any]:
    read_refs: set[str] = scan["read_refs"]
    cited_refs: set[str] = scan["cited_refs"]
    refs = read_refs | cited_refs
    triggered = bool(scan["triggered"])

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
        and scan["completed"]
    )

    return {
        "id": item.get("id"),
        "query": item["query"],
        "should_trigger": should_trigger,
        "triggered": triggered,
        "pass": passed,
        "refs": sorted(refs),
        "read_refs": sorted(read_refs),
        "cited_refs": sorted(cited_refs),
        "expected_refs": sorted(expected_refs),
        "missing_refs": missing_refs,
        "forbidden_selected": forbidden_selected,
        "max_refs": max_refs,
        "too_many_refs": too_many_refs,
        "refs_when_skipped": refs_when_skipped,
        "skill_invocations": scan["skill_invocations"],
        "completed": scan["completed"],
        "duration_seconds": round(duration_seconds, 2),
    }


# ── claude -p ─────────────────────────────────────────────────────────────────

def collect_events(cmd: list[str], cwd: str, timeout: int) -> tuple[list[dict], bool]:
    """Run cmd, parse stream-json lines until the result event, EOF or timeout.

    Returns (events, timed_out).
    """
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=cwd,
        env=env,
    )
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    events: list[dict] = []
    buffer = ""
    timed_out = False
    saw_result = False

    def parse_lines(lines: list[str]) -> None:
        nonlocal saw_result
        for line in lines:
            if saw_result:
                return
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
                if event.get("type") == "result":
                    saw_result = True

    start_time = time.time()
    try:
        while not saw_result:
            if time.time() - start_time > timeout:
                timed_out = True
                break
            ready, _, _ = select.select([process.stdout], [], [], 1.0)
            if not ready:
                continue
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                break
            buffer += decoder.decode(chunk)
            *lines, buffer = buffer.split("\n")
            parse_lines(lines)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()

    if not saw_result:
        parse_lines((buffer + decoder.decode(b"", final=True)).split("\n"))
    return events, timed_out


def run_single_case(
    item: dict,
    skill_name: str,
    skill_description: str,
    skill_body: str,
    skill_path: str,
    timeout: int,
    workspace_root: str,
    aliases: dict[str, str],
    model: str | None = None,
    append_system_prompt: str | None = None,
) -> dict[str, Any]:
    unique_id = uuid.uuid4().hex[:8]
    clean_name = f"{skill_name}-skill-{unique_id}"
    project_commands_dir = Path(workspace_root) / ".claude" / "commands"
    project_commands_dir.mkdir(parents=True, exist_ok=True)
    command_file = project_commands_dir / f"{clean_name}.md"

    indented_desc = "\n  ".join(skill_description.split("\n"))
    # In a command file "!`...`" runs as shell; SKILL.md has inline code like
    # `value!`. A zero-width space keeps the text but breaks that syntax.
    command_body = skill_body.lstrip().replace("!`", "!\u200b`")
    command_content = (
        f"---\n"
        f"description: |\n"
        f"  {indented_desc}\n"
        f"---\n\n"
        f"Base directory for this skill: {Path(skill_path).resolve()}\n\n"
        f"{command_body}"
    )
    command_file.write_text(command_content)

    try:
        cmd = [
            "claude",
            "-p", item["query"],
            "--output-format", "stream-json",
            "--verbose",
            "--disallowedTools", DISALLOWED_TOOLS,
        ]
        if model:
            cmd.extend(["--model", model])
        if append_system_prompt:
            cmd.extend(["--append-system-prompt", append_system_prompt])

        start_time = time.time()
        events, timed_out = collect_events(cmd, workspace_root, timeout)
        duration = time.time() - start_time
        if timed_out:
            print(f"[routing] timeout after {timeout}s for id={item.get('id')}", file=sys.stderr)

        scan = scan_events(
            events,
            clean_name=clean_name,
            skill_name=skill_name,
            skill_path=Path(skill_path),
            workspace_root=Path(workspace_root),
            aliases=aliases,
        )
        return score_case(item, scan, duration)
    finally:
        if command_file.exists():
            command_file.unlink()


# ── main eval loop ────────────────────────────────────────────────────────────

def failed_case(item: dict, error: Exception) -> dict[str, Any]:
    scan = {
        "triggered": False,
        "completed": False,
        "skill_invocations": [],
        "read_refs": set(),
        "cited_refs": set(),
    }
    result = score_case(item, scan, 0.0)
    result["error"] = str(error)
    return result


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r["pass"])
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "false_negatives": sum(1 for r in results if r["should_trigger"] and not r["triggered"]),
        "false_positives": sum(1 for r in results if not r["should_trigger"] and r["triggered"]),
        "routing_misses": sum(1 for r in results if r["should_trigger"] and r["missing_refs"]),
        "over_reads": sum(1 for r in results if r["forbidden_selected"] or r["too_many_refs"]),
        "incomplete": sum(1 for r in results if not r["completed"]),
    }


def run_routing_eval(
    eval_set: list[dict],
    skill_name: str,
    description: str,
    skill_body: str,
    skill_path: Path,
    num_workers: int,
    timeout: int,
    workspace_root: Path,
    model: str | None = None,
    append_system_prompt: str | None = None,
) -> dict:
    aliases = reference_aliases(skill_body)
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        future_to_item = {
            executor.submit(
                run_single_case,
                item,
                skill_name,
                description,
                skill_body,
                str(skill_path),
                timeout,
                str(workspace_root),
                aliases,
                model,
                append_system_prompt,
            ): item
            for item in eval_set
        }
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            try:
                results.append(future.result())
            except Exception as e:
                print(f"Warning: case id={item.get('id')} failed: {e}", file=sys.stderr)
                results.append(failed_case(item, e))

    results.sort(key=lambda r: (r["id"] is None, r["id"]))
    return {
        "skill_name": skill_name,
        "description": description,
        "append_system_prompt": append_system_prompt,
        "results": results,
        "summary": summarize(results),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Routing eval — checks which skill references claude -p reads or cites"
    )
    parser.add_argument("--eval-set", required=True, help="Path to routing-eval.json")
    parser.add_argument("--skill-path", required=True, help="Path to skill directory containing SKILL.md")
    parser.add_argument("--workspace-root", default=None,
                        help="cwd for claude -p (must have .claude/); default: nearest parent with .claude/")
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=240, help="Per-case timeout in seconds")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only run the first N cases from the eval set")
    parser.add_argument("--model", default=None)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--append-system-prompt",
        default=DEFAULT_APPEND_SYSTEM,
        help="System prompt appended to claude -p. Empty string disables.",
    )
    parser.add_argument("--no-append-system-prompt", action="store_true",
                        help="Disable system-prompt injection")
    args = parser.parse_args()

    skill_path = Path(args.skill_path)
    if not (skill_path / "SKILL.md").exists():
        print(f"Error: No SKILL.md found at {skill_path}", file=sys.stderr)
        sys.exit(1)

    name, description, body = parse_skill_md(skill_path)
    raw = json.loads(Path(args.eval_set).read_text())
    eval_set: list[dict] = raw["evals"] if isinstance(raw, dict) and "evals" in raw else raw
    if args.limit:
        eval_set = eval_set[: args.limit]

    workspace_root = Path(args.workspace_root) if args.workspace_root else find_project_root()
    append_sys = None if args.no_append_system_prompt else (args.append_system_prompt or None)

    leftovers = sorted(p.name for p in (workspace_root / ".claude" / "commands").glob(f"{name}-skill-*.md"))
    if leftovers:
        print(f"Warning: leftover command stubs compete with the eval install: {', '.join(leftovers)}",
              file=sys.stderr)

    if args.verbose:
        print(f"Skill: {name}", file=sys.stderr)
        print(f"Routing cases: {len(eval_set)}", file=sys.stderr)
        print(f"Workspace root: {workspace_root}", file=sys.stderr)
        print(f"Append-system-prompt: {'(none)' if not append_sys else append_sys[:140] + '…'}", file=sys.stderr)

    output = run_routing_eval(
        eval_set=eval_set,
        skill_name=name,
        description=description,
        skill_body=body,
        skill_path=skill_path,
        num_workers=args.num_workers,
        timeout=args.timeout,
        workspace_root=workspace_root,
        model=args.model,
        append_system_prompt=append_sys,
    )

    if args.verbose:
        summary = output["summary"]
        print(f"Results: {summary['passed']}/{summary['total']} passed", file=sys.stderr)
        for r in output["results"]:
            status = "PASS" if r["pass"] else "FAIL"
            detail = f"refs={len(r['refs'])}/{r['max_refs']}"
            if r["missing_refs"]:
                detail += f" missing={','.join(r['missing_refs'])}"
            if r["forbidden_selected"]:
                detail += f" forbidden={','.join(r['forbidden_selected'])}"
            print(
                f"  [{status}] id={r['id']} triggered={r['triggered']} expected={r['should_trigger']} "
                f"{detail}: {r['query'][:70]}",
                file=sys.stderr,
            )

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
