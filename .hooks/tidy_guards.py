"""The checks the tidy runs before it removes anything, and the commands they use."""

import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from contextlib import suppress
from pathlib import Path


def idle(stamp: float) -> bool:
    """Nothing touched the thing for a day."""
    return time.time() - stamp > 24 * 3600


CARGO_SIGNATURE = "Signature: 8a477f597d28d172789f06886806bc55"
REFLOG_SELECTOR = re.compile(r"@\{(\d+)\}$")
PAUSED_BRANCH_FILES = (
    "rebase-merge/head-name",
    "rebase-apply/head-name",
    "BISECT_START",
)


class TidyStop(Exception):
    pass


ITEM_ERRORS = (TidyStop, ValueError, OSError, subprocess.SubprocessError)


def note(text: str) -> None:
    print(f"Tidy {text}", file=sys.stderr, flush=True)


def tidy_run(
    cwd: Path,
    limit: float,
    *command: str,
    env: dict[str, str] | None = None,
    lines: str | None = None,
) -> subprocess.CompletedProcess[str]:
    if command[0] == "git":
        env = {
            **(os.environ if env is None else env),
            "GIT_NO_REPLACE_OBJECTS": "1",
        }
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=limit,
            check=False,
            input=lines,
            stdin=None if lines is not None else subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise TidyStop(f"`{' '.join(command[:3])}` did not run: {error}") from error


def tidy_git(cwd: Path, *arguments: str) -> str:
    done = tidy_run(cwd, 120, "git", *arguments)
    if done.returncode:
        raise TidyStop(f"`git {' '.join(arguments[:3])}` exited {done.returncode}")
    return done.stdout


def reflog_time(cwd: Path, ref: str) -> float | None:
    """When the ref last moved; None when it has no log."""
    selector = tidy_git(
        cwd, "log", "-g", "-1", "--date=unix", "--format=%gd", ref
    ).strip()
    found = REFLOG_SELECTOR.search(selector)
    return float(found[1]) if found else None


def foreign_user(process: Path) -> bool:
    """A person's account other than ours owns the process; system accounts cannot sit in a worktree."""
    try:
        owner = process.stat().st_uid
    except OSError:
        return False
    return owner != os.getuid() and owner >= 1000


def process_links(process: Path) -> set[str] | None:
    """Where one process stands; None when a foreign user's process cannot be read."""
    found: set[str] = set()
    try:
        names = [process / "cwd"]
        with suppress(FileNotFoundError):
            names += [Path(entry.path) for entry in os.scandir(process / "fd")]
    except PermissionError:
        return None if foreign_user(process) else found
    for link in names:
        try:
            found.add(os.readlink(link))
        except PermissionError:
            if foreign_user(process):
                return None
        except OSError:
            continue
    return found


def proc_paths(proc: Path = Path("/proc")) -> set[str] | None:
    found: set[str] = set()
    for process in proc.iterdir():
        if process.name.isdigit() and int(process.name) != os.getpid():
            links = process_links(process)
            if links is None:
                return None
            found |= links
    return found


def open_paths() -> set[str] | None:
    """Every path a process has as its folder or open file; None when the host cannot say."""
    if os.name != "posix":
        return None
    if Path("/proc/self/cwd").exists():
        return proc_paths()
    if shutil.which("lsof") is None:
        return None
    done = tidy_run(Path("/"), 60, "lsof", "-n", "-P", "-w", "-F", "pn")
    if done.returncode not in {0, 1}:
        raise TidyStop(f"`lsof` exited {done.returncode}")
    names: set[str] = set()
    mine = False
    for line in done.stdout.splitlines():
        if line.startswith("p"):
            mine = line[1:] == str(os.getpid())
        elif line.startswith("n/") and not mine:
            names.add(line[1:])
    return names or None


def fold(path: str | Path) -> str:
    """A path as text that ignores letter case and Unicode form, as macOS volumes do."""
    return unicodedata.normalize("NFC", str(path)).casefold()


def same_place(first: Path, second: Path) -> bool:
    return fold(first) == fold(second)


def inside(path: Path, names: set[str]) -> bool:
    prefixes = {fold(path), fold(path.resolve())}
    return any(
        folded == prefix or folded.startswith(prefix + os.sep)
        for folded in map(fold, names)
        for prefix in prefixes
    )


def foreign_folder(worktree: Path, target: Path) -> bool:
    """The folder is a link, a mount point or on another device than its worktree, so removing it reaches something else."""
    return (
        target.is_symlink()
        or os.path.ismount(target)
        or target.stat().st_dev != worktree.stat().st_dev
    )


def holds_repository(folder: Path) -> bool:
    """A nested repository, with a `.git` entry or bare, is below the folder; the walk stops at the first one, follows no link, and counts an unreadable folder as one."""
    pending = [folder]
    try:
        while pending:
            with os.scandir(pending.pop()) as entries:
                found = list(entries)
            names = {entry.name for entry in found}
            if ".git" in names or {"HEAD", "objects", "refs"} <= names:
                return True
            pending += [
                Path(entry.path)
                for entry in found
                if entry.is_dir(follow_symlinks=False)
            ]
    except OSError:
        return True
    return False


def cargo_target(worktree: Path) -> bool:
    tag = worktree / "target/CACHEDIR.TAG"
    with suppress(OSError):
        return tag.read_text().startswith(CARGO_SIGNATURE)
    return False


def quiet_folders(target: Path) -> bool:
    """No folder in the top two levels of a build folder changed within a day."""
    try:
        level, seen = [target], [target]
        for _ in range(2):
            level = [
                Path(entry.path)
                for folder in level
                for entry in os.scandir(folder)
                if entry.is_dir(follow_symlinks=False)
            ]
            seen += level
        return all(idle(folder.stat().st_mtime) for folder in seen)
    except OSError:
        return False


def idle_worktree(path: Path) -> bool:
    """The HEAD log, the top level and every tracked file, submodules too, are a day old; status, fetch and this tidy touch none of them."""
    logged = reflog_time(path, "HEAD")
    listing = tidy_git(path, "ls-files", "-z", "-v", "--recurse-submodules")
    entries = [(r[0], path / r[2:]) for r in listing.split("\0") if r]
    entries += [("H", path / e.name) for e in os.scandir(path) if e.name != ".git"]
    times = []
    for tag, name in entries:
        try:
            times.append(os.lstat(name).st_mtime)
        except FileNotFoundError:
            if tag not in "Ss":
                return False
    return logged is not None and idle(max(times, default=0)) and idle(logged)


OBJECT_ID = re.compile(rb"[0-9a-f]{40}|[0-9a-f]{64}")


def logged_ids(log: Path) -> set[str]:
    """Both commit ids of every line of a log file; a line ends only at a newline, and a field that is no full lowercase id stops the check."""
    found: set[str] = set()
    with suppress(FileNotFoundError):
        for line in log.read_bytes().split(b"\n"):
            if line:
                for field in line.split(b" ", 2)[:2]:
                    if OBJECT_ID.fullmatch(field) is None:
                        raise TidyStop(
                            f"{log.name} has a line that starts with no commit ids"
                        )
                    found.add(field.decode())
    return found


def paused_branches(common: Path) -> set[str]:
    """Branches that a rebase or bisect in any worktree will return to, though HEAD is detached now."""
    folders = [common, *sorted((common / "worktrees").glob("*"))]
    found: set[str] = set()
    for folder in folders:
        for name in PAUSED_BRANCH_FILES:
            with suppress(FileNotFoundError, NotADirectoryError):
                found.add(
                    (folder / name).read_text().strip().removeprefix("refs/heads/")
                )
        with suppress(FileNotFoundError, NotADirectoryError):
            for line in (folder / "rebase-merge/update-refs").read_text().splitlines():
                if line.startswith("refs/heads/"):
                    found.add(line.removeprefix("refs/heads/"))
    return found


EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
RESCUE = "refs/hard-eng/tidy"
RESCUE_DAYS = 30


def rescue_stamp(now: float) -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))


def save_commits(root: Path, commits: list[str], now: float) -> None:
    """One ref for each commit that a removal would leave unnamed, written together or not at all."""
    stamp = rescue_stamp(now)
    lines = "".join(
        f"update {RESCUE}/{stamp}/{commit} {commit}\n" for commit in commits
    )
    if lines:
        done = tidy_run(root, 120, "git", "update-ref", "--stdin", lines=lines)
        if done.returncode:
            raise TidyStop("the rescue refs could not be written")


def expire_rescues(root: Path, now: float) -> None:
    """Rescue refs go after the same days as the removal record."""
    listing = tidy_git(root, "for-each-ref", "--format=%(refname)", RESCUE)
    limit = rescue_stamp(now - RESCUE_DAYS * 86400)
    old = [
        name
        for name in listing.split()
        if name.removeprefix(f"{RESCUE}/").partition("/")[0] < limit
    ]
    if old:
        done = tidy_run(
            root,
            120,
            "git",
            "update-ref",
            "--stdin",
            lines="".join(f"delete {n}\n" for n in old),
        )
        if done.returncode:
            raise TidyStop("old rescue refs could not be removed")


def scratch_git(
    scratch: Path, *arguments: str, repository: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Every Git command of the scratch repository: nothing from the user's environment, settings, templates or attributes."""
    env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(scratch),
        "TMPDIR": str(scratch),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_ATTR_NOSYSTEM": "1",
    }
    if repository is not None:
        env["GIT_DIR"] = str(repository)
    return tidy_run(
        scratch,
        120,
        "git",
        f"--attr-source={EMPTY_TREE}",
        "-c",
        f"core.attributesFile={os.devnull}",
        *arguments,
        env=env,
    )
