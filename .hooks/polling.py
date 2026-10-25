"""Claude Code PreToolUse hook: deny foreground polling (HE-NO-FOREGROUND-POLL)."""

import json
import re
import sys

LOOP = re.compile(r"\b(?:while|until)\b")
SHELL_SLEEP = re.compile(r"\bsleep\s+(\d+(?:\.\d+)?)([smhd]?)\b")
HIDDEN_SLEEP = re.compile(
    r"\btime\.sleep\(\s*(\d+(?:\.\d+)?)|\bselect\(\s*undef\s*,\s*undef\s*,\s*undef\s*,\s*(\d+(?:\.\d+)?)"
)
UNIT = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}
REASON = (
    "HE-NO-FOREGROUND-POLL: this command waits in the foreground with sleep. "
    "Start the long job once with run_in_background: true, then keep working or end the turn; "
    "the harness tells you when it exits. Read its output file after that notice."
)


def polls(command: str) -> bool:
    shell = [float(value) * UNIT[unit] for value, unit in SHELL_SLEEP.findall(command)]
    hidden = [float(a or b) for a, b in HIDDEN_SLEEP.findall(command)]
    looped = bool(LOOP.search(command)) and max(shell + hidden, default=0) >= 1
    return looped or max(shell, default=0) >= 30


def decision(payload: object) -> dict[str, object] | None:
    if not isinstance(payload, dict) or payload.get("agent_id"):
        return None
    tool_input = payload.get("tool_input")
    if payload.get("tool_name") != "Bash" or not isinstance(tool_input, dict):
        return None
    command = tool_input.get("command")
    if tool_input.get("run_in_background") is True or not isinstance(command, str):
        return None
    if not polls(command):
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON,
        }
    }


def main() -> int:
    try:
        output = decision(json.load(sys.stdin))
    except ValueError:
        return 0
    if output is not None:
        print(json.dumps(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
