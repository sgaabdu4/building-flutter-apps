"""Recent passing times of each gate, so a hung gate stops early."""

import fcntl
import json
import os
import subprocess
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from gate_config import Gate, Group, JsonValue
from project_files import keep

GATE_FLOOR_SECONDS = 600
RECENT_PASSES = 5
LOCK_WAIT_SECONDS = 5.0
COMMON_FOLDER_LOCK = threading.Lock()
STOPPED_AT_LIMIT: set[str] = set()


def times_file(root: Path) -> Path:
    common = subprocess.check_output(
        ["git", "rev-parse", "--git-common-dir"], cwd=root, text=True
    ).strip()
    return root / common / "hard-eng-gate-times.json"


def gate_key(group: Group, gate: Gate, related_base: str | None) -> str:
    key = f"{group['path']}/{gate['name']}" + ("@related" if related_base else "")
    if part := gate.get("part"):
        key += "@shard" if part.isdecimal() else "@merge"
    return key


def gate_times(root: Path) -> Path:
    with COMMON_FOLDER_LOCK:
        return keep("references", ("gate_times", str(root)), lambda: times_file(root))


def passing_times(times: JsonValue, key: str) -> tuple[list[float], bool]:
    if not isinstance(times, dict):
        return [], False
    entry = times.get(key)
    timed_out = False
    if isinstance(entry, dict):
        timed_out = entry.get("timed_out") is True
        entry = entry.get("passes")
    if isinstance(entry, int | float) and not isinstance(entry, bool):
        entry = [entry]
    if not isinstance(entry, list):
        return [], timed_out
    return [
        float(seconds)
        for seconds in entry
        if isinstance(seconds, int | float) and not isinstance(seconds, bool)
    ], timed_out


def gate_limit(root: Path, key: str, budget: float) -> float:
    """A hung gate stops at three times its slowest recent pass; one that timed out gets the budget."""
    try:
        times = json.loads(gate_times(root).read_text())
    except (OSError, ValueError, subprocess.CalledProcessError):
        return budget
    passes, timed_out = passing_times(times, key)
    if timed_out or not passes:
        return budget
    return min(budget, max(GATE_FLOOR_SECONDS, 3 * max(passes)))


@contextmanager
def lock_gate_times(root: Path) -> Generator[bool]:
    with gate_times(root).with_suffix(".lock").open("w") as lock:
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    yield False
                    return
                time.sleep(0.05)
        yield True


def update_gate_record(root: Path, key: str, seconds: float | None) -> None:
    path = gate_times(root)
    with lock_gate_times(root) as locked:
        if not locked:
            return
        try:
            loaded = json.loads(path.read_text())
        except (OSError, ValueError):
            loaded = None
        times: dict[str, JsonValue] = loaded if isinstance(loaded, dict) else {}
        passes, _ = passing_times(times, key)
        if seconds is not None:
            passes = [*passes, round(seconds, 3)][-RECENT_PASSES:]
        recent: list[JsonValue] = [*passes]
        times[key] = {"passes": recent, "timed_out": seconds is None}
        temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(times))
        temporary.replace(path)


def record_gate_time(root: Path, key: str, seconds: float) -> None:
    update_gate_record(root, key, seconds)


def record_gate_timeout(root: Path, key: str) -> None:
    update_gate_record(root, key, None)


def run_not_finished(
    error: Exception, group: Group, gate: Gate, related_base: str | None
) -> bool:
    if isinstance(error, subprocess.TimeoutExpired):
        STOPPED_AT_LIMIT.add(gate_key(group, gate, related_base))
    return isinstance(error, ImportError | OSError | subprocess.TimeoutExpired)


def settle_gate_time(root: Path, key: str, failed: bool, seconds: float) -> bool:
    if key in STOPPED_AT_LIMIT:
        record_gate_timeout(root, key)
        return True
    if not failed:
        record_gate_time(root, key, seconds)
    return failed


def gate_budget(root: Path) -> float:
    """Each gate's ceiling: CI's budget in CI, pre-push's elsewhere."""
    from shipping import load_policy

    policy = load_policy(root, required=False)
    if policy is None:
        return 600
    return policy["ci_seconds" if os.environ.get("CI") else "pre_push_seconds"]
