"""Run a command in its own process group so a timeout stops every process it started."""

import fcntl
import json
import os
import re
import signal
import subprocess
import threading
from collections.abc import Generator, Mapping
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import IO, NamedTuple

from project_files import clean_tree

BROKER = re.compile(
    r"^\S+ \S*/app-server-broker\.mjs serve --endpoint \S+ --cwd (.+) --pid-file \S+$"
)
COMPANION = "codex-companion.mjs"
RUNNING: set[int] = set()
STOPPED = threading.Event()
STOP_SIGNAL: list[int] = []
STARTING = threading.Lock()
INSTALLS: dict[str, bool] = {}
INSTALLED_FILE = "hard-eng-installed"
PASSED_FILE = "hard-eng-passed"
PASSED_SECONDS = 1800
INSTALL_FOLDERS = (".venv", "node_modules", ".dart_tool")


class Process(NamedTuple):
    pid: int
    parent: int
    command: str


def run_in_group(
    command: list[str],
    *,
    timeout: float | None,
    cwd: os.PathLike[str] | str | None = None,
    env: dict[str, str] | None = None,
    stdin: int | IO[str] | None = None,
    stdout: int | IO[str] | None = None,
    stderr: int | IO[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Like subprocess.run, but a timeout or interrupt kills the whole group first."""
    process: subprocess.Popen[str] | None = None
    try:
        with STARTING:
            if STOPPED.is_set():
                raise KeyboardInterrupt
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                text=True,
                start_new_session=True,
            )
            RUNNING.add(process.pid)
        out, err = process.communicate(timeout=timeout)
    except BaseException:
        if process is not None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
        raise
    finally:
        if process is not None:
            RUNNING.discard(process.pid)
    return subprocess.CompletedProcess(command, process.returncode, out, err)


def exit_when_stopped() -> None:
    """SIGTERM and SIGHUP end the process through the exit path that stops its groups."""

    def stop(number: int, _frame: object) -> None:
        STOP_SIGNAL[:] = [number]
        raise SystemExit(128 + number)

    for number in (signal.SIGTERM, signal.SIGHUP):
        if signal.getsignal(number) is not signal.SIG_IGN:
            signal.signal(number, stop)


def stop_groups() -> None:
    """An interrupt reaches only the main thread, not commands run by worker threads;
    they start no new command until `STOPPED` is cleared."""
    with STARTING:
        STOPPED.set()
        for group in RUNNING.copy():
            with suppress(ProcessLookupError, PermissionError):
                os.killpg(group, signal.SIGKILL)


def stopped_note(code: int) -> str:
    """The text for a gate that ended because the check was stopped."""
    if code == 0 or not STOPPED.is_set():
        return ""
    cause = f" by {signal.Signals(STOP_SIGNAL[0]).name}" if STOP_SIGNAL else ""
    return f"\nThe check was stopped{cause}, so this gate was ended before it finished."


GENERATED_FILES_NOTE = (
    "Generated Dart files are missing in this checkout. Run the code generation of "
    "this package, then run the check again. Give the gate that runs it the role "
    "`generated` in hard-eng.gates.json: a new checkout then runs it one time before "
    "this gate.\n"
)


def generated_files_note(command: list[str], code: int, output: str) -> str:
    """The step to take when a failed Dart analysis reports generated files that do not exist."""
    analysis = command[:2] in (["dart", "analyze"], ["flutter", "analyze"])
    return (
        GENERATED_FILES_NOTE
        if code and analysis and "uri_has_not_been_generated" in output
        else ""
    )


def parallel_hint(
    code: int, tests: bool, command: list[str], report: Path | None = None
) -> str:
    """The advice for a failed parallel test run; none when its report holds no failed test."""
    if code in {0, 5} or not tests or "-n auto" not in " ".join(command):
        return ""
    if report is not None:
        from reports import junit_root

        with suppress(OSError, SyntaxError):
            tree = junit_root(report)
            if not (tree.findall(".//failure") or tree.findall(".//error")):
                return ""
    return (
        "\nThese tests ran in parallel (-n auto). If they pass serially, isolate "
        "the state they share, or set -n 0 in this gate's command."
    )


def process_table() -> list[Process]:
    output = subprocess.run(
        ["ps", "-Ao", "pid=,ppid=,command="],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    rows = []
    for line in output.splitlines():
        pid, parent, command = (line.split(None, 2) + [""])[:3]
        rows.append(Process(int(pid), int(parent), command))
    return rows


def state_path(root: Path, name: str) -> Path:
    """A file in this checkout's own Git folder, so a linked worktree keeps its own."""
    return (
        root
        / subprocess.check_output(
            ["git", "rev-parse", "--git-path", name], cwd=root, text=True
        ).strip()
    )


@contextmanager
def check_lock_file(root: Path) -> Generator[tuple[IO[str], bool]]:
    """Open this checkout's check lock and try to take it; the flag says another check holds it."""
    with state_path(root, "hard-eng-check.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            held = True
        else:
            held = False
        yield lock, held


def lock_stamp(root: Path, key: str) -> str:
    """Size and change time of each lock file, and the install folders, in a package group's folder; its install mark holds only while they stay the same.

    A workspace root can hold the install and have no language, so the language does not pick the names."""
    from gate_config import LOCKFILES

    folder = root / key.partition(":")[2]
    found = []
    for name in sorted({name for names in LOCKFILES.values() for name in names}):
        with suppress(OSError):
            status = (folder / name).stat()
            found.append(f"{name} {status.st_size} {status.st_mtime_ns}")
    present = [name for name in INSTALL_FOLDERS if (folder / name).is_dir()]
    return "; ".join([*found, f"folders {' '.join(present)}"])


def read_installed(lock: IO[str], root: Path) -> frozenset[str]:
    """Package groups whose install passed in this checkout with the lock files of now; a bad state file counts as none."""
    INSTALLS.clear()
    try:
        saved = json.loads(Path(lock.name).with_name(INSTALLED_FILE).read_text())
    except (OSError, ValueError):
        return frozenset()
    if not isinstance(saved, dict):
        return frozenset()
    return frozenset(
        key for key, stamp in saved.items() if stamp == lock_stamp(root, key)
    )


# A new checkout needs its dependencies and its generated code before the quick gates can judge it.
INSTALL_ROLES = ("lockfiles", "generated")


def install_key(group: Mapping[str, object]) -> str:
    """One mark for each package group: two languages can share a folder, and each has its own install."""
    return f"{group.get('language', '')}:{group['path']}"


def note_install(key: str, role: object, failed: bool) -> None:
    if role in INSTALL_ROLES:
        INSTALLS[key] = INSTALLS.get(key, True) and not failed


def save_installed(lock: IO[str], before: frozenset[str], root: Path) -> None:
    passed = {key for key, ok in INSTALLS.items() if ok}
    after = (before | passed) - (INSTALLS.keys() - passed)
    if after != before:
        with suppress(OSError):
            Path(lock.name).with_name(INSTALLED_FILE).write_text(
                json.dumps({key: lock_stamp(root, key) for key in sorted(after)})
            )


def clean_start(
    lock: IO[str], root: Path, base: str | None, plan_stage: str | None, partial: bool
) -> tuple[str, str, float] | None:
    """Remove the old pass record; give the start of a full check that may write a new one; a partial check or one in CI does no record work."""
    import time

    if partial or os.environ.get("CI") or plan_stage not in (None, "Complete"):
        return None
    if base is None:
        from change_size import judged_point
        from update import update_in_diff

        base = judged_point(root)
        if base is None or update_in_diff(root, base) is not None:
            return None
    with suppress(OSError):
        Path(lock.name).with_name(PASSED_FILE).unlink()
    commit = subprocess.run(
        ["git", "rev-parse", "--verify", "-q", base + "^{commit}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    state = clean_tree(root)
    if commit.returncode or state is None or not state[1]:
        return None
    return state[0], commit.stdout.strip(), time.time()


def record_pass(
    lock: IO[str], root: Path, start: tuple[str, str, float] | None, failed: bool
) -> None:
    """A full check that passed on a clean tree and left it clean is a pass of its commit and base."""
    if start is None or failed or clean_tree(root) != (start[0], True):
        return
    record = Path(lock.name).with_name(PASSED_FILE)
    with suppress(OSError):
        temporary = record.with_name(f"{PASSED_FILE}.tmp")
        temporary.write_text(
            json.dumps({"head": start[0], "base": start[1], "time": start[2]})
        )
        temporary.replace(record)


def fresh_pass(record: Path) -> tuple[str, str, int] | None:
    """Commit, base and age in minutes of the full pass that this record holds while it is fresh; any doubt is None."""
    import time

    try:
        saved = json.loads(record.read_text())
        age = time.time() - saved["time"]
        head, base = saved["head"], saved["base"]
        if (
            isinstance(head, str)
            and isinstance(base, str)
            and not isinstance(saved["time"], bool)
            and 0 <= age <= PASSED_SECONDS
        ):
            return head, base, int(age // 60)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def passed_note(minutes: int, earlier: bool = False) -> str:
    where = "commit from an earlier base" if earlier else "commit and base"
    return f"Hard Eng: the full check passed on this exact {where} {minutes} min ago; not repeating it."


def passed_minutes(root: Path, revision: str, base: str) -> int | None:
    """Minutes since a full check passed on this commit and base; any doubt is None."""
    try:
        found = fresh_pass(state_path(root, PASSED_FILE))
    except (OSError, subprocess.SubprocessError):
        return None
    return found[2] if found and found[:2] == (revision, base) else None


def lock_and_pass(root: Path) -> tuple[bool, tuple[str, str, int] | None]:
    """Whether another check holds this checkout's lock, and the fresh full pass of the record beside it."""
    with check_lock_file(root) as (lock, held):
        return held, fresh_pass(Path(lock.name).with_name(PASSED_FILE))


def covering_minutes(
    root: Path, passed: tuple[str, str, int] | None, tip: str | None, base: str
) -> tuple[int, bool] | None:
    """Minutes since a full check passed on this commit with a clean tree, and whether its base is an earlier one; the Git starts come last."""
    if passed is None or passed[0] != tip:
        return None
    earlier = passed[1] != base
    if earlier:
        older = subprocess.run(
            ["git", "merge-base", "--is-ancestor", "--end-of-options", passed[1], base],
            cwd=root,
            check=False,
            capture_output=True,
        )
        if older.returncode != 0:
            return None
    return (passed[2], earlier) if clean_tree(root) == (tip, True) else None


def stop_idle_codex_brokers(table: list[Process] | None = None) -> tuple[int, int]:
    """SessionEnd alone misses killed sessions; a job's folder is not readable, so any job keeps live folders."""
    rows = process_table() if table is None else table
    children: dict[int, list[int]] = {}
    for row in rows:
        children.setdefault(row.parent, []).append(row.pid)
    jobs = any(COMPANION in row.command for row in rows)
    brokers = stopped = 0
    for row in rows:
        broker = BROKER.match(row.command)
        if broker is None:
            continue
        if jobs and Path(broker.group(1)).is_dir():
            continue
        tree: list[int] = []
        pending = [row.pid]
        while pending:
            pid = pending.pop()
            tree.append(pid)
            pending.extend(children.get(pid, []))
        for pid in tree:
            with suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGTERM)
        brokers += 1
        stopped += len(tree)
    return brokers, stopped
