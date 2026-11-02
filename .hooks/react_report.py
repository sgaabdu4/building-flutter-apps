"""Say why React Doctor reports a project as incomplete."""

from gate_config import JsonObject

DETAIL_LIMIT = 2000
MEMORY_FIX = (
    ". Fix: allow memory overcommit on the runner or give the job more memory,"
    " then rerun the job; the scan starts clean each time."
)


def incomplete_reason(project: JsonObject) -> str:
    skipped = project.get("skippedChecks")
    reasons = project.get("skippedCheckReasons")
    notes = reasons if isinstance(reasons, dict) else {}
    names = dict.fromkeys(
        str(name) for name in [*(skipped if isinstance(skipped, list) else []), *notes]
    )
    details = [
        f"{name} skipped: {str(notes.get(name, 'no reason reported'))[:DETAIL_LIMIT]}"
        for name in names
    ]
    diagnostics = project.get("diagnostics")
    if isinstance(diagnostics, list) and diagnostics:
        details.append(f"{len(diagnostics)} diagnostics")
    if not details:
        details.append("the project scan did not complete")
    message = "React Doctor reports incomplete checks or diagnostics: " + "; ".join(
        details
    )
    if "out of memory" in message.lower():
        message += MEMORY_FIX
    return message
