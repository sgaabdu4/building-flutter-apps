#!/usr/bin/env python3
"""Refuse an old Python, answer a hook event early, else run the commands."""

import json
import sys

PYTHON_FLOOR = (3, 12)
if sys.version_info < PYTHON_FLOOR:
    v = f"{sys.version_info[0]}.{sys.version_info[1]}"
    refusal = f"Hard Eng needs Python {PYTHON_FLOOR[0]}.{PYTHON_FLOOR[1]} or later, but python3 here is {v}. No check or hook ran. Put a newer python3 first on PATH."
    event, agy = sys.argv[1:2], sys.argv[2:3] == ["agy"]
    msg = {"systemMessage": refusal}
    if event == ["stop"]:
        d = json.load(sys.stdin)
        skip = True in (d.get("stop_hook_active"), d.get("continuationActive"))
        if agy and (d.get("parentConversationId") or d.get("fullyIdle") is False):
            skip = True
        skip = skip or (agy and d.get("terminationReason") == "USER_CANCELED")
        block = {"decision": "continue" if agy else "block", "reason": refusal}
        print(json.dumps(({} if agy else msg) if skip else block))
    elif event == ["session"]:
        print(json.dumps({"injectSteps": [{"systemMessage": msg}]} if agy else msg))
    else:
        sys.exit(refusal)
    sys.exit(0)

if __name__ == "__main__":
    a, agents = sys.argv[1:], ("claude", "codex", "agy")
    web = a[:1] == ["look"] or (
        a[:1] == ["browser"] and a[1:2] not in (["-h"], ["--help"])
    )
    if web or (len(a) == 2 and a[0] in ("session", "stop") and a[1] in agents):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        if web:
            from browser import run as run_web

            raise SystemExit(run_web(root, a))
        from agent_hooks import handle_event

        raise SystemExit(handle_event(root, a[0], a[1]))
    from gate_runner import run

    run()
