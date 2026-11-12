"""Report workflow cache settings that cannot work on a self-hosted runner."""

import json
import re
import sys
from pathlib import Path

VARIABLE_OR_SELF_HOSTED_CONDITION = re.compile(r"vars\.|self-hosted")

TOOL_DIRECTORIES = (
    "MISE_DATA_DIR",
    "MISE_CACHE_DIR",
    "MISE_STATE_DIR",
    "BUN_INSTALL_CACHE_DIR",
)


UNKEPT_DIRECTORY = re.compile(
    rf"\b({'|'.join(TOOL_DIRECTORIES)})(?:=|: *)"
    r"[^\n]*(?:RUNNER_TEMP|runner\.temp)"
)
BROWSER_CACHE = "ms-playwright"


def tool_directory_messages(relative: str, text: str) -> list[str]:
    """One message for the lines that set a tool directory from the runner temp folder, ignoring the runner's own value."""
    found = [
        (str(number), match[1])
        for number, line in enumerate(text.splitlines(), 1)
        if (match := UNKEPT_DIRECTORY.search(line)) and f"${{{match[1]}:-" not in line
    ]
    if not found:
        return []
    names = list(dict.fromkeys(name for _, name in found))
    step = "; ".join(
        f'echo "{name}=${{{name}:-$RUNNER_TEMP/hard-eng-tools/...}}"' for name in names
    )
    # shellcheck, which actionlint runs, refuses one redirect for each line (SC2129).
    step = step if len(names) == 1 else f"{{ {step}; }}"
    sets, lines = ("sets", "that line") if len(found) == 1 else ("set", "those lines")
    message = (
        f"CI tool directories: {relative}:{','.join(number for number, _ in found)} "
        f"{sets} {', '.join(names)} from the runner temp folder, so a runner that "
        "exports its own value is ignored and every run downloads the tools again. "
        f'Replace {lines} with a step whose `run: |` block holds {step} >> "$GITHUB_ENV"; '
        "then remove an `env:` key that has no lines left; "
        "a job env mapping cannot read the runner's value."
    )
    return [message]


def browser_cache_messages(relative: str, text: str) -> list[str]:
    """Playwright cache steps whose default folder is missing when the runner sets its own browser path."""
    import yaml

    if "PLAYWRIGHT_BROWSERS_PATH" in text:
        return []
    try:
        jobs = yaml.safe_load(text).get("jobs")
    except (yaml.YAMLError, AttributeError):
        return []
    messages = []
    for job_name, job in (jobs if isinstance(jobs, dict) else {}).items():
        if not isinstance(job, dict) or not VARIABLE_OR_SELF_HOSTED_CONDITION.search(
            json.dumps(job.get("runs-on"))
        ):
            continue
        for step in job.get("steps") or []:
            path = str((step.get("with") or {}).get("path", ""))
            if (
                str(step.get("uses", "")).startswith("actions/cache@")
                and BROWSER_CACHE in path
            ):
                messages.append(
                    f"CI browser cache: {relative} job {job_name} caches {path.strip()}, "
                    "which does not exist when the runner sets PLAYWRIGHT_BROWSERS_PATH, so "
                    "the cache is never saved. Add a step before it with echo "
                    '"PLAYWRIGHT_BROWSERS_PATH=${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/'
                    'ms-playwright}" >> "$GITHUB_ENV" and cache ${{ env.PLAYWRIGHT_BROWSERS_PATH }}.'
                )
    return messages


def report_cache_problems(root: Path, changes: dict[str, str]) -> None:
    for path in sorted((root / ".github/workflows").glob("*")):
        if path.is_file() and path.suffix in {".yml", ".yaml"}:
            relative = path.relative_to(root).as_posix()
            text = changes.get(relative, path.read_text())
            for message in (
                *tool_directory_messages(relative, text),
                *browser_cache_messages(relative, text),
            ):
                print(message, file=sys.stderr)
