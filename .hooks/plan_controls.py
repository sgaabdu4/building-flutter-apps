"""The `Controls:` line of a visible-change plan: each control names the shared part it reuses, or a new part with a mockup that `look` has opened."""

import os
from collections.abc import Callable
from pathlib import Path, PurePosixPath

MOCKUP_OPEN = " — mockup !["


def plain_word(text: str) -> bool:
    return bool(text) and not any(c.isspace() or c == "`" for c in text)


def reused_part(entry: str) -> str | None:
    head, found, rest = entry.partition(" — reuses `")
    part = rest[:-1]
    return part if head and found and rest.endswith("`") and plain_word(part) else None


def new_part(entry: str) -> tuple[bool, str | None]:
    """Whether the entry is a `— new` entry, and the mockup path it names, if any."""
    head, found, rest = entry.partition(" — new `")
    part, tick, tail = rest.partition("`")
    if not (head and found and tick and plain_word(part)):
        return False, None
    if not tail:
        return True, None
    inner = tail[len(MOCKUP_OPEN) :].removesuffix(")")
    alt, close, url = inner.partition("](")
    shaped = tail.startswith(MOCKUP_OPEN) and tail.endswith(")") and close
    clean = "]" not in alt and "\n" not in alt and ")" not in url
    named = bool(url) and not any(c.isspace() for c in url)
    return (True, url) if shaped and clean and named else (False, None)


def plan_root(plan: Path) -> Path | None:
    for folder in plan.resolve().parents:
        if (folder / ".git").exists():
            return folder
    return None


def looked_hashes(root: Path) -> set[str]:
    import json
    import subprocess

    """The hashes of the images that a `look` record of this checkout says were opened."""
    done = subprocess.run(
        ["git", "rev-parse", "--git-path", "hard-eng/look"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    found: set[str] = set()
    for record in (root / done.stdout.strip()).glob("*.json") if done.stdout else []:
        try:
            images = json.loads(record.read_text())["images"]
            found.update(i["sha256"] for i in images if i["read"] is True)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return found


def mockup_problem(entry: str, mockup: str, root: Path) -> str | None:
    image = root / mockup
    if mockup.startswith(("http://", "https://")) or not image.is_file():
        return f"Controls: the mockup in `{entry}` must be an image file in the repository, and `{mockup}` is not"
    import hashlib

    if os.environ.get("GITHUB_ACTIONS"):
        return None
    if hashlib.sha256(image.read_bytes()).hexdigest() not in looked_hashes(root):
        return f"Controls: the mockup `{mockup}` has no `look` record; run `python3 .hooks/hard-eng.py look {mockup}`"
    return None


def is_tracked(part: str, root: Path) -> bool:
    import subprocess

    listed = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", part],
        cwd=root,
        capture_output=True,
        check=False,
    )
    return listed.returncode == 0


def part_problem(part: str, root: Path, tracked: bool = False) -> str | None:
    """The shared part must be a file under the project's `ui_paths` when it has any, and not a test file; the full gate also needs it tracked."""
    from plans import _is_test

    if not (root / part).is_file():
        return f"Controls: the shared part `{part}` must be one file of the repository"
    if _is_test(PurePosixPath(part)):
        return (
            f"Controls: the shared part `{part}` is a test file, not a shared component"
        )
    if tracked and not is_tracked(part, root):
        return f"Controls: the shared part `{part}` is not a tracked file"
    import fnmatch
    import json

    try:
        policy = json.loads((root / "hard-eng.gates.json").read_text())
        patterns = policy["shipping"]["ui_paths"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if patterns and not any(fnmatch.fnmatchcase(part, pattern) for pattern in patterns):
        return f"Controls: the shared part `{part}` is not under the project's ui_paths ({', '.join(patterns)})"
    return None


def entry_problem(entry: str, root: Path | None, tracked: bool = False) -> str | None:
    if reused := reused_part(entry):
        return None if root is None else part_problem(reused, root, tracked)
    is_new, mockup = new_part(entry)
    if not is_new:
        return f"Controls: `{entry}` needs `— reuses `<repo path>`` or `— new `<repo path>` — mockup ![..](..)``"
    if mockup is None:
        return f"Controls: the new shared part in `{entry}` needs a mockup image"
    return None if root is None else mockup_problem(entry, mockup, root)


def controls_problem(
    content: str, root: Path | None, tracked: bool = False
) -> str | None:
    found = [line[9:] for line in content.splitlines() if line.startswith("Controls:")]
    if len(found) != 1 or not found[0].strip():
        return "ux_reference needs one `Controls:` line: each changed or new control with the shared part it reuses, or `None — reason`"
    line = found[0].strip()
    if line.startswith("None — ") and line[7:8].strip():
        return None
    problems = (entry_problem(entry, root, tracked) for entry in line.split("; "))
    return next((problem for problem in problems if problem), None)


def judged_controls(
    content: str, root: Path | None, age: Callable[[], bool] | None
) -> None:
    """A Complete plan untouched since the last Hard Eng update may predate the Controls line."""
    problem = controls_problem(content, root)
    if problem and ("\nControls:" in f"\n{content}" or age is None or age()):
        raise ValueError(problem)


def tracked_problem(content: str, root: Path | None) -> str | None:
    """The full gate's extra check for a plan that has a `Controls:` line: each reused part is tracked by Git."""
    if "\nControls:" not in f"\n{content}":
        return None
    return controls_problem(content, root, tracked=True)
