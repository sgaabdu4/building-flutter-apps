"""Claude Code PreToolUse hook: note real-app previews on Artifact pages (HE-REAL-APP-PREVIEW)."""

PAGE_ACTIONS = {"publish", "quickstart"}
NOTE = (
    "HE-REAL-APP-PREVIEW: if this page shows a proposed change to this project's app screens, "
    "do not publish a hand-made mock. Build the change in the real app in an isolated checkout, "
    "capture before and after images with the project's browser or device tools, send them in the "
    "conversation and record them in the plan's ux_reference. For anything else, carry on."
)


def decision(payload: object) -> dict[str, object] | None:
    if not isinstance(payload, dict) or payload.get("tool_name") != "Artifact":
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    if tool_input.get("action", "publish") not in PAGE_ACTIONS:
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": NOTE,
        }
    }


if __name__ == "__main__":
    from polling import respond

    raise SystemExit(respond(decision))
