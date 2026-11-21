"""PreToolUse hook (Claude Code and Antigravity): refuse a merge that skips ship, and deny foreground polling (HE-NO-FOREGROUND-POLL)."""

import json
import sys
from collections.abc import Callable

REASON = (
    "HE-NO-FOREGROUND-POLL: this command waits in the foreground with sleep. "
    "Start the long job once with run_in_background: true; "
    "the harness tells you when it exits. Read its output file after that notice."
)
AGY_REASON = (
    "HE-NO-FOREGROUND-POLL: this command waits in the foreground with sleep. "
    "Do not poll with sleep; start the long job directly with a short WaitMsBeforeAsync "
    "(or use the schedule tool for a timer), and wait for the harness exit notice."
)


UNQUOTE = str.maketrans("", "", "'\"\\")
NONWORD = str.maketrans({c: " " for c in "!\"#$%&'()*+,-.:;<=>?@[\\]^`{|}~"})


WATCHED_MARKS = ("$", "`", "{", "<(")
WATCHED_WORDS = frozenset(
    ("merge", "merges", "mergebranch", "mergepullrequest", "enqueuepullrequest")
    + ("enablepullrequestautomerge", "alias")
)
SPLIT = str.maketrans({c: " " for c in "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"})
API_WRITES = ("--method", "--input", "--field", "--raw-field")


def writes_api(words: list[str]) -> bool:
    """Whether a `gh api` call has a method flag, a field or `--input`: anything but a plain read."""
    return "api" in words and any(
        word.startswith(API_WRITES)
        or (word.startswith(("-f", "-x")) and not word.startswith("--"))
        for word in words
    )


def watched_gh(command: str) -> bool:
    """Whether the command, with its quotes removed, has a word that is `gh` or a path to it, in any letter case, and a word, mark or api write the merge guard must read."""
    bare = command.replace("\\\n", "").translate(UNQUOTE).lower()
    return (
        "gh" in bare
        and (
            any(mark in bare for mark in WATCHED_MARKS)
            or not WATCHED_WORDS.isdisjoint(bare.translate(SPLIT).split())
            or writes_api(bare.split())
        )
        and any(
            word.rsplit("/", 1)[-1] == "gh" for word in bare.translate(NONWORD).split()
        )
    )


def deny(reason: str, agy: bool = False) -> dict[str, object]:
    if agy:
        return {"decision": "deny", "reason": reason}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _parse_command(payload: dict[str, object]) -> tuple[str, bool, bool, str] | None:
    tool_call = payload.get("toolCall")
    if isinstance(tool_call, dict):
        args = tool_call.get("args")
        if (
            tool_call.get("name") != "run_command"
            or not isinstance(args, dict)
            or not isinstance(command := args.get("CommandLine"), str)
        ):
            return None
        skip_poll = bool(payload.get("parentConversationId")) or (
            args.get("IsDaemon") is True
        )
        cwd = str(payload.get("cwd") or args.get("Cwd") or ".")
        return command, True, skip_poll, cwd
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if payload.get("tool_name") != "Bash" or not isinstance(command, str):
        return None
    skip_poll = bool(payload.get("agent_id")) or (
        isinstance(tool_input, dict) and tool_input.get("run_in_background") is True
    )
    return command, False, skip_poll, str(payload.get("cwd") or ".")


def decision(payload: object) -> dict[str, object] | None:
    if not isinstance(payload, dict) or (parsed := _parse_command(payload)) is None:
        return None
    command, agy, skip_poll, cwd = parsed
    if watched_gh(command):
        from merge_guard import merge_problem

        if problem := merge_problem(command, cwd):
            return deny(f"Merge refused: {problem}", agy)
    if skip_poll or ("sleep" not in command and "select(" not in command):
        return None
    from wait_text import polls

    return deny(AGY_REASON if agy else REASON, agy) if polls(command) else None


def respond(decide: Callable[[object], dict[str, object] | None]) -> int:
    try:
        output = decide(json.load(sys.stdin))
    except ValueError:
        return 0
    if output is not None:
        print(json.dumps(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(respond(decision))
