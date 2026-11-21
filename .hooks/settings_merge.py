"""Merge installed settings into a project's settings file."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gate_config import JsonObject


AGY_POLL_COMMAND = (
    'python3 "$(git rev-parse --show-toplevel)/.hooks/polling.py" 2>/dev/null || true'
)
AGY_POLL_HOOK: JsonObject = {
    "matcher": "run_command",
    "hooks": [{"type": "command", "command": AGY_POLL_COMMAND, "timeout": 5}],
}


def hook_identity(item: object) -> str:
    """The same matcher and commands are the same hook, whatever its timeout."""
    handlers = item.get("hooks") if isinstance(item, dict) else None
    if isinstance(item, dict) and isinstance(handlers, list):
        commands = [h.get("command") for h in handlers if isinstance(h, dict)]
        return json.dumps([item.get("matcher"), commands])
    if isinstance(item, dict) and "command" in item:
        return json.dumps([item.get("type", "command"), item.get("command")])
    return json.dumps(item, sort_keys=True)


def configure_agent_hooks(agent: str, current: JsonObject, command: str) -> JsonObject:
    """Merge Hard Eng's managed hooks and defaults into one agent's settings file."""
    import agent_hooks

    if agent == "agy":
        return configure_agy_hooks(current, command, agent_hooks.HOOK_TIMEOUTS)
    hooks: JsonObject = {}
    for event, native in agent_hooks.hook_events(agent).items():
        timeout = agent_hooks.HOOK_TIMEOUTS.get(event, 10)
        status_message = (
            agent_hooks.CODEX_HOOK_STATUS.get(event) if agent == "codex" else None
        )
        hooks[native] = [
            agent_hooks.owned_hook_entry(
                agent, event, command, timeout, status_message=status_message
            )
        ]
    if agent == "claude":
        hooks["PostToolUseFailure"] = [agent_hooks.FAILURE_HOOK]
        hooks["PreToolUse"] = list(agent_hooks.CLAUDE_TOOL_HOOKS)
    if current.get("disableAllHooks"):
        raise ValueError(f"{agent} hooks are disabled; ask before changing that")
    agent_hooks.remove_routine_hooks(current, agent, command)
    additions: JsonObject = {"hooks": hooks}
    if agent == "claude":
        from mcp_setup import retire_claude_integrations

        retire_claude_integrations(current)
        current.setdefault("advisorModel", "fable")
        current.setdefault("outputStyle", "Plain STE")
        current.setdefault("attribution", {"commit": "", "pr": "", "sessionUrl": False})
        current.setdefault("autoCompactWindow", 500000)
        current.setdefault("bashOutputMaxChars", 10000)
        current.setdefault("subagentPromptCacheTtl", "1h")
        env = current.get("env")
        if not (isinstance(env, dict) and "CLAUDE_CODE_FORK_SUBAGENT" in env):
            additions["env"] = {"CLAUDE_CODE_FORK_SUBAGENT": "0"}
    return merge(current, additions)


def configure_agy_hooks(
    current: JsonObject, command: str, timeouts: dict[str, int]
) -> JsonObject:
    """Merge Hard Eng's Antigravity hooks under the top-level 'hard-eng' key."""
    existing = current.get("hard-eng")
    if isinstance(existing, dict) and existing.get("enabled") is False:
        raise ValueError("agy hooks are disabled; ask before changing that")
    additions: JsonObject = {
        "hard-eng": {
            "SessionStart": [
                {
                    "type": "command",
                    "command": f"{command} session agy",
                    "timeout": timeouts["session"],
                }
            ],
            "PreToolUse": [AGY_POLL_HOOK],
            "Stop": [
                {
                    "type": "command",
                    "command": f"{command} stop agy",
                    "timeout": timeouts["stop"],
                }
            ],
        }
    }
    return merge(current, additions)


def agy_event_output(event: str, output: JsonObject) -> JsonObject:
    """Format a session or stop response using Antigravity's protojson contract."""
    if event == "stop":
        return (
            {"decision": "continue", "reason": output["reason"]}
            if output.get("decision") == "block"
            else {}
        )
    message = str(output.get("systemMessage", ""))
    return {"injectSteps": [{"systemMessage": {"systemMessage": message}}]}


def paused_turn(payload: JsonObject) -> JsonObject | None:
    if (
        payload.get("parentConversationId")
        or payload.get("terminationReason") == "USER_CANCELED"
    ):
        return {}
    if (
        payload.get("stop_hook_active") is True
        or payload.get("continuationActive") is True
    ):
        return {
            "systemMessage": "Report blockers honestly; don't claim a pass; no stop-hook loop."
        }
    tasks = payload.get("background_tasks")
    if payload.get("fullyIdle") is False or (
        isinstance(tasks, list)
        and any(
            isinstance(t, dict)
            and t.get("type") in {"subagent", "workflow", "teammate"}
            for t in tasks
        )
    ):
        return {
            "systemMessage": "Hard Eng: background agents still editing; checks run after they finish. Don't claim done."
        }
    return None


def merge(
    current: JsonObject, additions: JsonObject, path: tuple[str, ...] = ()
) -> JsonObject:
    if not isinstance(current, dict):
        raise TypeError(f"Conflicting setting {'.'.join(path)}; expected an object")
    for key, value in additions.items():
        location = (*path, key)
        existing = current.get(key)
        if key not in current:
            current[key] = value
        elif isinstance(value, dict):
            if not isinstance(existing, dict):
                raise TypeError(
                    f"Conflicting setting {'.'.join(location)}; expected an object"
                )
            merge(existing, value, location)
        elif (
            isinstance(value, list)
            and path in {("hooks",), ("hard-eng",)}
            and isinstance(existing, list)
        ):
            known = {hook_identity(item) for item in existing}
            for item in value:
                if hook_identity(item) not in known:
                    existing.append(item)
        elif current[key] != value:
            raise ValueError(
                f"Conflicting setting {'.'.join(location)}; preserve it and ask before changing it"
            )
    return current
