"""Run the scaffold update detached from agent startup, one per repository."""

import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TextIO

from gate_config import SOURCE_FILE

RESULT_FILE = ".hard-eng/update-result.txt"
LOG_FILE = ".hard-eng/update.log"
FAILURE_FILE = ".hard-eng/update-failure.json"
LOCAL_INPUTS = (".claude/settings.local.json", "CLAUDE.local.md")
UPDATE_BRANCH = "hard-eng/update"
UPDATE_REF = f"refs/heads/{UPDATE_BRANCH}"
UPDATE_COMMAND = "python3 .hooks/hard-eng.py update-pr"
REPAIR_SUBJECT = "Install Hard Eng"
NOT_PUBLISHED = "Hard Eng updates start after the Hard Eng install is on the base branch of a remote."
CI_STEP = "CI setup pending: add a `shipping` block with the project's checks and a measured ci_seconds budget to hard-eng.gates.json and merge it to the base branch, then rerun setup"
HEX_REVISION = re.compile(r"[0-9a-f]{40}")


class UpdateRunning(ValueError):
    pass


class UpdateNeeded(ValueError):
    pass


def update_blocker(root: Path) -> str | None:
    marker = root / SOURCE_FILE
    if not marker.exists():
        return "Auto-update unavailable: no installed source revision."
    metadata = json.loads(marker.read_text())
    if not isinstance(metadata, dict):
        raise TypeError("Installed source metadata must be an object")
    previous = metadata.get("revision")
    if not isinstance(previous, str) or not HEX_REVISION.fullmatch(previous):
        return "Installed from an uncommitted copy; publish a verified revision to enable auto-updates."
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


def last_result(root: Path) -> str:
    result = root / RESULT_FILE
    return result.read_text().strip() if result.is_file() else "none recorded yet"


def stale_error(root: Path, revision: str) -> ValueError:
    if update_running(root):
        return ValueError(
            f"Hard Eng update to newer verified revision {revision} is still running in the "
            f"background ({LOG_FILE}). Wait for it to finish without starting another update, "
            "then reverify before shipping or claiming completion."
        )
    from update_pr import next_step

    return UpdateNeeded(
        f"Hard Eng freshness check found newer verified revision {revision}. "
        f"Last update result: {last_result(root)}. {next_step(root)} "
        "Shipping stays blocked until this branch contains the current Hard Eng; then reverify."
    )


@contextmanager
def source_reader(root: Path) -> Generator[Callable[[str], str | None]]:
    """One Git process gives the source revision at each ref when it is asked."""
    git = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    stdin, stdout = git.stdin, git.stdout

    def read(ref: str) -> str | None:
        if stdin is None or stdout is None:
            return None
        name = f"{ref}:{SOURCE_FILE}\n".encode()
        with suppress(OSError, ValueError, AttributeError):
            stdin.write(name)
            stdin.flush()
            fields = stdout.readline().split()
            if len(fields) == 3 and fields[2].isdigit():
                revision = json.loads(stdout.read(int(fields[2]) + 1)).get("revision")
                return revision if isinstance(revision, str) else None
        return None

    try:
        yield read
    finally:
        git.communicate()


def revision_at(root: Path, ref: str) -> str | None:
    with source_reader(root) as read:
        return read(ref)


def shipping_base(root: Path) -> str:
    try:
        base = json.loads((root / "hard-eng.gates.json").read_text())["shipping"][
            "base"
        ]
    except (OSError, ValueError, KeyError, TypeError):
        return "main"
    return base if isinstance(base, str) else "main"


def waiting_note(root: Path) -> str | None:
    # The base is read only when an update waits, so the usual Stop pays for one Git start alone.
    with source_reader(root) as read:
        waiting = read(f"refs/heads/{UPDATE_BRANCH}")
        if waiting is None or waiting == installed_revision(root):
            return None
        base = shipping_base(root)
        landed = read(f"refs/remotes/origin/{base}")
    if landed != waiting:
        return ready_message(waiting)
    return (
        f"Hard Eng update {waiting} is already on origin/{base}; this checkout does not "
        f"hold it yet. On {base}: `git pull`. On another branch: `git rebase origin/{base}`."
    )


def ready_message(revision: str) -> str:
    return (
        f"Hard Eng update {revision} ready on {UPDATE_BRANCH} → `{UPDATE_COMMAND}` "
        "(own PR beside the task's; merges on green)."
    )


def freshness_note(root: Path) -> str:
    """What the session-start update already found, read without any network request."""
    if not (root / SOURCE_FILE).exists():
        return ""
    try:
        if (blocker := update_blocker(root)) is not None:
            return blocker
        if update_running(root):
            return f"Hard Eng update still running ({LOG_FILE}); scaffold may be stale."
        if (waiting := waiting_note(root)) is not None:
            return waiting
        result = last_result(root)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        return f"Hard Eng freshness unknown: {error}."
    if NOT_PUBLISHED in result:
        return NOT_PUBLISHED
    if result == "none recorded yet":
        return "Hard Eng freshness unknown: no update result yet."
    if "failed" in result:
        first, _, rest = result.partition("\n")
        more = f" (the rest is in {RESULT_FILE})" if rest else ""
        return f"Scaffold may be stale. Last Hard Eng update: {first}{more}"
    return ""


def current_head(root: Path) -> str:
    found = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return found.stdout.strip()


def built_commit(candidate: Path, tip: str) -> str | None:
    """The update worktree is private, so its new HEAD is the updater's commit; a repair keeps the revision and needs its subject."""
    commit = current_head(candidate)
    if not commit or commit == tip:
        return None
    if revision_at(candidate, commit) != revision_at(candidate, tip):
        return commit
    subject = subprocess.check_output(
        ["git", "log", "-1", "--format=%s", commit], cwd=candidate, text=True
    )
    return commit if subject.strip() == REPAIR_SUBJECT else None


def tree_entries(
    root: Path, command: list[str], column: int, names: list[str]
) -> dict[str, tuple[str, str]]:
    listing = subprocess.check_output(
        [*command, "-z", "--", *names], cwd=root, text=True
    )
    return {
        path: (fields[0], fields[column])
        for entry in listing.split("\0")
        if entry
        for meta, _, path in [entry.partition("\t")]
        for fields in [meta.split()]
    }


def undo_hooked_commit(
    root: Path,
    head: str,
    staged: dict[str, tuple[str, str]],
    expected: dict[str, str | None],
    names: list[str],
) -> list[str]:
    """Undo the install commit when a project commit hook rewrote it; return the changed paths."""
    from update import write_changes

    commit = current_head(root)
    parent = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "HEAD^"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if not commit or commit == head or parent != head:
        return []
    committed = tree_entries(root, ["git", "ls-tree", "-r", commit], 2, names)
    changed = sorted(
        path
        for path in {*staged, *committed}
        if staged.get(path) != committed.get(path)
    )
    if not changed:
        return []
    undo = ["git", "reset", "--soft", head]
    subprocess.run(
        undo if head else ["git", "update-ref", "-d", "HEAD"], cwd=root, check=True
    )
    write_changes(
        root,
        {
            n: expected[n]
            for n in changed
            if n in expected and not (root / n).is_symlink()
        },
    )
    subprocess.run(["git", "reset", "--quiet", "--", *names], cwd=root, check=False)
    return changed


def rebase_sessions(root: Path, head: str) -> bool:
    """Sessions based on the install commit's parent must not count that commit as their work."""
    if not head:
        return False
    found = subprocess.run(
        [
            "git",
            "rev-list",
            "--first-parent",
            "--reverse",
            "--parents",
            head + "..HEAD",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.splitlines()
    commit, *parents = found[0].split() if found else [""]
    if not commit or parents[:1] != [head]:
        return False
    for state in (root / ".hard-eng/sessions").glob("*.json"):
        try:
            saved = json.loads(state.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(saved, dict) and saved.get("base") == head:
            state.write_text(json.dumps({**saved, "base": commit}))
    return True


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
            + ". A project commit hook that rejects it ran in a fresh checkout with no package install; "
            "fix that hook in the project, not Hard Eng, and leave verification to the pre-push gate"
        )


def commit_update(
    root: Path,
    changes: dict[str, str | None],
    links: dict[str, str | None],
    revision: str,
) -> None:
    from update import write_changes, write_links

    names = sorted({*changes, *links})
    write_links(root, links)
    write_changes(root, changes)
    subprocess.run(["git", "add", "--force", "--", *names], cwd=root, check=True)
    git_commit(root, names, changes, f"Update Hard Eng to {revision}")


def exclusive(handle: TextIO) -> bool:
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def locked_update(root: Path, repair: bool = False) -> str:
    if (blocker := update_blocker(root)) is not None:
        return blocker
    with lock_file(root).open("a") as handle:
        if not exclusive(handle):
            raise UpdateRunning(
                "Another Hard Eng update is already running for this repository; "
                "wait for its result instead of starting another"
            )
        from stale_updates import remove_stale_candidates

        remove_stale_candidates(root)
        try:
            outcome = prepare_update(root, repair)
        except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
            if repair:
                record_result(root, failed_update(error))
            raise
        if repair:
            record_result(root, outcome)
        return outcome


def update_attempt(head: str, revision: str) -> str:
    """What a refused update would see again: the release and the base tip it builds on."""
    import hashlib

    return f"{revision} {hashlib.sha256(head.encode()).hexdigest()}"


def known_failure(root: Path, attempt: str) -> str | None:
    try:
        saved = json.loads((root / FAILURE_FILE).read_text())
    except (OSError, ValueError):
        return None
    if (
        not isinstance(saved, dict)
        or saved.get("attempt") != attempt
        or not isinstance(saved.get("at"), (int, float))
        or time.time() - saved["at"] > 24 * 3600
    ):
        return None
    failed = time.strftime("%Y-%m-%d %H:%M %Z", time.localtime(saved["at"]))
    return failed_update(
        f"{saved.get('error')} (at {failed}; it is not retried before 24 hours unless "
        "a new release or a new base-branch commit appears; run the published setup "
        "command to retry now)"
    )


def remember_failure(root: Path, attempt: str, error: Exception) -> None:
    failure = root / FAILURE_FILE
    failure.parent.mkdir(parents=True, exist_ok=True)
    failure.write_text(
        json.dumps({"attempt": attempt, "at": time.time(), "error": str(error)})
    )


def failed_update(error: Exception | str) -> str:
    cause, start, note = str(error).partition("This checkout")
    return (
        f"Hard Eng update failed: {cause.strip().rstrip('.')}. Fix that cause first. A fix in tracked files "
        "goes on the base branch as its own commit, since the update is built from it. "
        "Cause outside repo → tell user. Installed gates still apply."
        + (f" {start}{note}" if start else "")
    )


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
    try:
        return json.loads((root / SOURCE_FILE).read_text()).get("revision")
    except (OSError, ValueError, AttributeError):
        return None


def lookup_failure(
    found: "subprocess.CompletedProcess[str]",
) -> subprocess.SubprocessError:
    lines = (found.stderr or "").strip().splitlines()
    fatal = [line for line in lines if line.startswith("fatal:")]
    reason = fatal[0] if fatal else "".join(lines[-1:])
    return subprocess.SubprocessError(
        f"git ls-remote exited {found.returncode}" + (f": {reason}" if reason else "")
    )


def update_base(root: Path) -> str:
    from shipping import load_policy

    policy = load_policy(root, required=False)
    if policy:
        return policy["base"]
    if (
        subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=root,
            capture_output=True,
            check=False,
        ).returncode
        != 0
    ):
        return "main"
    found = subprocess.run(
        ["git", "ls-remote", "--symref", "origin", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if found.returncode != 0:
        raise lookup_failure(found)
    for line in found.stdout.splitlines():
        if line.startswith("ref: refs/heads/"):
            return line.partition("\t")[0].removeprefix("ref: refs/heads/")
    return "main"


def fetch_base(root: Path, base: str) -> str:
    subprocess.run(
        ["git", "fetch", "--quiet", "--no-tags", "origin", base],
        cwd=root,
        check=True,
        timeout=120,
    )
    return subprocess.check_output(
        ["git", "rev-parse", "FETCH_HEAD^{commit}"], cwd=root, text=True
    ).strip()


def landed(root: Path, base: str, branch: str) -> bool:
    """Every file the branch changed already matches the base, as after a squash merge."""
    span = f"{base}...{branch}"
    changed = subprocess.run(
        ["git", "diff", "--name-only", "-z", span],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    names = [name for name in changed.stdout.split("\0") if name]
    if changed.returncode != 0 or not names:
        return False
    same = subprocess.run(
        ["git", "diff", "--quiet", base, branch, "--", *names], cwd=root, check=False
    )
    return same.returncode == 0


def update_branch_tip(root: Path) -> str:
    found = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", UPDATE_REF],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return found.stdout.strip()


def set_update_branch(root: Path, commit: str, expected: str) -> bool:
    command = ["git", "update-ref", UPDATE_REF, commit, expected]
    moved = subprocess.run(command, cwd=root, capture_output=True, check=False)
    if moved.returncode and update_branch_tip(root) == expected:
        raise ValueError(moved.stderr.decode().strip())
    return moved.returncode == 0


def published(root: Path, base: str) -> bool:
    """Whether origin exists and has the base branch; any other lookup failure raises."""
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if remote.returncode != 0:
        return False
    found = subprocess.run(
        ["git", "ls-remote", "--exit-code", "--heads", "origin", base],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if found.returncode not in {0, 2}:
        raise lookup_failure(found)
    return found.returncode == 0


def ci_step_notes(root: Path) -> list[str]:
    """The CI step that a project without a shipping block still owes."""
    try:
        gates = json.loads((root / "hard-eng.gates.json").read_text())
    except (OSError, ValueError):
        return []
    return [] if "shipping" in gates else [CI_STEP]


def repair_checkout(root: Path, previous: str) -> str:
    """A setup rerun fixes this checkout's pre-push hook, its gates file and the project files that are missing; the update path owns the rest."""
    import tempfile

    import hook_chain
    import update
    from ci_setup import GATES_FILE, without_workflow_gates

    hook_chain.install_worktree_hook(root)
    needs_hook = update.pre_push_missing(root) or hook_chain.foreign_hook(
        root, hook_chain.locate(root)[1]
    )
    with tempfile.TemporaryDirectory(prefix="hard-eng-update-") as temporary:
        try:
            source, old = update.fetch_sources(Path(temporary), previous, previous)
            changes, _, hook, _ = update.update_plan(root, source, old)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            if needs_hook:
                raise
            refused = isinstance(error, ValueError)
            reason = "" if refused else "the installed release could not be fetched: "
            parts = [str(error).rstrip("."), *(ci_step_notes(root) if refused else [])]
            return f"This checkout is unchanged: {reason}{'; '.join(parts)}."
    notes = []
    if needs_hook:
        update.install_planned_hook(root, hook)
        notes.append("installed the missing pre-push hook")
    planned = changes.get(GATES_FILE)
    waits = without_workflow_gates(root, changes)
    if waits is not None and waits != planned:
        changes[GATES_FILE] = (
            None if waits == (root / GATES_FILE).read_text() else waits
        )
    written = {
        name: content
        for name, content in sorted(changes.items())
        if content is not None
        and not update.maybe_installed(name)
        and (name == GATES_FILE or not (root / name).exists())
    }
    for name, content in written.items():
        update.replace_file(root / name, content.encode())
    if written:
        notes.append(
            f"setup wrote {', '.join(written)}; "
            f"review and commit {'it' if len(written) == 1 else 'them'}"
        )
    notes.extend(ci_step_notes(root))
    if waits is not None and waits != planned:
        notes.append(
            "the update brings the workflow files and their gates when the `shipping` block of hard-eng.gates.json is on the base branch"
        )
    return f"This checkout: {'; '.join(notes)}." if notes else ""


def failure_kind(error: Exception) -> type[Exception]:
    """The base class a caller catches for this error; each takes one message."""
    for kind in (subprocess.SubprocessError, OSError, TypeError):
        if isinstance(error, kind):
            return kind
    return ValueError


def prepare_update(root: Path, repair: bool = False) -> str:
    """Build the update as one commit on its own branch from the remote base, leaving this checkout alone."""
    note = ""
    if repair:
        note = repair_checkout(
            root, json.loads((root / SOURCE_FILE).read_text())["revision"]
        )
    try:
        base = update_base(root)
        if not published(root, base):
            return f"{NOT_PUBLISHED} {note}".strip()
        built = build_update(root, base, repair)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        if not note:
            raise
        raise failure_kind(error)(f"{str(error).rstrip('.')}. {note}") from error
    return f"{built} {note}".strip()


def free_step(root: Path, worktree: Path) -> str:
    from stale_updates import registered_worktrees

    if worktree == Path(registered_worktrees(root)[0]["worktree"]):
        return f"switch the main checkout to another branch with `git -C {worktree} switch <branch>`"
    return (
        f"free it with `git -C {worktree} switch --detach` or "
        f"`git worktree remove {worktree}`"
    )


def build_update(root: Path, base: str, repair: bool) -> str:
    import tempfile

    from hook_chain import use_own_hooks
    from update import update
    from update_pr import branch_worktree, unfinished_update

    tip = fetch_base(root, base)
    if update_blocker(root) is None and revision_at(root, tip) is None:
        return NOT_PUBLISHED
    expected = update_branch_tip(root)
    if unfinished_update(root, tip):
        return (
            f"Hard Eng update branch {UPDATE_BRANCH} holds unfinished work; finish it with "
            f"`{UPDATE_COMMAND}` before a newer update is prepared."
        )
    if branch_current(root, tip):
        return ready_message(revision_at(root, f"refs/heads/{UPDATE_BRANCH}") or "")
    if (worktree := branch_worktree(root)) is not None:
        raise ValueError(
            f"{UPDATE_BRANCH} is checked out in {worktree} with no unfinished work, so the "
            f"update cannot move it; {free_step(root, worktree)}, then rerun "
            "`python3 .hooks/hard-eng.py update`"
        )
    with tempfile.TemporaryDirectory(prefix="hard-eng-update-") as temporary:
        candidate = Path(temporary) / "candidate"
        subprocess.run(
            ["git", "worktree", "add", "--quiet", "--detach", str(candidate), tip],
            cwd=root,
            check=True,
            timeout=120,
        )
        owner = f"hard-eng-update {os.getpid()}"
        subprocess.run(
            ["git", "worktree", "lock", "--reason", owner, str(candidate)],
            cwd=root,
            check=True,
        )
        try:
            use_own_hooks(root, candidate)
            for name in LOCAL_INPUTS:
                if (candidate / name).is_symlink():
                    (candidate / name).unlink()
            outcome = update(candidate, repair, remember=None if repair else root)
            revision = installed_revision(candidate)
            landed = built_commit(candidate, tip)
        finally:
            subprocess.run(
                ["git", "worktree", "unlock", str(candidate)], cwd=root, check=False
            )
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(candidate)],
                cwd=root,
                check=False,
                timeout=120,
            )
    if landed is None or not isinstance(revision, str):
        return outcome
    refuse_untracked_overlap(root, tip, landed, revision, repair)
    # Work committed or checked out on the branch during the build stays.
    if branch_worktree(root) or not set_update_branch(root, landed, expected):
        return (
            f"{UPDATE_BRANCH} changed while the update was prepared, so it was kept; "
            f"rerun `python3 .hooks/hard-eng.py update` once that work is finished."
        )
    return ready_message(revision)


def refuse_untracked_overlap(
    root: Path, tip: str, landed: str, revision: str, repair: bool
) -> None:
    """The candidate never held this checkout's ignored or untracked files, so a pull could replace them."""
    from update import local_state

    changed = subprocess.check_output(
        ["git", "diff", "--name-only", "--no-renames", "-z", tip, landed],
        cwd=root,
        text=True,
    )
    names = list(filter(None, changed.split("\0")))
    if not names:
        return
    parents = {
        str(parent)
        for name in names
        for parent in Path(name).parents
        if parent != Path(".")
        and ((root / parent).is_symlink() or (root / parent).is_file())
    }
    found = [
        line[3:].strip('"')
        for line in local_state(root, [*names, *sorted(parents)])
        if line.startswith(("?? ", "!! "))
    ]
    if found:
        from hook_chain import SETUP_COMMAND

        error = ValueError(
            "The update would replace local files that Git does not track: "
            + ", ".join(found)
            + f"; move or rename them, then rerun setup to retry: {SETUP_COMMAND}"
        )
        if not repair:
            remember_failure(root, update_attempt(tip, revision), error)
        raise error


def branch_current(root: Path, tip: str) -> bool:
    """The update branch sits on the base tip and holds the newest verified release."""
    from update import latest_verified

    current = revision_at(root, tip)
    waiting = revision_at(root, f"refs/heads/{UPDATE_BRANCH}")
    branch = f"refs/heads/{UPDATE_BRANCH}"
    based = subprocess.run(
        ["git", "merge-base", "--is-ancestor", tip, branch],
        cwd=root,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return bool(
        current
        and waiting
        and HEX_REVISION.fullmatch(current)
        and based.returncode == 0
        and waiting == (latest_verified(current) or current)
        and (waiting != current or update_branch_tip(root) != tip)
    )


def apply_update(root: Path) -> int:
    """Prepare the update branch and record the outcome; the supervising process holds the lock."""
    signal.signal(signal.SIGTERM, interrupt_update)
    try:
        outcome = prepare_update(root)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        outcome = failed_update(error)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
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
    from stale_updates import remove_stale_candidates

    with lock_file(root).open("a") as handle:
        if not exclusive(handle):
            print(
                "Another Hard Eng update is already running for this repository; "
                f"its result will be in {RESULT_FILE}."
            )
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
            print(last_result(root))
            return 1
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
    result = last_result(root)
    print(result)
    return 1 if "Hard Eng update failed" in result else 0


def start_update(root: Path) -> str:
    """Report the last update and start the next one detached, so session start never waits on it."""
    if (blocker := update_blocker(root)) is not None:
        return "Hard Eng update result: " + blocker
    if update_running(root):
        status = "Hard Eng update already running in the background"
    else:
        log = root / LOG_FILE
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as output:
            subprocess.Popen(
                update_command(),
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        status = "Hard Eng update started in the background"
    return (
        f"{status} ({LOG_FILE}); installed gates apply; next start reports it; no setup meanwhile. "
        f"Last: {last_result(root)}"
    )


def update_main(root: Path, publishing: bool, apply: bool, merge: bool = True) -> int:
    if publishing:
        from update_pr import publish

        return publish(root, merge)
    return apply_update(root) if apply else run_update(root)
