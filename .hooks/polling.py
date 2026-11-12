"""Claude Code PreToolUse hook: deny foreground polling (HE-NO-FOREGROUND-POLL)."""

import json
import sys
from collections.abc import Callable

REASON = (
    "HE-NO-FOREGROUND-POLL: this command waits in the foreground with sleep. "
    "Start the long job once with run_in_background: true; "
    "the harness tells you when it exits. Read its output file after that notice."
)


def decision(payload: object) -> dict[str, object] | None:
    if not isinstance(payload, dict) or payload.get("agent_id"):
        return None
    tool_input = payload.get("tool_input")
    if payload.get("tool_name") != "Bash" or not isinstance(tool_input, dict):
        return None
    command = tool_input.get("command")
    if tool_input.get("run_in_background") is True or not isinstance(command, str):
        return None
    if "sleep" not in command and "select(" not in command:
        return None
    from wait_text import polls

    if not polls(command):
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON,
        }
    }


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
