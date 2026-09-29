"""Run the scaffold update detached from agent startup, one per repository."""

import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Generator, Iterable
from contextlib import contextmanager, suppress
from functools import partial
from pathlib import Path
from typing import TextIO

RESULT_FILE = ".hard-eng/update-result.txt"
LOG_FILE = ".hard-eng/update.log"
OWNER = re.compile(r"hard-eng-update (\d+)")


class UpdateRunning(ValueError):
    pass


def update_blocker(root: Path) -> str | None:
    from update import SOURCE_FILE

    marker = root / SOURCE_FILE
    if not marker.exists():
        return "Automatic update unavailable: this checkout has no installed source revision."
    metadata = json.loads(marker.read_text())
    if not isinstance(metadata, dict):
        raise TypeError("Installed source metadata must be an object")
    previous = metadata.get("revision")
    if not isinstance(previous, str) or not re.fullmatch(r"[0-9a-f]{40}", previous):
        return "Installed from an uncommitted working copy; publish a verified source revision before automatic updates."
    return None


def lock_file(root: Path) -> Path:
    """One lock per repository, because every worktree shares its registered worktrees."""
    common = subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=root,
        text=True,
    )
    return Path(common.strip()) / "hard-eng-update.lock"


def update_running(root: Path) -> bool:
    lock = lock_file(root)
    if not lock.is_file():
        return False
    with lock.open() as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def stale_message(root: Path, revision: str) -> str:
    if update_running(root):
        return (
            f"Hard Eng update to newer verified revision {revision} is still running in the "
            f"background ({LOG_FILE}). Wait for it to finish without starting another update, "
            "then reverify before shipping or claiming completion."
        )
    return (
        f"Hard Eng freshness check found newer verified revision {revision}. "
        "Use the supported updater, preserve local edits, then reverify before shipping or claiming completion."
    )


def current_head(root: Path) -> str:
    found = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return found.stdout.strip()


def landed_commit(root: Path, head: str, message: str) -> tuple[str, str] | None:
    """The updater's own commit since head, found by its message because the agent may commit too."""
    span = head + "..HEAD" if head else "-1"
    found = subprocess.run(
        ["git", "log", "--format=%H %P%x1f%s", span],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    for line in found.stdout.splitlines():
        identities, _, subject = line.partition("\x1f")
        commit, *parents = identities.split()
        if subject == message:
            return commit, parents[0] if parents else ""
    return None


def committed_matches(root: Path, commit: str, expected: dict[str, str | None]) -> bool:
    """Whether the commit holds exactly the planned files and link targets, so no other edit rode along."""
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "--name-only", commit, "--", *expected],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    planned = {name for name, content in expected.items() if content is not None}
    if set(filter(None, listing.split("\0"))) - planned:
        return False
    request = "".join(f"{commit}:{name}\n" for name in expected).encode()
    output = subprocess.run(
        ["git", "cat-file", "--batch"],
        input=request,
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout
    for content in expected.values():
        header, _, output = output.partition(b"\n")
        fields = header.split()
        found = None
        if len(fields) == 3:
            size = int(fields[2])
            if fields[1] == b"blob":
                found = output[:size]
            output = output[size + 1 :]
        if found != (None if content is None else content.encode()):
            return False
    return True


def rebase_sessions(
    root: Path, head: str, message: str, expected: dict[str, str | None] | None = None
) -> bool:
    """Sessions based on the update commit's parent must not count that commit as their work."""
    landed = landed_commit(root, head, message)
    if landed is None:
        return False
    commit, parent = landed
    if expected is not None and not committed_matches(root, commit, expected):
        return True
    for state in (root / ".hard-eng/sessions").glob("*.json"):
        try:
            saved = json.loads(state.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(saved, dict) and parent and saved.get("base") == parent:
            state.write_text(json.dumps({**saved, "base": commit}))
    return True


def written(root: Path, name: str, content: str | None, link: bool) -> bool:
    """Whether a path still holds what the updater wrote, so rollback cannot erase a later edit."""
    target = root / name
    if content is None:
        return not target.exists() and not target.is_symlink()
    if link:
        return target.is_symlink() and str(target.readlink()) == content
    return (
        target.is_file()
        and not target.is_symlink()
        and target.read_text(errors="replace") == content
    )


def snapshot(root: Path, names: Iterable[str]) -> dict[str, bytes | None]:
    return {
        name: (root / name).read_bytes() if (root / name).exists() else None
        for name in names
    }


def holds(root: Path, name: str, content: bytes | None) -> bool:
    return snapshot(root, [name])[name] == content


def link_state(root: Path, names: Iterable[str]) -> dict[str, str | None]:
    return {
        name: str((root / name).readlink()) if (root / name).is_symlink() else None
        for name in names
    }


def prune(directory: Path) -> None:
    """Remove the empty directories left beneath a path, deepest first."""
    for path in [*sorted(directory.rglob("*"), reverse=True), directory]:
        with suppress(OSError):
            path.rmdir()


def roll_back(
    root: Path,
    changes: dict[str, str | None],
    links: dict[str, str | None],
    before: dict[str, bytes | None],
    before_links: dict[str, str | None],
    applied: list[str],
) -> list[str]:
    """Restore each applied path only while it still holds the updater's write, checked just before."""
    from update import replace_file

    kept = []
    for name in applied:
        if name not in changes:
            continue
        content = before[name]
        unchanged = partial(written, root, name, changes[name], False)
        if content is None and unchanged():
            (root / name).unlink(missing_ok=True)
        elif content is None or not replace_file(root / name, content, unchanged):
            kept.append(name)
    for name in applied:
        if name not in links:
            continue
        if links[name] is None and not (root / name).is_symlink():
            prune(root / name)
        if not written(root, name, links[name], True):
            kept.append(name)
            continue
        (root / name).unlink(missing_ok=True)
        if (target := before_links[name]) is not None:
            (root / name).symlink_to(target, target_is_directory=True)
    return kept


def index_entries(root: Path, names: list[str]) -> dict[str, str]:
    listing = subprocess.check_output(
        ["git", "ls-files", "--stage", "-z", "--", *names], cwd=root, text=True
    )
    return {
        path: entry
        for entry, _, path in (
            line.partition("\t") for line in listing.split("\0") if line
        )
    }


def unstage_own(
    root: Path, names: list[str], staging: tuple[dict[str, str], dict[str, str]]
) -> None:
    """Restore only index entries the updater changed and that still hold its staging."""
    before, staged = staging
    current = index_entries(root, names)
    own = [
        path
        for path in {*before, *staged, *current}
        if current.get(path) == staged.get(path) != before.get(path)
    ]
    if restored := "".join(
        f"{before[path]}\t{path}\0" for path in own if path in before
    ):
        subprocess.run(
            ["git", "update-index", "-z", "--index-info"],
            input=restored,
            cwd=root,
            text=True,
            check=True,
        )
    if added := [path for path in own if path not in before]:
        subprocess.run(
            ["git", "update-index", "--force-remove", "--", *added],
            cwd=root,
            check=True,
        )


@contextmanager
def deferred_sigterm() -> Generator[None]:
    """Hold SIGTERM, whichever thread receives it, and keep it from child git commands until the block ends."""
    received: list[int] = []
    previous = signal.signal(
        signal.SIGTERM, lambda signum, _frame: received.append(signum)
    )
    mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        signal.signal(signal.SIGTERM, previous)
        if received:
            signal.raise_signal(signal.SIGTERM)


def relink_verified(
    root: Path,
    links: dict[str, str | None],
    before_links: dict[str, str | None],
    applied: list[str],
) -> None:
    """Replace each link only while it still holds its verified state, checked just before."""
    from update import write_links

    for name, target in links.items():
        if link_state(root, [name])[name] != before_links[name]:
            raise ValueError(f"{name} changed while the update was being applied")
        applied.append(name)
        write_links(root, {name: target})


def write_verified(
    root: Path,
    changes: dict[str, str | None],
    before: dict[str, bytes | None],
    relinked: tuple[str, ...],
    applied: list[str],
) -> None:
    """Write each file only while it still holds its verified content, checked just before."""
    from update import replace_file, write_changes

    for name, content in changes.items():
        verified = partial(holds, root, name, before[name])
        applied.append(name)
        if name.startswith(relinked) or (content is None and verified()):
            write_changes(root, {name: content})
        elif content is None or not replace_file(
            root / name, content.encode(), verified
        ):
            applied.pop()
            raise ValueError(f"{name} changed while the update was being applied")


def git_commit(
    root: Path, names: list[str], changes: dict[str, str | None], message: str
) -> None:
    result = subprocess.run(
        [
            "git",
            "commit",
            "--only",
            "-m",
            message,
            "--",
            *(
                name
                for name in names
                if not any(other.startswith(f"{name}/") for other in changes)
            ),
        ],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
        timeout=3500,
    )
    sys.stderr.write(result.stdout)
    if result.returncode != 0:
        # SessionStart stderr never reaches the agent, so the error carries the reason.
        tail = " | ".join(result.stdout.strip().splitlines()[-5:])
        raise subprocess.SubprocessError(
            f"git commit exited {result.returncode}: {tail}".removesuffix(": ")
        )


def unwritten(
    root: Path,
    changes: dict[str, str | None],
    links: dict[str, str | None],
    applied: list[str],
) -> list[str]:
    """Applied paths that no longer hold the updater's write; a retired link's planned folder is checked by its files."""
    return [
        name
        for name in applied
        if (name in changes and not written(root, name, changes[name], False))
        or (
            name in links
            and not any(other.startswith(f"{name}/") for other in changes)
            and not written(root, name, links[name], True)
        )
    ]


def commit_update(
    root: Path,
    changes: dict[str, str | None],
    links: dict[str, str | None],
    revision: str,
    before: dict[str, bytes | None],
) -> None:
    names = sorted({*changes, *links})
    before_links = link_state(root, links)
    retired = tuple(
        f"{name}/"
        for name, target in links.items()
        if target is None and before_links[name] is not None
    )
    # Files beneath a retired link must still be absent when the update writes them.
    expected = {
        name: None if name.startswith(retired) else content
        for name, content in before.items()
    }
    head = current_head(root)
    message = f"Update Hard Eng to {revision}"
    staging: tuple[dict[str, str], dict[str, str]] | None = None
    applied: list[str] = []
    try:
        relink_verified(root, links, before_links, applied)
        # Paths under a link the update repointed no longer show their verified content.
        relinked = tuple(f"{name}/" for name, target in links.items() if target)
        write_verified(root, changes, expected, relinked, applied)
        with deferred_sigterm():
            index = index_entries(root, names)
            subprocess.run(
                ["git", "add", "--force", "--", *names], cwd=root, check=True
            )
            staging = (index, index_entries(root, names))
        if moved := unwritten(root, changes, links, applied):
            raise ValueError(
                f"{', '.join(moved)} changed while the update was being applied"
            )
        git_commit(root, names, changes, message)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        if rebase_sessions(root, head, message, {**changes, **links}):
            raise
        kept = roll_back(root, changes, links, expected, before_links, applied)
        if staging is not None:
            unstage_own(root, names, staging)
        if kept:
            raise subprocess.SubprocessError(
                f"{error}; kept later edits to {', '.join(kept)} instead of rolling them back"
            ) from error
        raise
    rebase_sessions(root, head, message, {**changes, **links})


def alive(process: int) -> bool:
    try:
        os.kill(process, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def remove_stale_candidates(root: Path) -> None:
    """Remove candidates whose owning update has exited; the caller holds the lock."""
    listing = subprocess.check_output(
        ["git", "worktree", "list", "--porcelain"], cwd=root, text=True
    )
    for block in listing.split("\n\n"):
        fields = {
            key: value
            for key, _, value in (line.partition(" ") for line in block.splitlines())
        }
        path = Path(fields.get("worktree", ""))
        owner = OWNER.fullmatch(fields.get("locked", ""))
        if (
            path.name != "candidate"
            or not path.parent.name.startswith("hard-eng-update-")
            or owner is None
            or alive(int(owner[1]))
        ):
            continue
        if not path.exists():
            subprocess.run(
                ["git", "worktree", "unlock", str(path)], cwd=root, check=True
            )
        elif not subprocess.run(
            ["git", "worktree", "remove", "--force", "--force", str(path)],
            cwd=root,
            check=False,
            timeout=120,
        ).returncode:
            shutil.rmtree(path.parent, ignore_errors=True)
    subprocess.run(["git", "worktree", "prune"], cwd=root, check=True, timeout=60)


def exclusive(handle: TextIO) -> bool:
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def locked_update(root: Path, repair: bool = False) -> str:
    from update import update

    if (blocker := update_blocker(root)) is not None:
        return blocker
    with lock_file(root).open("a") as handle:
        if not exclusive(handle):
            raise UpdateRunning(
                "Another Hard Eng update is already running for this repository; "
                "wait for its result instead of starting another"
            )
        remove_stale_candidates(root)
        return update(root, repair)


def failed_update(error: Exception | str) -> str:
    return f"Hard Eng update failed: {error}. Continue with the existing scaffold; its gates remain required."


def record_result(root: Path, outcome: str) -> None:
    result = root / RESULT_FILE
    result.parent.mkdir(parents=True, exist_ok=True)
    pending = result.with_suffix(".tmp")
    pending.write_text(f"{time.strftime('%Y-%m-%d %H:%M %Z')}: {outcome}\n")
    pending.replace(result)


def interrupt_update(signum: int, _frame: object) -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    raise subprocess.SubprocessError(f"interrupted by signal {signum}")


def installed_revision(root: Path) -> object:
    from update import SOURCE_FILE

    try:
        return json.loads((root / SOURCE_FILE).read_text()).get("revision")
    except (OSError, ValueError, AttributeError):
        return None


def apply_update(root: Path) -> int:
    """Install the update and record its outcome; the supervising process holds the lock."""
    from update import update

    signal.signal(signal.SIGTERM, interrupt_update)
    previous = installed_revision(root)
    try:
        outcome = update(root)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        outcome = failed_update(error)
        if (revision := installed_revision(root)) != previous:
            outcome = (
                f"Updated Hard Eng to {revision} with a local commit, but it stopped before "
                f"its final steps ({error}); the next update finishes them."
            )
    record_result(root, outcome)
    return 0


def update_command(*options: str) -> list[str]:
    return [
        sys.executable,
        str(Path(__file__).with_name("hard-eng.py")),
        "update",
        *options,
    ]


def group_exists(group: int) -> bool:
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # macOS refuses signals to a group holding only unreaped zombies.
        return True
    return True


def stop_group(update: "subprocess.Popen[bytes]") -> None:
    """Stop the update's whole process group, killing anything that ignores SIGTERM."""
    for signum in (signal.SIGTERM, signal.SIGKILL):
        with suppress(ProcessLookupError, PermissionError):
            os.killpg(update.pid, signum)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            update.poll()
            if not group_exists(update.pid):
                return
            time.sleep(0.1)


def run_update(root: Path) -> int:
    """Hold the repository's update lock while one update runs in its own process group."""
    with lock_file(root).open("a") as handle:
        if not exclusive(handle):
            return 0
        try:
            remove_stale_candidates(root)
            update = subprocess.Popen(
                update_command("--apply"),
                cwd=root,
                process_group=0,
                pass_fds=(handle.fileno(),),
            )
        except (OSError, subprocess.SubprocessError) as error:
            record_result(root, failed_update(error))
            return 0
        signal.signal(signal.SIGTERM, interrupt_update)
        with suppress(subprocess.SubprocessError):
            try:
                update.wait()
            finally:
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
        stop_group(update)
        if update.returncode != 0:
            record_result(root, failed_update(f"update exited {update.returncode}"))
        with suppress(OSError, subprocess.SubprocessError):
            remove_stale_candidates(root)
    return 0


def start_update(root: Path) -> str:
    """Report the last update and start the next one detached, so session start never waits on it."""
    if (blocker := update_blocker(root)) is not None:
        return "Hard Eng update result: " + blocker
    if update_running(root):
        status = "A Hard Eng update is already running in the background"
    else:
        log = root / LOG_FILE
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w") as output:
            subprocess.Popen(
                update_command(),
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        status = "Hard Eng update started in the background"
    result = root / RESULT_FILE
    last = result.read_text().strip() if result.is_file() else "none recorded yet"
    return (
        f"{status} ({LOG_FILE}); this session keeps the installed scaffold and its gates until "
        "it finishes, and the next session start reports its result. Do not run setup meanwhile. "
        f"Last update result: {last}"
    )
