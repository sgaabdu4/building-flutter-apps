"""Decide whether a branch change is small enough to need no plan."""

import subprocess
from pathlib import Path, PurePosixPath

from dependency_graph import owner_language
from gate_config import SOURCE_FILE, Group, changed_files, parse_config
from plans import (
    SMALL_SIZE,
    _git_output,
    _is_test,
    acceptance_tests,
    default_branch_point,
    is_documentation,
    is_plan_path,
    plan_files,
    plan_sections,
    plan_status,
    release_references,
    validate_plan,
)
from project_files import KEPT, keep, keeping

NO_CHANGE = "no change"
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
    return None


def _branch_change(root: Path, point: str) -> tuple[list[str], list[str], list[str]]:
    status = _git_output(
        root, "diff", "--name-status", "--no-renames", "-z", point, "--"
    ).split("\0")
    counts = _git_output(
        root, "diff", "--numstat", "--no-renames", "-z", point, "--"
    ).split("\0")
    # The Linux sandbox binds /dev/null over missing protected paths; Git lists them but cannot add them.
    untracked = [
        name
        for name in _git_output(
            root, "ls-files", "--others", "--exclude-standard", "-z"
        ).split("\0")
        if (root / name).is_file() or (root / name).is_symlink()
    ]
    return status, counts, untracked


def _counted_lines(counts: list[str], names: set[str]) -> tuple[int, list[str]] | str:
    """Changed lines, the test files that lose lines, or the first reason a file needs a plan."""
    total = 0
    losing: list[str] = []
    for entry in filter(None, counts):
        added, removed, name = entry.split("\t", 2)
        if name not in names:
            continue
        if reason := _file_reason(name, added, removed):
            return reason
        total += int(added) + int(removed)
        if int(removed) and _is_test(PurePosixPath(name)):
            losing.append(name)
    return total, sorted(losing)


def _removed_check(root: Path, point: str, names: list[str]) -> str | None:
    """The reason a test file loses more than import lines and empty lines, or None."""
    from comments import DIFF, HASH, SLASH, changed_lines, import_or_empty

    for name in names:
        if Path(name).suffix not in HASH | SLASH:
            return f"it removes lines from the test file {name}"
    try:
        diff = subprocess.check_output(
            [*DIFF, point, "--", *(f":(literal){name}" for name in names)],
            cwd=root,
            text=True,
            errors="replace",
        )
    except (subprocess.CalledProcessError, OSError):
        return "the change cannot be measured"
    removed = changed_lines(diff)[1]
    for name in names:
        if not all(import_or_empty(text) for _, text in removed.get(name, [])):
            return f"it removes lines from the test file {name}"
    return None


def configured_packages(root: Path) -> dict[str, Group]:
    try:
        config = parse_config(
            (root / "hard-eng.gates.json").read_text(), require_impact_review=False
        )
    except (OSError, ValueError, TypeError):
        return {}
    return {group["path"]: group for group in config["packages"]}


def update_written(
    root: Path,
    point: str,
    names: set[str],
    found: tuple[str, str] | None = None,
) -> set[str]:
    """Paths a verified Hard Eng update in this branch wrote, scaffold and setup edits alike."""
    from ci_setup import setup_written
    from update import (
        maybe_installed,
        proven_installed,
        shared_sources,
        update_since,
    )

    if not any(maybe_installed(name) for name in names):
        return set()
    if (found := found or update_since(root, point)) is None:
        return set()
    installed = proven_installed(root, point, names, *found)
    if not installed:
        return set()
    sources = shared_sources(*found)
    return installed | setup_written(root, point, names - installed, sources)


def update_only(root: Path, base: str, changed: set[str]) -> bool:
    """Whether a clean tree holds only files a verified Hard Eng update wrote."""
    from update import maybe_installed, update_since

    if not any(maybe_installed(name) for name in changed):
        return False
    if (found := update_since(root, base)) is None:
        return False
    if _git_output(root, "status", "--porcelain"):
        return False
    return not changed - update_written(root, base, changed, found)


def _verdict(
    root: Path,
    point: str,
    status: list[str],
    counts: list[str],
    untracked: list[str],
    names: set[str],
    packages: dict[str, Group],
) -> tuple[bool, str]:
    def documentation(name: str) -> bool:
        return is_documentation(Path(name), owner_language(packages, name))

    if all(documentation(name) for name in names):
        return True, "documentation only"

    names = {
        name
        for name in names
        if name != "hard-eng.debt.json"
        and (not documentation(name) or _is_protected(PurePosixPath(name)))
    }
    added = sorted(
        {
            name
            for kind, name in zip(status[0::2], status[1::2], strict=False)
            if kind[:1] in {"A", "D", "T"} and name in names
        }
        | names.intersection(untracked)
    )
    if SOURCE_FILE in added:
        return False, "this branch installs Hard Eng"
    if added:
        return False, f"it adds, deletes or renames the file {added[0]}"
    counted = _counted_lines(counts, names)
    if isinstance(counted, str):
        return False, counted
    total, losing = counted
    if len(names) > MAX_SMALL_FILES:
        return False, f"it changes {len(names)} files, more than {MAX_SMALL_FILES}"
    if total > MAX_SMALL_LINES:
        return False, f"it changes {total} lines, more than {MAX_SMALL_LINES}"
    if losing and (reason := _removed_check(root, point, losing)):
        return False, reason
    plural = "file" if len(names) == 1 else "files"
    return True, f"{len(names)} {plural}, {total} changed lines"


def merge_point(root: Path) -> str | None:
    """While a merge is in progress: the merge base of the release reference with both merge parents."""
    folder = root / ".git"
    try:
        if folder.is_file():
            folder = root / folder.read_text().split("gitdir:", 1)[1].strip()
        merging = (folder / "MERGE_HEAD").is_file()
    except (OSError, IndexError):
        return None
    for reference in release_references(root) if merging else ():
        try:
            return _git_output(
                root, "merge-base", reference, "HEAD", "MERGE_HEAD"
            ).strip()
        except (subprocess.CalledProcessError, OSError):
            continue
    return None


def size_verdict(root: Path) -> tuple[bool, str]:
    """Whether the whole branch change, not just this session's, is small, and the first reason."""
    point = merge_point(root) or default_branch_point(root)
    if point is None:
        return False, "the branch point with the default branch cannot be found"
    try:
        status, counts, untracked = _branch_change(root, point)
    except (subprocess.CalledProcessError, OSError):
        return False, "the change cannot be measured"
    names = {name for name in status[1::2] + untracked if name}
    if not names:
        return True, NO_CHANGE
    names -= update_written(root, point, names)
    if not names:
        return True, "only files the verified Hard Eng update wrote"
    packages = configured_packages(root)
    return _verdict(root, point, status, counts, untracked, names, packages)


def judged_point(root: Path) -> str | None:
    """The branch point that a check with no base judges from, once Hard Eng is on it; a first install keeps its own check."""
    point = default_branch_point(root)
    if point is None:
        return None
    try:
        _git_output(root, "cat-file", "-e", f"{point}:.hooks/hard-eng.py")
    except (subprocess.CalledProcessError, OSError):
        return None
    return point


def _revision(root: Path, reference: str) -> str | None:
    return keep(
        "references", ("revision", str(root), reference), lambda: _tip(root, reference)
    )


def _tip(root: Path, reference: str) -> str | None:
    try:
        return _git_output(
            root, "rev-parse", "--verify", "-q", f"{reference}^{{commit}}"
        )
    except (subprocess.CalledProcessError, OSError):
        return None


def released_plans(root: Path, base: str | None) -> set[str]:
    """Plans changed since the release base, so a feature check sees what the release checks."""
    references = release_references(root)
    revisions = {name: _revision(root, name) for name in references}
    tips = set(revisions.values())
    remote = {tip for name, tip in revisions.items() if name.startswith("origin/")}
    if base is None and remote - {None}:
        # A caller's base names what is released; without one, origin does.
        tips = remote
    point = default_branch_point(root)
    if point is None or _revision(root, base or "HEAD") in tips:
        return set()
    return {
        name for name in changed_files(root, point) or () if is_plan_path(Path(name))
    }


def held_by_base(root: Path, path: Path) -> bool:
    """A remote base holds the plan and the branch did not change it; with no remote base each plan is the branch's own."""
    with keeping("references"):
        remote = any(
            _revision(root, name)
            for name in release_references(root)
            if name.startswith("origin/")
        )
        return remote and str(path.relative_to(root)) not in released_plans(root, None)


def moved_plans(root: Path, base: str | None, changed: set[str]) -> set[str]:
    """Changed plan paths that only moved a plan the base holds."""
    gone = [
        name
        for name in changed
        if is_plan_path(Path(name)) and not (root / name).exists()
    ]
    if not gone:
        return set()
    references = [
        reference for reference in (base, default_branch_point(root)) if reference
    ]
    held: dict[str, str] = {}
    for name in gone:
        for reference in references:
            try:
                held[_git_output(root, "show", f"{reference}:{name}")] = name
                break
            except (subprocess.CalledProcessError, OSError):
                continue
    moved = {
        name
        for name in changed
        if held
        and is_plan_path(Path(name))
        and (root / name).is_file()
        and (root / name).read_text() in held
    }
    return moved


def plan_words(text: str) -> list[str]:
    """The words of a plan; every table rule counts as one form."""
    return [
        "---" if word.count("-") > 2 and not word.strip("-:") else word
        for word in text.split()
    ]


def fails_todays_rules(path: Path) -> bool:
    if plan_status(path.read_text()) != "Complete":
        return False
    try:
        validate_plan(path)
    except ValueError:
        return True
    return False


def held_words(root: Path, reference: str, name: str) -> list[str] | None:
    try:
        return plan_words(_git_output(root, "show", f"{reference}:{name}"))
    except (subprocess.CalledProcessError, OSError):
        return None


def reformatted_plans(root: Path, base: str | None, changed: set[str]) -> set[str]:
    """Changed Complete plans that fail today's rules but keep every word of the copy that the base and the branch point hold."""
    failing = [
        name
        for name in changed
        if is_plan_path(Path(name))
        and (root / name).is_file()
        and fails_todays_rules(root / name)
    ]
    if not failing:
        return set()
    references = {
        reference
        for reference in (base or "HEAD", default_branch_point(root))
        if reference
    }
    return {
        name
        for name in failing
        if all(
            held_words(root, reference, name) == plan_words((root / name).read_text())
            for reference in references
        )
    }


def plan_not_needed(root: Path) -> bool:
    small, reason = size_verdict(root)
    if reason == NO_CHANGE:
        return True
    if small:
        print(f"{SMALL_SIZE}{reason}); no plan needed.")
    else:
        print(f"Size: big, because {reason}; a plan is needed.")
    return small


def judged_plans(
    root: Path, base: str | None, changed: set[str]
) -> tuple[set[str], list[Path], list[Path]]:
    """The changed files with released plans added and moved plans out, every plan file, and the plans that judge the change."""
    changed = changed | released_plans(root, base)
    changed -= moved_plans(root, base, changed)
    skipped: set[str] = keep("references", ("reformatted", str(root)), set)
    changed -= skipped
    paths = plan_files(root)
    applicable = [path for path in paths if str(path.relative_to(root)) in changed]
    return (
        changed,
        paths,
        applicable
        or [
            path
            for path in paths
            if plan_status(path.read_text()) not in {None, "Complete"}
        ],
    )


def judged_stage(root: Path, base: str | None, stage: str | None) -> str:
    """The stage that validate_plans reaches; a failing run is judged again without its reformatted old plans."""
    from plans import validate_plans

    with keeping("references"):
        try:
            return validate_plans(root, base, stage)
        except ValueError:
            point = base or judged_point(root)
            changed = changed_files(root, point or "HEAD") or set()
            changed |= released_plans(root, base)
            found = reformatted_plans(root, point, changed)
            if not found:
                raise
            KEPT["references"][("reformatted", str(root))] = found
            return validate_plans(root, base, stage)


def plan_tests(root: Path, base: str | None) -> set[str]:
    """Test names that the active plans' acceptance lines depend on."""
    _, _, applicable = judged_plans(
        root, base, changed_files(root, base or "HEAD") or set()
    )
    from requirement_registry import requirement_tests

    names = set()
    for path in applicable:
        content = path.read_text()
        if plan_status(content) in {"Ready", "Complete"}:
            sections = plan_sections(content, allow_placeholders=True)
            references, requirements = acceptance_tests(sections)
            names.update(name for _, name in references)
            tests = requirement_tests(root) if requirements else {}
            for requirement in requirements:
                names.update(name for _, _, name in tests.get(requirement, []))
    return names


def plan_skips(root: Path, base: str | None, groups: list[Group], since: float) -> bool:
    from reports import skipped_tests

    skipped = sorted(plan_tests(root, base) & skipped_tests(root, groups, since))
    if skipped:
        print("FAIL plan acceptance tests were skipped: " + ", ".join(skipped))
    return bool(skipped)


MAX_PR_COMMITS = 100
WARN_PR_COMMITS = 80
JOIN_COMMITS = (
    "Or join neighbour commits on the same base commit: `git diff <old head> <new head>` "
    "must then print nothing; push with `--force-with-lease` and never pull the old "
    "commits back in."
)


def commits_problem(count: int) -> str | None:
    """The refusal when a PR holds more commits than HE-PR-COMMITS allows."""
    if count <= MAX_PR_COMMITS:
        return None
    return (
        f"PR has {count} commits; HE-PR-COMMITS allows at most {MAX_PR_COMMITS}. "
        "Move the oldest finished commits to a PR of their own, merge it, then rebase "
        f"the rest. {JOIN_COMMITS}"
    )


def commit_note(root: Path) -> None:
    """Warn, never refuse, when the branch nears or passes the HE-PR-COMMITS cap."""
    point = default_branch_point(root)
    if point is None:
        return
    try:
        count = int(_git_output(root, "rev-list", "--count", f"{point}..HEAD"))
    except (subprocess.CalledProcessError, OSError, ValueError):
        return
    if count < WARN_PR_COMMITS:
        return
    way = (
        "Move the oldest finished commits to a PR of their own and merge it first. "
        + JOIN_COMMITS
        if count > MAX_PR_COMMITS
        else "Ship this work soon, then continue on a new branch."
    )
    print(
        f"Hard Eng warning: this branch has {count} commits; ship refuses a PR "
        f"with more than {MAX_PR_COMMITS} (HE-PR-COMMITS). {way}"
    )
