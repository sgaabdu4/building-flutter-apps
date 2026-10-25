"""Last passing time of each gate, so a hung gate stops early."""

import json
import os
import subprocess
import threading
from pathlib import Path

from gate_config import JsonValue

GATE_FLOOR_SECONDS = 600
GATE_TIMES_LOCK = threading.Lock()


def gate_times(root: Path) -> Path:
    common = subprocess.check_output(
        ["git", "rev-parse", "--git-common-dir"], cwd=root, text=True
    ).strip()
    return root / common / "hard-eng-gate-times.json"


def gate_limit(root: Path, key: str, budget: float) -> float:
    """A hung gate stops at three times its last passing time, not the whole budget."""
    try:
        times = json.loads(gate_times(root).read_text())
    except (OSError, ValueError, subprocess.CalledProcessError):
        return budget
    last = times.get(key) if isinstance(times, dict) else None
    if not isinstance(last, int | float):
        return budget
    return min(budget, max(GATE_FLOOR_SECONDS, 3 * last))


def record_gate_time(root: Path, key: str, seconds: float) -> None:
    path = gate_times(root)
    with GATE_TIMES_LOCK:
        try:
            loaded = json.loads(path.read_text())
        except (OSError, ValueError):
            loaded = None
        times: dict[str, JsonValue] = loaded if isinstance(loaded, dict) else {}
        times[key] = round(seconds, 3)
        temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(times))
        temporary.replace(path)
