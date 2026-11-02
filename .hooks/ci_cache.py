"""Report workflow cache settings that cannot work on a self-hosted runner."""

import json
import re
import sys
from pathlib import Path

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
    """Lines that set a tool directory from the runner temp folder, ignoring the runner's own value."""
    messages = []
    for number, line in enumerate(text.splitlines(), 1):
        found = UNKEPT_DIRECTORY.search(line)
        if found and f"${{{found[1]}:-" not in line:
            messages.append(
                f"CI tool directories: {relative}:{number} sets {found[1]} from the runner "
                "temp folder, so a runner that exports its own value is ignored and every "
                f"run downloads the tools again. Set it in a step with echo "
                f'"{found[1]}=${{{found[1]}:-$RUNNER_TEMP/hard-eng-tools/...}}" >> "$GITHUB_ENV"; '
                "a job env mapping cannot read the runner's value."
            )
    return messages


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
        if not isinstance(job, dict) or not re.search(
            r"vars\.|self-hosted", json.dumps(job.get("runs-on"))
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
