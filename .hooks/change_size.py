"""Decide whether a branch change is small enough to need no plan."""

import subprocess
from pathlib import Path, PurePosixPath

from dependency_graph import owner_language
from gate_config import Group, parse_config
from plans import _git_output, _is_test, default_branch_point, is_documentation

MAX_SMALL_LINES = 20
MAX_SMALL_FILES = 3
PROTECTED_NAMES = {
    "pyproject.toml",
    "uv.lock",
    "poetry.lock",
    "package.json",
    "pnpm-lock.yaml",
    "package-lock.json",
    "yarn.lock",
    "pubspec.yaml",
    "pubspec.lock",
    "hard-eng.gates.json",
    "AGENTS.md",
    "AGENTS.override.md",
    "schema.prisma",
    "appwrite.json",
    "appwrite.config.json",
}
PROTECTED_DIRECTORIES = {".github", ".hooks", ".agents", ".claude", "migrations"}


def _is_protected(path: PurePosixPath) -> bool:
    return (
        path.name in PROTECTED_NAMES
        or (path.name.startswith("requirements") and path.suffix == ".txt")
        or path.name.startswith("bun.lock")
        or path.suffix == ".sql"
        or bool(PROTECTED_DIRECTORIES.intersection(path.parts[:-1]))
    )


def _file_reason(name: str, added: str, removed: str) -> str | None:
    path = PurePosixPath(name)
    if added == "-":
        return f"it changes the binary file {name}"
    if _is_protected(path):
        return f"it changes {name}, which always needs a plan"
    if _is_test(path) and int(removed):
        return f"it removes lines from the test file {name}"
    return None


def _branch_change(root: Path, point: str) -> tuple[list[str], list[str], list[str]]:
    status = _git_output(
        root, "diff", "--name-status", "--no-renames", "-z", point, "--"
    ).split("\0")
    counts = _git_output(
        root, "diff", "--numstat", "--no-renames", "-z", point, "--"
    ).split("\0")
    untracked = _git_output(
        root, "ls-files", "--others", "--exclude-standard", "-z"
    ).split("\0")
    return status, counts, untracked


def _counted_lines(counts: list[str], names: set[str]) -> int | str:
    """Changed lines in the counted files, or the first reason one of them needs a plan."""
    total = 0
    for entry in filter(None, counts):
        added, removed, name = entry.split("\t", 2)
        if name not in names:
            continue
        if reason := _file_reason(name, added, removed):
            return reason
        total += int(added) + int(removed)
    return total


def configured_packages(root: Path) -> dict[str, Group]:
    try:
        config = parse_config(
            (root / "hard-eng.gates.json").read_text(), require_impact_review=False
        )
    except (OSError, ValueError, TypeError):
        return {}
    return {group["path"]: group for group in config["packages"]}


def update_written(root: Path, point: str) -> set[str]:
    """Paths a verified Hard Eng update in this branch wrote, scaffold and setup edits alike."""
    import tempfile

    from ci_setup import setup_written
    from update import fetch_sources, installed_update_paths, update_in_diff

    installed = installed_update_paths(root, point)
    found = update_in_diff(root, point)
    if not installed or found is None:
        return set()
    revision, previous, names = found
    with tempfile.TemporaryDirectory(prefix="hard-eng-plan-size-") as temporary:
        sources = fetch_sources(Path(temporary), revision, previous)
        return installed | setup_written(root, point, names - installed, sources)


def size_verdict(root: Path) -> tuple[bool, str]:
    """Whether the whole branch change, not just this session's, is small, and the first reason."""
    point = default_branch_point(root)
    if point is None:
        return False, "the branch point with the default branch cannot be found"
    try:
        status, counts, untracked = _branch_change(root, point)
    except (subprocess.CalledProcessError, OSError):
        return False, "the change cannot be measured"
    names = {name for name in status[1::2] + untracked if name}
    names -= update_written(root, point)
    if not names:
        return True, "only files the verified Hard Eng update wrote"
    packages = configured_packages(root)

    def documentation(name: str) -> bool:
        return is_documentation(Path(name), owner_language(packages, name))

    if all(documentation(name) for name in names):
        return True, "documentation only"

    names = {
        name
        for name in names
        if not documentation(name) or _is_protected(PurePosixPath(name))
    }
    added = sorted(
        {
            name
            for kind, name in zip(status[0::2], status[1::2], strict=False)
            if kind[:1] in {"A", "D", "T"} and name in names
        }
        | names.intersection(untracked)
    )
    if added:
        return False, f"it adds, deletes or renames the file {added[0]}"
    counted = _counted_lines(counts, names)
    if isinstance(counted, str):
        return False, counted
    total = counted
    if len(names) > MAX_SMALL_FILES:
        return False, f"it changes {len(names)} files, more than {MAX_SMALL_FILES}"
    if total > MAX_SMALL_LINES:
        return False, f"it changes {total} lines, more than {MAX_SMALL_LINES}"
    plural = "file" if len(names) == 1 else "files"
    return True, f"{len(names)} {plural}, {total} changed lines"


def plan_not_needed(root: Path) -> bool:
    small, reason = size_verdict(root)
    if small:
        print(f"Size: small ({reason}); no plan needed.")
    else:
        print(f"Size: big, because {reason}; a plan is needed.")
    return small
