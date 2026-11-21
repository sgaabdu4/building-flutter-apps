"""Guard the mutations following verified PR delivery."""

import json
import os
import plistlib
import posixpath
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path, PurePosixPath
from xml.parsers.expat import ExpatError

from challenge import shipping_note
from gate_config import Group
from process_group import (
    STOP_SIGNAL,
    exit_when_stopped,
    passed_minutes,
    passed_note,
    policy_at,
    report_gate_edits,
)
from ship_record import SETTING_NAMES
from shipping import (
    PendingCheck,
    Shipment,
    ShippingError,
    ShippingPolicy,
    _compare,
    _pr_url,
    _pull,
    gh,
    git,
    load_policy,
    merge_settings,
    pushed_policy,
    verify,
)
from submodules import update_submodules
from tool_setup import TOOL_OWNER, temporary_root
from update import require_current

OBJECT_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
GITHUB_SSH_PREFIX = re.compile(r"(?:ssh://)?git@github\.com[:/]")

DERIVED_DATA = Path.home() / "Library/Developer/Xcode/DerivedData"


def rebase_step(base: str) -> str:
    return (
        f"GitHub cannot rebase this PR onto {base}, so nothing was merged. "
        f"Rebase the branch on origin/{base} and push it with --force-with-lease. "
        "If GitHub still cannot rebase it, cut its commits (HE-PR-COMMITS). "
        "Then wait for the checks and run ship again."
    )


def _stale_rebase_report(root: Path, repository: str, base: str, head: str) -> bool:
    """True when the branch is current with base and has no merge commit."""
    try:
        comparison = _compare(root, repository, base, head)
    except ShippingError:
        return False
    commits = comparison.get("commits")
    return (
        type(comparison.get("behind_by")) is int
        and comparison["behind_by"] == 0
        and isinstance(commits, list)
        and comparison.get("total_commits") == len(commits)
        and all(
            isinstance(commit, dict)
            and isinstance(commit.get("parents"), list)
            and len(commit["parents"]) <= 1
            for commit in commits
        )
    )


def rebase_problem(root: Path, repository: str, base: str, head: str) -> str | None:
    """Why a PR GitHub cannot rebase is refused; None when the repository allows another method."""
    try:
        allowed = merge_settings(root, repository, SETTING_NAMES)
    except ShippingError:
        return rebase_step(base)
    if allowed.get("rebaseMergeAllowed") is not False:
        if _stale_rebase_report(root, repository, base, head):
            return (
                f"GitHub reports that it cannot rebase this PR onto {base}, but the "
                f"branch is current with {base} and has no merge commit, so that "
                "report can be stale. Close the pull request and open it again, wait "
                "for the checks, then run ship again. If GitHub still cannot rebase "
                "it, cut its commits (HE-PR-COMMITS)."
            )
        return rebase_step(base)
    if any(allowed.get(name) is True for name in SETTING_NAMES[1:]):
        return None
    return (
        "This repository does not allow rebase merges, and Hard Eng merges by "
        "rebase only, so nothing was merged. Allow rebase merges in the "
        "repository settings, then run ship again."
    )


def remote_base(root: Path, branch: str | None) -> str | None:
    """The remote base revision, or None when the remote has no branches yet."""
    destination = git(root, "remote", "get-url", "--push", "origin").strip()
    if not git(root, "ls-remote", "--heads", destination).strip():
        return None
    reference = f"refs/heads/{branch}" if branch else "HEAD"
    advertised = git(root, "ls-remote", "--exit-code", "origin", reference).split()
    if (
        len(advertised) != 2
        or advertised[1] != reference
        or OBJECT_ID.fullmatch(advertised[0]) is None
    ):
        raise ValueError("Cannot resolve the current remote base")
    revision = advertised[0]
    git(root, "fetch", "--no-tags", "--no-write-fetch-head", "origin", revision)
    return revision


def stop_number(code: int) -> int | None:
    """The signal that ended a check, from its exit code or its wait status."""
    return next(
        (
            int(number)
            for number in (signal.SIGTERM, signal.SIGHUP)
            if code in {128 + number, -number}
        ),
        None,
    )


def stopped_line(number: int) -> str:
    return (
        f"Hard Eng: the pre-push check was stopped by {signal.Signals(number).name} "
        "before it finished. The stop is not a fault in the project, and neither is "
        "a gate that the stop ended. Fix any other failure printed above, then run "
        "the push again."
    )


def run_hard_eng(
    checkout: Path, arguments: list[str], environment: dict[str, str]
) -> int:
    """Run the snapshot's command in its own group so an interrupt stops every child first."""
    command = subprocess.Popen(
        [sys.executable, str(checkout / ".hooks/hard-eng.py"), *arguments],
        cwd=checkout,
        env=environment,
        start_new_session=True,
    )
    try:
        return command.wait()
    finally:
        if command.poll() is None:
            os.killpg(command.pid, signal.SIGTERM)
            with suppress(subprocess.TimeoutExpired):
                command.wait(timeout=10)
            with suppress(ProcessLookupError):
                os.killpg(command.pid, signal.SIGKILL)
            command.wait()


def snapshot_environment(root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    kept = {"GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT"}
    for name in git(root, "rev-parse", "--local-env-vars").splitlines():
        if name not in kept:
            environment.pop(name, None)
    return environment


LOCAL_FILES = {".claude/settings.local.json", "CLAUDE.local.md"}


def local_files(root: Path) -> Iterator[tuple[str, bool]]:
    """Ignored paths of the main checkout that a new worktree gets: (name, copied)."""
    ignored = git(
        root,
        "ls-files",
        "-z",
        "--others",
        "--ignored",
        "--exclude-standard",
        "--directory",
    )
    hooks = Path(
        git(root, "rev-parse", "--path-format=absolute", "--git-path", "hooks").strip()
    )
    for name in filter(None, ignored.split("\0")):
        source = root / name
        if name in LOCAL_FILES or (
            (Path(name).name.startswith(".env") or name.endswith(".dart"))
            and source.is_file()
        ):
            yield name, False
        elif source.resolve() == hooks.resolve():
            # Git ignores files inside a linked folder, not the link; Husky's folder holds only shims.
            yield name, True


DIRECTIVE = re.compile(r"^[ \t]*(?:import|export|part)\s+([^;]*);", re.MULTILINE)
QUOTED = re.compile(r"""['"]([^'"]+)['"]""")
PACKAGE_NAME = re.compile(r"""^name:\s*["']?([^\s"']+)""", re.MULTILINE)


type LocalizationOutput = tuple[PurePosixPath | None, str] | None


def written_by_generator(
    checkout: Path, name: str, mains: dict[Path, LocalizationOutput]
) -> bool:
    """A file that a tool of the project writes again; a link would let that tool write into the main checkout. `mains` holds each package's main gen-l10n file, read once."""
    path = PurePosixPath(name)
    if path.name.count(".") > 1:
        return True
    for folder in path.parents:
        package = checkout / folder
        if (package / "l10n.yaml").is_file():
            if package not in mains:
                mains[package] = main_localization_file(package)
            main = mains[package]
            if main is None:
                return False
            output, file = main
            relative = path.relative_to(folder)
            stem, _, extension = file.partition(".")
            # gen-l10n writes `<stem>_<language>.<extension>` only for each bare language code.
            return output in (None, relative.parent) and (
                relative.name == file
                or re.fullmatch(
                    rf"{re.escape(stem)}_[a-z]{{2,3}}\.{re.escape(extension)}",
                    relative.name,
                )
                is not None
            )
    return False


def main_localization_file(package: Path) -> LocalizationOutput:
    """The output folder and main file of gen-l10n; a python3 without PyYAML cannot read l10n.yaml, so the default name stands in any folder (None)."""
    from dart_boundaries import localization_file, localization_main

    try:
        main = localization_main(package)
    except ImportError:
        default = localization_file({})
        return None if default is None else (None, default.name)
    return None if main is None else (main.parent, main.name)


def dart_target(uri: str, folder: str, package: tuple[str, str] | None) -> str | None:
    """The project path that a Dart import names, or None for a library of another package."""
    if uri.startswith("package:"):
        name, _, rest = uri.removeprefix("package:").partition("/")
        if package is None or name != package[1]:
            return None
        return posixpath.normpath(posixpath.join(package[0], "lib", rest))
    if ":" in uri:
        return None
    return posixpath.normpath(posixpath.join(folder, uri))


def imported_files(checkout: Path, candidates: set[str]) -> set[str]:
    """The candidates that a Dart file of this commit imports, exports or takes as a part by path."""
    packages: dict[str, tuple[str, str] | None] = {}

    def package_of(folder: str) -> tuple[str, str] | None:
        if folder not in packages:
            pubspec = checkout / folder / "pubspec.yaml"
            match = (
                PACKAGE_NAME.search(pubspec.read_text()) if pubspec.is_file() else None
            )
            if match:
                packages[folder] = (folder, match.group(1))
            else:
                packages[folder] = (
                    None
                    if folder == "."
                    else package_of(posixpath.dirname(folder) or ".")
                )
        return packages[folder]

    found: set[str] = set()
    for name in filter(
        None, git(checkout, "ls-files", "-z", "--", "*.dart").split("\0")
    ):
        text = (checkout / name).read_text(errors="replace")
        folder = posixpath.dirname(name) or "."
        for directive in DIRECTIVE.findall(text):
            for uri in QUOTED.findall(directive):
                target = dart_target(uri, folder, package_of(folder))
                if target in candidates:
                    found.add(target)
    return found


def link_local_files(root: Path, checkout: Path) -> None:
    """Builds read ignored local .env* files and ignored Dart files that tracked code imports; link them and local settings without reading them."""
    wanted = list(local_files(root))
    dart = {
        name
        for name, _ in wanted
        if name.endswith(".dart") and not Path(name).name.startswith(".env")
    }
    mains: dict[Path, LocalizationOutput] = {}
    missing = {
        name
        for name in dart
        if not (checkout / name).exists()
        and not (checkout / name).is_symlink()
        and not written_by_generator(checkout, name, mains)
    }
    imported = imported_files(checkout, missing) if missing else set()
    for name, copied in wanted:
        if name in dart and name not in imported:
            continue
        source = root / name
        target = checkout / name
        if name in dart:
            target.parent.mkdir(parents=True, exist_ok=True)
        if not target.parent.is_dir() or target.exists() or target.is_symlink():
            continue
        if copied:
            shutil.copytree(source, target, symlinks=True)
        else:
            target.symlink_to(source)


COMPILED_HOOKS = "!! .hooks/__pycache__/"


def placed_by_hard_eng(root: Path, checkout: Path) -> set[str]:
    """Status lines for what link_local_files put in this worktree."""
    return {
        f"!! {name}"
        for name, copied in local_files(root)
        if copied or (checkout / name).resolve() == (root / name).resolve()
    }


def changed_copies(root: Path, checkout: Path, folder: str) -> list[str]:
    """Paths in a copied folder that the main checkout does not hold with the same content."""
    changed = []
    for path in sorted((checkout / folder).rglob("*")):
        name = path.relative_to(checkout)
        source = root / name
        if path.is_symlink() or source.is_symlink():
            same = (
                path.is_symlink()
                and source.is_symlink()
                and path.readlink() == source.readlink()
            )
        else:
            same = path.is_dir() or (
                source.is_file() and path.read_bytes() == source.read_bytes()
            )
        if not same:
            changed.append(str(name))
    return changed


def prepare_checkout(root: Path, checkout: Path, environment: dict[str, str]) -> None:
    link_local_files(root, checkout)
    update_submodules(checkout, root, environment)


def post_checkout(checkout: Path) -> int:
    """A new linked worktree gets the main checkout's local files, hooks and submodules."""
    environment = snapshot_environment(checkout)
    os.environ.clear()
    os.environ.update(environment)
    main = worktrees(checkout)[0]
    if "bare" not in main and Path(main["worktree"]).resolve() != checkout.resolve():
        prepare_checkout(Path(main["worktree"]), checkout, environment)
    return 0


@contextmanager
def snapshot(
    root: Path, revision: str, environment: dict[str, str], prepare: bool = True
) -> Generator[Path]:
    """A copy of a revision; without `prepare` it holds only tracked files, and no hook runs."""
    with tempfile.TemporaryDirectory(
        prefix="hard-eng-push-", dir=temporary_root()
    ) as temporary:
        checkout = Path(temporary) / "project"
        hooks = [] if prepare else ["-c", "core.hooksPath=/dev/null"]
        subprocess.run(
            ["git", *hooks, "worktree", "add", "--detach", str(checkout), revision],
            cwd=root,
            env=environment,
            check=True,
        )
        try:
            environment[TOOL_OWNER] = os.pathsep.join(
                [str(checkout.resolve()), str(root.resolve())]
            )
            if prepare:
                prepare_checkout(root, checkout, environment)
            yield checkout
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(checkout)],
                cwd=root,
                env=environment,
                check=True,
            )
            drop_derived_data(checkout)


def drop_derived_data(checkout: Path) -> None:
    """Xcode keys its build cache by project path, so a removed snapshot's cache is never reused."""
    roots = {checkout, checkout.resolve()}
    for info in DERIVED_DATA.glob("*/info.plist"):
        with suppress(OSError, ValueError, ExpatError):
            workspace = plistlib.loads(info.read_bytes()).get("WorkspacePath")
            if isinstance(workspace, str) and any(
                Path(workspace).is_relative_to(root) for root in roots
            ):
                shutil.rmtree(info.parent, ignore_errors=True)


def mutate(
    root: Path,
    base: str,
    seconds: float | None,
    in_place: bool,
    production: Callable[[Path, Group], set[Path]],
) -> int:
    """Mutate committed changes in a snapshot, since Dart mutates source in place."""
    exit_when_stopped()
    if in_place:
        from mutation import report

        return report(root, base, seconds, production)
    environment = snapshot_environment(root)
    revision = git(root, "rev-parse", "HEAD").strip()
    limit = [] if seconds is None else ["--seconds", str(seconds)]
    with snapshot(root, revision, environment) as checkout:
        if run_hard_eng(checkout, ["check", "--base", base], environment):
            print(
                "Mutation testing needs passing checks; fix the failures above first."
            )
            return 1
        arguments = ["mutation", "--base", base, "--in-place", *limit]
        return run_hard_eng(checkout, arguments, environment)


def push_base(
    root: Path, branch: str, target: str, remote: str, revision: str
) -> str | None:
    """Diff base for one pushed ref; None checks everything on a remote's first push."""
    if set(remote) != {"0"}:
        if target == f"refs/heads/{branch}":
            raise ValueError(
                "Push a task branch and use a PR; direct base updates are blocked"
            )
        if set(revision) == {"0"}:
            return remote
        # A rewritten branch (a merged update branch reused) owns only its own commits.
        with suppress(ShippingError):
            git(root, "merge-base", "--is-ancestor", remote, revision)
            return remote
    base = remote_base(root, branch)
    if base is None:
        print("The remote has no branches yet; checking everything for its first push.")
    elif target == f"refs/heads/{branch}":
        raise ValueError(
            "Push a task branch and use a PR; direct base updates are blocked"
        )
    else:
        # A new branch owns only what it added since leaving the base, not later base edits.
        with suppress(ShippingError):
            base = git(root, "merge-base", base, revision).strip()
    return base


def spared(root: Path, revision: str, base: str | None) -> bool:
    """Say so when a full check passed on this exact commit and base."""
    minutes = None if base is None else passed_minutes(root, revision, base)
    if minutes is not None:
        print(passed_note(minutes), flush=True)
    return minutes is not None


def runner_text(checkout: Path) -> str:
    """The script text of a pushed revision; an older revision has no runner module."""
    hooks = checkout / ".hooks"
    modules = (hooks / name for name in ("gate_runner.py", "ci_jobs.py"))
    return (hooks / "hard-eng.py").read_text() + "".join(
        module.read_text() for module in modules if module.is_file()
    )


def push_check(runner: str, base: str | None, quick: bool) -> list[str]:
    """The check for a push; a pass that stands in for the full check leaves a quick one."""
    if quick:
        return ["check", "--base", str(base), "--quick"]
    # A pushed revision older than these options runs its full check.
    narrow = [
        option
        for option in ("--without-dependents", "--related-tests")
        if option in runner
    ]
    return ["check", *(["--base", base, *narrow] if base else [])]


def warn_ssh(root: Path) -> None:
    with suppress(ShippingError):
        if GITHUB_SSH_PREFIX.match(git(root, "remote", "get-url", "--push", "origin")):
            print(
                "Hard Eng: origin pushes to GitHub over SSH, which can drop the idle "
                "connection while these checks run (push exit 141 after they pass). "
                "Switch to HTTPS: git remote set-url origin https://github.com/<owner>/<repo>.git",
                flush=True,
            )


def base_leaves_checks_to_ci(root: Path, policy: ShippingPolicy) -> bool:
    """True only when the remote base tip's own policy also says "ci" for this base; the pushed commit cannot switch itself on."""
    if policy["pre_push_checks"] != "ci":
        return False
    try:
        tip = remote_base(root, policy["base"])
    except (ShippingError, ValueError):
        return False
    held = None if tip is None else policy_at(root, tip)
    return (
        held is not None
        and held["pre_push_checks"] == "ci"
        and held["base"] == policy["base"]
    )


def push_checks(
    checkout: Path,
    environment: dict[str, str],
    base: str | None,
    policy: ShippingPolicy,
    ci: bool,
    passed: bool,
) -> int:
    """The checks of one pushed revision; CI runs the full check when the base leaves it there, so only the commit secret scan stays."""
    if ci:
        scan = ["check", "--commit-secrets", *(["--base", base] if base else [])]
        if returncode := run_hard_eng(checkout, scan, environment):
            return returncode
        print(
            'Hard Eng: the full check is left to CI (shipping pre_push_checks "ci"); '
            "the pushed commits passed the secret scan.",
            flush=True,
        )
        # Mutation runs on installed dependencies, which the quick check installs.
        if base is None or not policy["pre_push_mutation_seconds"]:
            return 0
        check = push_check("", base, True)
    else:
        check = push_check(runner_text(checkout), base, passed)
    if returncode := run_hard_eng(checkout, check, environment):
        return returncode
    return int(report_gate_edits(checkout, environment))


def package_in_submodule(root: Path, revision: str) -> bool:
    """A package of the pushed gates file that sits in a submodule needs its files in the copy."""
    try:
        config = json.loads(git(root, "show", f"{revision}:hard-eng.gates.json"))
        listing = git(root, "ls-tree", "-r", "-z", revision)
    except (ShippingError, ValueError):
        return True
    modules = [
        Path(entry.partition("\t")[2])
        for entry in listing.split("\0")
        if entry.startswith("160000 ")
    ]
    return any(
        ".." in Path(package["path"]).parts
        or Path(os.path.normpath(package["path"])).is_relative_to(module)
        for package in config.get("packages", [])
        for module in modules
    )


def pre_push(root: Path) -> int:
    exit_when_stopped()
    try:
        return check_pushes(root)
    except SystemExit as stop:
        if STOP_SIGNAL and stop.code == 128 + STOP_SIGNAL[0]:
            print(stopped_line(STOP_SIGNAL[0]), flush=True)
        raise


def check_pushes(root: Path) -> int:
    started, mutating = time.monotonic(), 0.0
    for line in sys.stdin:
        fields = line.split()
        if len(fields) != 4:
            raise ValueError("Invalid pre-push input")
        revision = fields[1]
        policy = (
            load_policy(root)
            if set(revision) == {"0"}
            else pushed_policy(root, revision)
        )
        assert policy is not None
        base = push_base(root, policy["base"], fields[2], fields[3], revision)
        if set(revision) == {"0"}:
            continue
        passed = spared(root, revision, base)
        if passed and not policy["pre_push_mutation_seconds"]:
            continue
        warn_ssh(root)
        environment = snapshot_environment(root)
        ci = base_leaves_checks_to_ci(root, policy)
        scan_only = (
            ci
            and (base is None or not policy["pre_push_mutation_seconds"])
            and not package_in_submodule(root, revision)
        )
        with snapshot(root, revision, environment, not scan_only) as checkout:
            if returncode := push_checks(
                checkout, environment, base, policy, ci, passed
            ):
                if (number := stop_number(returncode)) is not None:
                    print(stopped_line(number), flush=True)
                return returncode
            if base is not None and (limit := policy["pre_push_mutation_seconds"]):
                began = time.monotonic()
                arguments = ["mutation", "--base", base, "--in-place"]
                run_hard_eng(
                    checkout, [*arguments, "--seconds", str(limit)], environment
                )
                mutating += time.monotonic() - began
        elapsed = time.monotonic() - started - mutating
        if elapsed > policy["pre_push_seconds"]:
            print(
                f"Hard Eng warning: pre-push checks passed in {elapsed:.0f}s, over the "
                f"{policy['pre_push_seconds']:.0f}s pre_push_seconds budget; the push "
                "continues. The elapsed time of each gate above shows what to speed up.",
                flush=True,
            )
    print(f"Pre-push verification: {time.monotonic() - started:.2f}s")
    return 0


def worktrees(root: Path) -> list[dict[str, str]]:
    records = git(root, "worktree", "list", "--porcelain", "-z")
    return [
        {
            key: value
            for key, _, value in (
                field.partition(" ") for field in record.split("\0") if field
            )
        }
        for record in records.split("\0\0")
        if record
    ]


def common_directory(root: Path) -> Path:
    return Path(
        git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    ).resolve()


def kept_groups(kept: list[str]) -> list[str]:
    """Each kept top-level path once; Git lists an ignored folder as one entry, so a file count would mislead."""
    return list(dict.fromkeys("".join(name.partition("/")[:2]) for name in kept))


def unchanged_checkout(shipment: Shipment) -> None:
    target = shipment.root.resolve()
    index_lock = Path(git(target, "rev-parse", "--git-path", "index.lock").strip())
    if (target / index_lock).exists():
        raise ValueError("Cleanup preserves a task with an active Git index lock")
    main = Path(worktrees(target)[0]["worktree"])
    own = placed_by_hard_eng(main, target)
    status = git(
        target,
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--ignored=matching",
        "--ignore-submodules=none",
    )
    folders = tuple(line for line in own if line.endswith("/"))
    kept = [
        line[3:]
        for line in status.splitlines()
        if line not in own | {COMPILED_HOOKS} and not line.startswith(folders)
    ]
    for folder in folders:
        kept += changed_copies(main, target, folder[3:])
    if kept:
        raise ValueError(
            "Cleanup preserves modified, untracked or ignored work: "
            + ", ".join(kept_groups(kept))
            + ". In that worktree, `git status --ignored --untracked-files=all` lists "
            "each file under those paths. Delete the generated files that nobody "
            "needs and move the others out of the worktree. Copy an edited tracked file "
            "out, then undo its edit. Then run cleanup again."
        )
    if git(target, "rev-parse", "HEAD").strip() != shipment.head_sha:
        raise ValueError("Cleanup preserves commits added after the verified PR")


def cleanup_guard(coordinator: Path, shipment: Shipment) -> None:
    target = shipment.root.resolve()
    if common_directory(coordinator) != common_directory(target):
        raise ValueError("Cleanup target is not in the coordinator's repository")
    if Path.cwd().resolve().is_relative_to(target):
        raise ValueError("Run cleanup outside the task's current worktree")
    records = worktrees(coordinator)
    if not records or Path(records[0]["worktree"]).resolve() == target:
        raise ValueError("The main worktree must be preserved")
    matches = [
        record for record in records if Path(record["worktree"]).resolve() == target
    ]
    if len(matches) != 1 or "locked" in matches[0] or "prunable" in matches[0]:
        raise ValueError("Cleanup needs one available, unlocked task worktree")
    branch = f"refs/heads/{shipment.branch}"
    if matches[0].get("branch") != branch:
        raise ValueError("Cleanup target no longer owns the verified task branch")
    if sum(record.get("branch") == branch for record in records) != 1:
        raise ValueError("Another worktree uses the task branch")
    unchanged_checkout(shipment)
    if any(
        not line.startswith("-")
        for line in git(target, "submodule", "status", "--recursive").splitlines()
    ):
        raise ValueError(
            "Cleanup preserves initialized submodules; use the repository's procedure"
        )
    if shipment.branch == shipment.base or not shipment.merged_sha:
        raise ValueError("Cleanup requires a merged task branch, never the base")


def remote_branch(root: Path, remote: str, branch: str) -> str | None:
    lines = git(root, "ls-remote", "--heads", remote, f"refs/heads/{branch}")
    rows = [line.split() for line in lines.splitlines() if line.strip()]
    if not rows:
        return None
    if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != f"refs/heads/{branch}":
        raise ValueError("Task remote branch is ambiguous")
    return rows[0][0]


def cleanup(coordinator: Path, shipment: Shipment) -> None:
    cleanup_guard(coordinator, shipment)
    if (
        git(shipment.root, "remote", "get-url", shipment.remote).strip()
        != shipment.remote_url
    ):
        raise ValueError(
            "Cleanup preserves a task whose remote changed after verification"
        )
    push_urls = git(
        shipment.root, "remote", "get-url", "--push", "--all", shipment.remote
    ).splitlines()
    if push_urls != [shipment.remote_url]:
        raise ValueError("Cleanup preserves a task with a different push endpoint")
    remote_head = remote_branch(shipment.root, shipment.remote_url, shipment.branch)
    if remote_head not in (None, shipment.head_sha):
        raise ValueError("Cleanup preserves a remote branch with additional work")
    if remote_head is not None:
        reference = f"refs/heads/{shipment.branch}"
        git(
            shipment.root,
            "push",
            f"--force-with-lease={reference}:{shipment.head_sha}",
            shipment.remote_url,
            f":{reference}",
        )
        if (
            remote_branch(shipment.root, shipment.remote_url, shipment.branch)
            is not None
        ):
            raise ValueError("Remote branch still exists; local worktree retained")
        print(f"Removed remote task branch {shipment.branch}", flush=True)
    tracking = f"refs/remotes/{shipment.remote}/{shipment.branch}"
    references = git(coordinator, "for-each-ref", "--format=%(refname)", tracking)
    if tracking in references.splitlines():
        git(coordinator, "update-ref", "-d", tracking, shipment.head_sha)
    cleanup_guard(coordinator, shipment)
    # Git refuses any worktree with a submodule gitlink; the guard proved it clean.
    git(coordinator, "worktree", "remove", "--force", str(shipment.root))
    print(f"Removed task worktree {shipment.root}", flush=True)
    git(
        coordinator,
        "update-ref",
        "-d",
        f"refs/heads/{shipment.branch}",
        shipment.head_sha,
    )
    print(f"Removed local task branch {shipment.branch}", flush=True)


def merge(target: Path, plan: Path | None, shipment: Shipment, method: str) -> Shipment:
    """Merge the verified head, then prove the merged revision."""
    if shipment.delivery_target == "PR":
        raise ValueError("The plan authorizes PR delivery, not merging")
    try:
        gh(
            target,
            "pr",
            "merge",
            shipment.pr_url,
            f"--{method}",
            *(["--admin"] if shipment.review_bypass else []),
            "--match-head-commit",
            shipment.head_sha,
        )
    except ShippingError as failure:
        if _pull(target, *_pr_url(shipment.pr_url)).rebaseable is False and (
            problem := rebase_problem(
                target, shipment.repository, shipment.base, shipment.head_sha
            )
        ):
            raise ShippingError(problem) from failure
        raise
    try:
        return verify(target, plan, shipment.pr_url, "delivered")
    except PendingCheck as error:
        raise ShippingError(
            f"Merged; base-branch CI has not finished ({error}). Run ship "
            "--stage delivered once it completes; do not retry the merge."
        ) from error
    except ShippingError as error:
        raise ShippingError(
            "Merge command succeeded; post-merge delivery verification is pending "
            f"or failed: {error}. Inspect the PR before retrying and do not claim "
            "that the merge was undone."
        ) from error


def require_stage_options(
    stage: str, worktree: str | None, merge_method: str | None
) -> None:
    if stage not in {"ready", "merge", "delivered", "cleanup"}:
        raise ValueError("Unknown shipping stage")
    if stage == "merge" and merge_method != "rebase":
        raise ValueError(
            "Hard Eng merges by rebase only; squash and merge commits are refused"
        )
    if stage == "cleanup" and not worktree:
        raise ValueError(
            "Cleanup needs --worktree <path of the task's worktree>; "
            "run it from the repository's main checkout."
        )


def run(
    coordinator: Path,
    plan: str | None,
    pr_url: str,
    stage: str,
    worktree: str | None,
    merge_method: str | None,
) -> int:
    require_stage_options(stage, worktree, merge_method)
    target = Path(worktree).resolve() if worktree else coordinator.resolve()
    if common_directory(coordinator) != common_directory(target):
        raise ValueError("Shipping target belongs to a different repository")
    plan_path = (target / plan).resolve() if plan else None
    if plan_path is not None and not plan_path.is_relative_to(target):
        raise ValueError("Use the selected task's plan inside its worktree")
    proof_stage = "ready" if stage in {"ready", "merge"} else "delivered"
    if stage in {"ready", "merge"}:
        require_current(target)
    shipment = verify(target, plan_path, pr_url, proof_stage)
    if stage in {"ready", "merge"} and (
        note := shipping_note(shipment.root, shipment.head_sha)
    ):
        print(note)
    if shipment.rule_note:
        print(shipment.rule_note)
    bypassed = shipment.review_bypass
    if stage == "merge":
        shipment = merge(target, plan_path, shipment, shipment.method)
    if stage == "cleanup":
        cleanup(coordinator, shipment)
    revision = shipment.merged_sha or shipment.head_sha
    if bypassed:
        print(
            "Review bypass: only the author can give the required review, so the "
            "merge uses admin rights once every other requirement passes."
        )
    print(f"PASS ship {stage}: {pr_url} at {revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(post_checkout(Path(sys.argv[1])))
