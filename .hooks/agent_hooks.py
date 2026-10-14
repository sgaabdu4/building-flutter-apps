"""Native context/completion responses; Git records scope, never gate results."""

import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

from gate_config import JsonObject, JsonValue, nonproduction_source, repository_files

GATE_OUTPUT_LIMIT = 8000
# The HE Build handoff line, not a quoted or negated mention of it.
SHIP_CLAIM = re.compile(r"^[*_ ]*Ready for ship[*_]*\s*[—–-]", re.MULTILINE)


def replaces_agents(path: Path) -> bool:
    return path.is_symlink() or path.exists()


def instruction_suffix(content: str) -> str:
    end = "<!-- hard-eng:end -->\n"
    if (
        content.startswith("<!-- hard-eng:start -->\n")
        and content.endswith(end)
        and content.count("<!-- hard-eng:end -->") == 1
    ):
        return ""
    return content.split(end + "\n", 1)[-1]


def configure_instructions(
    root: Path, source: Path, previous: Path | None, changes: dict[str, str]
) -> list[str]:
    from update import contained

    start, end = "<!-- hard-eng:start -->", "<!-- hard-eng:end -->"
    instructions = {
        "AGENTS.md": (source / "AGENTS.md").read_text().rstrip(),
    }
    listed = subprocess.check_output(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--",
            ":(glob)**/CLAUDE.md",
            ":(glob)**/CLAUDE.local.md",
            ":(glob,exclude)**/node_modules/**",
            ":(glob,exclude)**/vendor/**",
            ":(glob,exclude)**/.venv/**",
            ":(glob,exclude)**/.dart_tool/**",
            ":(glob,exclude)**/build/**",
            ":(glob,exclude).agents/**",
            ":(glob,exclude).hard-eng/**",
        ],
        cwd=root,
        text=True,
    ).split("\0")
    retired: list[str] = []
    replacing: list[str] = []
    for name in sorted(
        name
        for name in {*listed, "CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md"}
        if Path(name).name in {"CLAUDE.md", "CLAUDE.local.md"}
        and replaces_agents(root / name)
    ):
        path = root / name
        linked = path.is_symlink() and path.resolve() in {
            (root / "AGENTS.md").resolve(),
            path.with_name("AGENTS.md").resolve(),
        }
        imported = (
            not path.is_symlink()
            and path.is_file()
            and path.read_text().strip()
            in {
                CLAUDE_IMPORT.strip(),
                "@AGENTS.md",
                (CLAUDE_IMPORT + "@AGENTS.md").strip(),
                "@.agents/hard-eng/current/AGENTS.md",
            }
        )
        if linked or imported:
            if not contained(root, path):
                raise ValueError(
                    f"{name} is reached through a linked directory; preserve and review its shared instructions before retiring it"
                )
            retired.append(name)
        else:
            replacing.append(name)
    if replacing:
        raise ValueError(
            "Repository CLAUDE instructions prevent native AGENTS.md loading: "
            + ", ".join(replacing)
            + "; review their rules and imports, move shared guidance to the matching AGENTS.md, "
            "keep private/local guidance out of tracked files, then remove these CLAUDE files and rerun setup"
        )
    ancestors = [
        parent / name
        for parent in root.parents
        for name in ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md")
        if replaces_agents(parent / name)
        and not (parent == Path.home() and name == ".claude/CLAUDE.md")
    ]
    if ancestors:
        raise ValueError(
            "Ancestor CLAUDE instructions prevent native AGENTS.md loading: "
            + ", ".join(map(str, ancestors))
            + "; review their rules and imports at their owning directory before retiring them; "
            "setup cannot change instruction files outside the target repository"
        )
    if (root / "AGENTS.override.md").exists():
        instructions["AGENTS.override.md"] = (
            "Read and follow [shared instructions](AGENTS.md) before repository work."
        )
    for name, content in instructions.items():
        target = root / name
        existing = target.read_bytes().decode("utf-8") if target.exists() else ""
        if start in existing or end in existing:
            old = (
                ((previous or source) / name).read_text().rstrip()
                if name == "AGENTS.md"
                else content
            )
            prefix = f"{start}\n{old}\n{end}\n\n"
            existing = prefix if existing == prefix.removesuffix("\n") else existing
            if (
                existing.count(start) != 1
                or existing.count(end) != 1
                or not existing.startswith(prefix)
            ):
                raise ValueError(
                    f"Local Hard Eng instructions differ or have conflicting markers in {name}; preserve them and resolve before replacing them"
                )
            existing = existing[len(prefix) :]
        changes[name] = f"{start}\n{content}\n{end}\n" + (
            f"\n{existing}" if existing else ""
        )
    return retired


def project_pre_push(root: Path, hook: Path) -> Path:
    """Validate repository hook ownership and preserve Husky's forwarding shim.

    A linked worktree may run the hooks of the repository's common checkout.
    """
    owner = root
    if not hook.parent.resolve().is_relative_to(root.resolve()):
        common = Path(
            subprocess.check_output(
                ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                cwd=root,
                text=True,
            ).strip()
        ).resolve()
        directory = hook.parent.resolve()
        if directory != common / "hooks":
            if common.name != ".git" or not directory.is_relative_to(common.parent):
                origin = (
                    subprocess.run(
                        ["git", "config", "--show-origin", "core.hooksPath"],
                        cwd=root,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    .stdout.strip()
                    .replace("\t", " as ")
                )
                raise ValueError(
                    f"Git hooks point outside this repository: {directory} is not under {root}"
                    + (f" (core.hooksPath set in {origin})" if origin else "")
                )
            owner, hook = common.parent, directory / hook.name
    shim = '#!/usr/bin/env sh\n. "$(dirname "$0")/h"'
    if (
        hook == owner / ".husky/_/pre-push"
        and not hook.is_symlink()
        and hook.is_file()
        and hook.read_text().rstrip("\n") == shim
        and (hook.parent / "h").is_file()
    ):
        return root / ".husky/pre-push"
    return hook


def hook_events(agent: str) -> dict[str, str]:
    if agent not in HOOK_FILES:
        raise ValueError("Unsupported native agent; use Claude or Codex")
    events = {
        "session": "SessionStart",
        "failure": "PostToolUseFailure",
        "stop": "Stop",
    }
    if agent == "codex":
        del events["failure"]
    return events


def owned_hook_entry(
    agent: str,
    event: str,
    command: str,
    timeout: int,
    status_message: str | None = None,
) -> JsonObject:
    """Build one exact managed hook entry for setup and legacy migration."""
    call = f"{command} {event} {agent}"
    handler: JsonObject = {"type": "command", "command": call, "timeout": timeout}
    if status_message is not None:
        handler["statusMessage"] = status_message
    return {"hooks": [handler]}


HOOK_TIMEOUTS = {"session": 60, "stop": 3600}
CODEX_HOOK_STATUS = {
    "session": "Hard Eng: updating project setup",
    "stop": "Hard Eng: verifying changes",
}


def _remove_owned_entry(hooks: JsonObject, native: str, owned: JsonObject) -> None:
    entries = hooks.get(native)
    if not isinstance(entries, list) or owned not in entries:
        return
    while owned in entries:
        entries.remove(owned)
    if not entries:
        del hooks[native]


def remove_routine_hooks(current: JsonObject, agent: str, command: str) -> None:
    """Remove only registrations previously installed by us, including old-generation scripts."""
    hooks = current.get("hooks", {})
    if not isinstance(hooks, dict):
        raise TypeError("Conflicting hooks: expected an object")
    for event, native in (("prompt", "UserPromptSubmit"), ("tool", "PostToolUse")):
        call = f"{command} {event} {agent}"
        owned: JsonObject = {
            "hooks": [{"type": "command", "command": call, "timeout": 10}]
        }
        _remove_owned_entry(hooks, native, owned)
    if agent == "codex":
        for event in CODEX_HOOK_STATUS:
            _remove_owned_entry(
                hooks,
                hook_events(agent)[event],
                owned_hook_entry(agent, event, command, 3600),
            )
    status = CODEX_HOOK_STATUS["session"] if agent == "codex" else None
    _remove_owned_entry(
        hooks,
        hook_events(agent)["session"],
        owned_hook_entry(agent, "session", command, 3600, status_message=status),
    )
    remove_old_generation(hooks)
    if current.get("outputStyle") == "Plain English":
        del current["outputStyle"]


HOOK_FILES = {
    "claude": ".claude/settings.json",
    "codex": ".codex/hooks.json",
}


def retired_copilot_entry(native: str, entry: JsonValue, command: str) -> bool:
    events = {
        "sessionStart": ("session", 3600),
        "postToolUseFailure": ("failure", 10),
        "agentStop": ("stop", 3600),
        "postToolUse": ("tool", 10),
    }
    event, timeout = events.get(native, ("", 0))
    if entry == {
        "type": "command",
        "bash": f"{command} {event} copilot",
        "timeoutSec": timeout,
    }:
        return True
    return (
        isinstance(entry, dict)
        and entry.keys() <= {"type", "bash", "timeoutSec"}
        and entry.get("type") == "command"
        and isinstance(call := entry.get("bash"), str)
        and re.fullmatch(
            r'(?:bash|sh) (?:"\$\((?:env -u GIT_DIR )?git rev-parse --show-toplevel\)/)?'
            r'\.hard-eng/(?:bootstrap|hook)\.sh"? copilot(?: [a-z]+)?',
            call,
        )
        is not None
    )


def retire_copilot_hooks(root: Path, command: str) -> list[str]:
    from update import contained

    retired: list[str] = []
    for target in root.glob(".github/hooks/*.json"):
        name = str(target.relative_to(root))
        current: JsonObject = json.loads(target.read_text())
        wiring = current.get("hooks")
        if not isinstance(wiring, dict):
            raise TypeError(f"Conflicting hooks in {name}; expected an object")
        if current.keys() - {"version", "hooks"} or any(
            not isinstance(entries, list)
            or any(
                not retired_copilot_entry(native, entry, command) for entry in entries
            )
            for native, entries in wiring.items()
        ):
            raise ValueError(
                f"Harness migration required: {name} contains project hooks; preserve their checks in Claude or Codex and remove the retired registration before setup."
            )
        if target.is_symlink() or not contained(root, target):
            raise ValueError(f"Preserve linked retired harness config: {name}")
        retired.append(name)
    return retired


CLAUDE_IMPORT = "<!-- hard-eng:start -->\n@AGENTS.md\n<!-- hard-eng:end -->\n\n"
OLD_GENERATION_SCRIPT = re.compile(r"\.hard-eng\b|\.agents/hard-eng/")


def _old_generation(handler: JsonValue) -> bool:
    if not isinstance(handler, dict):
        return False
    calls = [
        handler[key] for key in ("command", "bash", "powershell") if key in handler
    ]
    obsolete = any(
        isinstance(call, str) and OLD_GENERATION_SCRIPT.search(call) for call in calls
    )
    legacy = (
        r'(?:bash|sh) (?:"\$\((?:env -u GIT_DIR )?git rev-parse --show-toplevel\)/|[^ \n;&|"\']*/)?'
        r'(?:\.hard-eng/(?:bootstrap|hook)\.sh|\.agents/hard-eng/current/scripts/hooks/agent-hook\.sh)"?(?: [a-z-]+)*'
    )
    if obsolete and any(
        not isinstance(call, str) or not re.fullmatch(legacy, call) for call in calls
    ):
        raise ValueError(
            "Legacy Hard Eng hook contains custom commands; preserve the separate project checks and remove the retired command before setup."
        )
    return obsolete


def remove_old_generation(hooks: JsonObject) -> None:
    for native, entries in list(hooks.items()):
        if isinstance(entries, list):
            kept = _without_old_generation(entries)
            if not kept and entries:
                del hooks[native]
            elif kept != entries:
                hooks[native] = kept


def _without_old_generation(entries: list[JsonValue]) -> list[JsonValue]:
    kept: list[JsonValue] = []
    for entry in entries:
        inner = entry.get("hooks") if isinstance(entry, dict) else None
        if isinstance(entry, dict) and isinstance(inner, list):
            handlers = [item for item in inner if not _old_generation(item)]
            if handlers:
                kept.append(
                    entry if handlers == inner else {**entry, "hooks": handlers}
                )
        elif not _old_generation(entry):
            kept.append(entry)
    return kept


def learning_context(event: str) -> str:
    return f"HE Learn ({event}): repeat failure or lasting decision → .agents/skills/he-learn/SKILL.md; else continue."


def context_output(native: str, message: str) -> JsonObject:
    return {
        "hookSpecificOutput": {
            "hookEventName": native,
            "additionalContext": message,
        }
    }


def session_state(root: Path, payload: JsonObject) -> Path | None:
    identifier = payload.get("session_id", payload.get("sessionId"))
    if not isinstance(identifier, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{1,200}", identifier
    ):
        return None
    return root / ".hard-eng/sessions" / (identifier + ".json")


def dirty_files(root: Path, base: str) -> dict[str, str]:
    """Content hash of each file differing from base; absent files hash to ''."""
    names = subprocess.check_output(
        ["git", "diff", "--name-only", "-z", base, "--"], cwd=root, text=True
    ).split("\0")
    names += subprocess.check_output(
        ["git", "ls-files", "-z", "--others", "--exclude-standard"], cwd=root, text=True
    ).split("\0")
    digests = dict.fromkeys(set(names) - {""}, "")
    for name in digests:
        if (root / name).is_file():
            with (root / name).open("rb") as file:
                digests[name] = hashlib.file_digest(file, "sha256").hexdigest()
    return digests


def gate_status(root: Path) -> str:
    """Say whether `check` can start, so an install never looks active while broken."""
    from gate_config import load_groups
    from update import SOURCE_FILE, install_paths

    try:
        load_groups(root)
        status = "Gates: ok."
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        subprocess.SubprocessError,
    ) as error:
        status = "Gates: not runnable — " + " ".join(str(error).split())
    try:
        pending: list[str] = [
            line[3:]
            for line in subprocess.check_output(
                [
                    "git",
                    "status",
                    "--porcelain",
                    "--untracked-files=all",
                    "--",
                    ".hooks",
                    ".agents/skills",
                    "hard-eng.gates.json",
                    ".husky/pre-push",
                ],
                cwd=root,
                text=True,
            ).splitlines()
        ]
    except (OSError, subprocess.SubprocessError):
        pending = []
    if pending and (root / SOURCE_FILE).exists():
        status += (
            " Uncommitted Hard Eng paths block updates + new worktrees; commit: "
            + install_paths(pending)
        )
    return status


def record_session(root: Path, payload: JsonObject) -> bool:
    """Save the session's Git base before a background update can move HEAD."""
    state = session_state(root, payload)
    if state is None:
        return True
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip()
        state.parent.mkdir(parents=True, exist_ok=True)
        if not state.exists():
            dirty = dirty_files(root, revision)
            state.write_text(json.dumps({"base": revision, "dirty": dirty}))
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def session_context(root: Path, payload: JsonObject) -> str:
    from update_runner import failed_update, start_update

    recorded = record_session(root, payload)
    try:
        messages = [start_update(root)]
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        messages = [failed_update(error)]
    from hook_chain import restore_note

    if note := restore_note(root):
        messages.append(note)
    messages.append(gate_status(root))
    messages.append(
        "Open the task's skill first: he-plan, he-build, he-ship or code-review. "
        "Tests fail before your edits → fix only that and stop; the feature waits until that fix merges."
    )
    if not recorded:
        messages.append("Session revision unavailable → full checks.")
    messages.append(
        "MCPs: use when relevant; verify a real call before relying (registration ≠ ready); unavailable → warn + continue."
    )
    messages.append(learning_context("start/resume"))
    return "\n".join(messages)


def completion_notice(agent: str | None, output: str) -> JsonObject:
    """Surface only the runner's explicit plan-stage handoff where supported."""
    if agent not in {"claude", "codex"}:
        return {}
    lines = output.splitlines()
    if lines and lines[-1].startswith(
        ("Hard Eng: planning checks passed", "Hard Eng: build checks passed")
    ):
        return {"systemMessage": lines[-1]}
    return {}


def integrated_services(root: Path) -> list[str]:
    patterns = {
        "Sentry": r"(?:from\s+['\"]@sentry/|require\(['\"]@sentry/|import\s+sentry_sdk|from\s+sentry_sdk\b|package:sentry(?:_flutter)?/)",
        "Appwrite": r"(?:from\s+['\"](?:node-)?appwrite['\"]|require\(['\"](?:node-)?appwrite['\"]|from\s+appwrite\b|import\s+appwrite\b|package:(?:dart_)?appwrite/)",
        "Dart": r"\b(?:import|export)\s+['\"](?:dart:|package:)",
    }
    found = set()
    for path in repository_files(root):
        relative = path.relative_to(root)
        if nonproduction_source(relative) or {".agents", ".claude", ".hooks"} & set(
            relative.parts
        ):
            continue
        if path.name == "pubspec.yaml":
            found.add("Dart")
        if path.suffix in {
            ".py",
            ".js",
            ".jsx",
            ".ts",
            ".tsx",
            ".dart",
            ".mjs",
            ".cjs",
        }:
            source = path.read_text(errors="replace")
            found.update(
                name for name, pattern in patterns.items() if re.search(pattern, source)
            )
    return sorted(found)


def passed_notice(
    building: bool, notice: str, agent: str | None, output: str
) -> JsonObject:
    if building:
        return {
            "systemMessage": "Hard Eng: build in progress; checks pass at Ready. "
            "Finish needs Complete + `check --plan-stage Complete`."
        }
    return {"systemMessage": notice} if notice else completion_notice(agent, output)


def failure_summary(log: str) -> str:
    """Failed gate names, then the first failing gate's output from its start."""
    failures = re.findall(
        r"FAIL (\S+?)(?: \(exit \d+;|: [^\n]*; elapsed)(?:[^\n]*? @ (\S+))?",
        log,
    )
    if not failures:
        return log[-GATE_OUTPUT_LIMIT:]
    heading = "Failed gates: " + ", ".join(dict.fromkeys(n for n, _ in failures)) + "\n"
    name, package = failures[0]
    owner = re.escape(f"{package}/" if package else "") or r"(?:\S*/)?"
    start = re.search(rf"OUTPUT {owner}{re.escape(name)}[^\n]*\n", log)
    if start is None:
        return heading + log[-GATE_OUTPUT_LIMIT:]
    body = log[start.end() :]
    tail = f"[^\n]* @ {re.escape(package)}(?!\\S)" if package else ""
    finished = re.escape(name) + r"(?: \(exit|:)" + tail
    end = re.search(rf"(?m)^(?:CHECK|OUTPUT) \S*/\S+|(?:PASS|FAIL) {finished}", body)
    return heading + body[: end.start() if end else None][:GATE_OUTPUT_LIMIT]


def show_decisions(root: Path, names: list[str], state: Path | None) -> str:
    """Accepted ADRs matching these files and not yet shown this session; records them as shown."""
    from plans import matched_decisions

    if state is None or not state.exists():
        return ""
    saved = json.loads(state.read_text())
    shown = saved.get("decisions", [])
    pending = {
        name: text
        for name, text in matched_decisions(root, names).items()
        if name not in shown
    }
    if not pending:
        return ""
    state.write_text(json.dumps({**saved, "decisions": [*shown, *pending]}))
    return (
        "\nAccepted decisions below apply to changed files; confirm each, fix if not.\n\n"
        + "\n\n".join(pending.values())
    )


def run_check(root: Path, base: str, building: bool) -> tuple[int, str]:
    with tempfile.TemporaryFile() as log:
        check = subprocess.Popen(
            [
                sys.executable,
                str(root / ".hooks/hard-eng.py"),
                "check",
                "--quick",
                "--base",
                base,
                *(["--plan-stage", "Ready"] if building else []),
            ],
            cwd=root,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        def stop_check(signum: int, _frame: object) -> None:
            with suppress(ProcessLookupError, PermissionError):
                os.killpg(check.pid, signum)

        # An interrupted Stop hook must not leave the check's tools running.
        previous = signal.signal(signal.SIGTERM, stop_check)
        try:
            returncode = check.wait(timeout=3500)
        except subprocess.TimeoutExpired:
            stop_check(signal.SIGKILL, None)
            check.wait()
            raise
        finally:
            signal.signal(signal.SIGTERM, previous)
        log.seek(0)
        text = log.read().decode("utf-8", errors="replace")
        return returncode, text if returncode == 0 else failure_summary(text)


def last_pass(state: Path | None) -> JsonValue:
    if state is None or not state.exists():
        return None
    saved = json.loads(state.read_text())
    return saved.get("verified") if isinstance(saved, dict) else None


def remember_pass(state: Path | None, verified: JsonObject) -> None:
    """Record what the last passing check saw, so an unchanged turn need not rerun it."""
    if state is not None and state.exists():
        saved = json.loads(state.read_text())
        state.write_text(json.dumps({**saved, "verified": verified}))


def saved_session(state: Path | None) -> tuple[str, JsonObject]:
    if state is None or not state.exists():
        return "HEAD", {}
    saved = json.loads(state.read_text())
    if not isinstance(saved, dict):
        raise TypeError("Invalid session state: expected an object")
    base, before = saved.get("base"), saved.get("dirty", {})
    if not isinstance(base, str) or not base.strip():
        raise ValueError("Invalid session state: expected a nonempty Git base")
    if not isinstance(before, dict):
        raise TypeError("Invalid session state: expected a dirty-file object")
    return base, before


def with_freshness(root: Path, output: JsonObject) -> JsonObject:
    from update_runner import freshness_note

    note = freshness_note(root)
    if not note:
        return output
    shown = output.get("systemMessage")
    return {**output, "systemMessage": f"{shown}\n{note}" if shown else note}


def unchanged_notice(root: Path, notice: str) -> JsonObject:
    message = (
        f"{notice}. Planning-only; no code checks run."
        if notice
        else "No changes since session base; no code checks run."
    )
    return with_freshness(root, {"systemMessage": message})


def paused_turn(payload: JsonObject) -> JsonObject | None:
    if payload.get("stop_hook_active") is True:
        return {
            "systemMessage": "Report blockers honestly; don't claim a pass; no stop-hook loop."
        }
    tasks = payload.get("background_tasks")
    if isinstance(tasks, list) and any(
        isinstance(task, dict)
        and task.get("type") in {"subagent", "workflow", "teammate"}
        for task in tasks
    ):
        return {
            "systemMessage": "Hard Eng: background agents still editing; checks run after they finish. Don't claim done."
        }
    return None


def completion(root: Path, payload: JsonObject, agent: str | None = None) -> JsonObject:
    from plans import build_in_progress, planning_feedback, planning_only

    if (paused := paused_turn(payload)) is not None:
        return paused
    state = session_state(root, payload)
    base, before = saved_session(state)
    try:
        base = subprocess.check_output(
            ["git", "rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}"],
            cwd=root,
            text=True,
        ).strip()
        current = dirty_files(root, base)
        changed = "".join(
            f"{name}\n"
            for name, digest in current.items()
            if before.get(name) != digest
        )
        notice, unfinished = planning_feedback(root, set(changed.splitlines()))
        if unfinished:
            return {
                "decision": "block",
                "systemMessage": notice,
                "reason": notice
                + ". Only authorized planning/verification; ask real blockers. No authority to implement, expand scope or edit read-only work → report + stop.",
            }
        if not changed.strip() and state is not None and state.exists():
            return unchanged_notice(root, notice)
        if notice and planning_only(root, set(changed.splitlines())):
            return with_freshness(
                root,
                {"systemMessage": notice + ". Planning-only; no code checks run."},
            )
        claim = str(
            payload.get("last_assistant_message", payload.get("lastAssistantMessage"))
        )
        # HE Build keeps a plan Ready until its final gate; only its handoff needs Complete.
        building = not SHIP_CLAIM.search(claim) and build_in_progress(
            root, set(changed.splitlines())
        )
        verified: JsonObject = {
            "base": base,
            "files": dict(current),
            "building": building,
        }
        if last_pass(state) == verified:
            return with_freshness(
                root,
                {
                    "systemMessage": "Hard Eng: unchanged since last passing check; not rerun."
                },
            )
        returncode, output = run_check(root, base, building)
        decisions = show_decisions(root, changed.splitlines(), state)
        if returncode == 0:
            remember_pass(state, verified)
            if decisions:
                return {"decision": "block", "reason": decisions.strip()}
            return with_freshness(root, passed_notice(building, notice, agent, output))
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        return {
            "decision": "block",
            "reason": f"Verification could not run: {error}. Report it; repair only within the authorized task. No new authority.",
        }
    return {
        "decision": "block",
        "reason": output.rstrip("\n")
        + decisions
        + "\n\nVerification failed; don't claim done. Fix every finding (unrelated too) as its own commit, then reverify. Edits/commits not allowed → report + stop. "
        + learning_context("failed verification"),
    }


def handle_event(root: Path, event: str, agent: str) -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise TypeError("Hook input must be a JSON object")
        native = hook_events(agent).get(event)
        if native is None:
            raise ValueError("Unsupported native hook event")
        if event == "stop":
            output = completion(root, payload, agent)
        else:
            message = (
                session_context(root, payload)
                if event == "session"
                else learning_context(event)
            )
            # Codex loads AGENTS.override.md natively; Claude loads only AGENTS.md.
            if (
                event == "session"
                and agent == "claude"
                and (root / "AGENTS.override.md").is_file()
            ):
                message += "\nProject rules also in AGENTS.override.md → read it now + follow it."
            output = context_output(native, message)
            if event == "session":
                output["systemMessage"] = "Hard Eng startup: " + " ".join(
                    message.splitlines()[:2]
                )
    except (OSError, ValueError, TypeError) as error:
        message = (
            f"Hard Eng hook failed: {error}. Continue; don't claim verification passed."
        )
        output = (
            {"systemMessage": message}
            if event != "stop"
            else {"decision": "block", "reason": message}
        )
    print(json.dumps(output))
    return 0
