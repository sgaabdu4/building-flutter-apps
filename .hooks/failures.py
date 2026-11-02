"""Repeat counts: failed checks per checkout; as Claude's PostToolUseFailure hook, failed tool calls per session."""

import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,200}")
NOT_A_MISTAKE = re.compile(
    r"(?i)doesn't want to (?:proceed|take this action)|tool use was rejected|"
    r"permission for this action was denied|hook error|interrupted by user|tool call interrupted"
)
ERROR_NOISE = (
    (r"(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<id>"),
    (r"(?i)\b[0-9a-f]{7,}\b", "<hex>"),
    (r"\d+(?:\.\d+)?", "#"),
)


def repeat_note(root: Path, output: str) -> str:
    """Counts each failure by its failing lines, else all lines, with numbers masked; a second sighting is a repeat."""
    masked = [
        re.sub(r"\d+(?:\.\d+)?", "#", line.strip())
        for line in output.splitlines()
        if line.strip()
    ]
    if not masked:
        return ""
    lines = {line for line in masked if re.search(r"(?i)fail|error", line)} or set(
        masked
    )
    key = hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()[:16]
    path = root / ".hard-eng/failures.json"
    try:
        loaded: object = json.loads(path.read_text())
    except (OSError, ValueError):
        loaded = None
    seen: dict[str, int] = (
        {name: value for name, value in loaded.items() if isinstance(value, int)}
        if isinstance(loaded, dict)
        else {}
    )
    count = seen.pop(key, 0) + 1
    seen[key] = count
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(dict(list(seen.items())[-100:])))
    if count < 2:
        return ""
    return (
        f"\n\nRepeat failure: seen {count} times in this checkout. Before another similar try, "
        "follow .agents/skills/he-learn/SKILL.md: find the shared cause and every place it occurs, "
        "then record them on the plan's Same cause line."
    )


def failure_context(root: Path, payload: dict[str, object]) -> str:
    """Warn from the third sighting of one tool error in a session; refusals and bare exit codes never count."""
    error, identifier = payload.get("error"), payload.get("session_id")
    if (
        payload.get("is_interrupt") is True
        or not isinstance(error, str)
        or not isinstance(identifier, str)
        or not SESSION_ID.fullmatch(identifier)
        or NOT_A_MISTAKE.search(error)
        or not re.sub(r"(?i)exit code|[\d\s]", "", error)
    ):
        return ""
    state = root / ".hard-eng/sessions" / (identifier + ".json")
    try:
        saved: object = json.loads(state.read_text())
    except (OSError, ValueError):
        return ""
    if not isinstance(saved, dict):
        return ""
    for pattern, mark in ERROR_NOISE:
        error = re.sub(pattern, mark, error)
    sighting = f"{payload.get('tool_name')}\0{payload.get('agent_id')}\0{error.strip()}"
    key = hashlib.sha256(sighting.encode()).hexdigest()[:16]
    seen = saved.get("failures")
    seen = seen if isinstance(seen, dict) else {}
    earlier = seen.get(key)
    count = (earlier if isinstance(earlier, int) else 0) + 1
    # Parallel failed calls share this file; a whole-file replace never leaves it half written.
    written = state.with_name(f"{state.name}.{os.getpid()}.tmp")
    try:
        written.write_text(json.dumps({**saved, "failures": {**seen, key: count}}))
        written.replace(state)
    except OSError:
        return ""
    if count < 3:
        return ""
    return (
        f"Same tool error {count} times this session. Stop retrying it: change approach or ask the user. "
        "Repeat cause → .agents/skills/he-learn/SKILL.md."
    )


def main(root: Path = ROOT) -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if isinstance(payload, dict) and (message := failure_context(root, payload)):
        context = {"hookEventName": "PostToolUseFailure", "additionalContext": message}
        print(json.dumps({"hookSpecificOutput": context}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
