"""Order gates and run the gate chains of separate packages at the same time."""

import os
import posixpath
import re
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path, PurePosixPath

from dependency_graph import reachable
from gate_config import Gate, Group
from process_group import STOPPED, stop_groups

Check = tuple[Group, Gate]

SCAN_ROLES = frozenset(
    {
        "secrets-files",
        "secrets-history",
        "security",
        "vulnerabilities",
        "freshness",
        "workflows",
        "ci-security",
        "shell",
    }
)
QUICK_ROLES = frozenset(
    {
        "format",
        "lint",
        "format-lint",
        "types",
        "annotations",
        "typing-style",
        "imports",
        "focused-tests",
        "secrets-files",
    }
)
DART_ANALYSIS = (
    ["dart", "analyze", "--fatal-infos"],
    ["dart", "analyze", "--fatal-infos", "."],
)
ANALYSIS_SETTINGS = (".yaml", ".lock", ".arb")
PART_OF_FILE = re.compile(r"""(?m)^part\s+of\s+(?:'([^'\n]*)'|"([^"\n]*)")\s*;""")
PART_OF_NAME = re.compile(r"(?m)^part\s+of\s+[\w.]+\s*;")
READ_ONLY_ROLES = (
    QUICK_ROLES
    | SCAN_ROLES
    | {
        "tests",
        "performance",
        "complexity",
        "dead-code",
        "duplicates",
        "dead-code-duplicates",
        "dependencies",
        "types-lint",
        "react",
        "shipped-format",
    }
)


def changed_dart(
    root: Path, groups: list[Group], changed: set[str] | None
) -> dict[str, list[str]]:
    """The changed Dart files that a quick check analyses first, for each Dart analysis gate; a gate with no entry analyses its package."""
    if changed is None or any(name.endswith(ANALYSIS_SETTINGS) for name in changed):
        return {}
    gates = [
        (group, gate)
        for group in groups
        for gate in group["checks"]
        if gate["command"] in DART_ANALYSIS
    ]
    # Git names a changed submodule or nested repository by its folder, not by its files.
    if not gates or any(
        not (root / name).is_file()
        if name.endswith(".dart")
        else (root / name).is_dir()
        for name in changed
    ):
        return {}
    files = sorted(PurePosixPath(name) for name in changed if name.endswith(".dart"))
    listed: dict[str, list[PurePosixPath] | None] = {}
    found: dict[str, list[str]] = {}
    for group, gate in gates:
        path = group["path"]
        if not all(file.is_relative_to(path) for file in files):
            continue
        if path not in listed:
            listed[path] = with_libraries(root, path, files)
        if (known := listed[path]) is not None:
            found[f"{path}/{gate['name']}"] = [
                str(file.relative_to(path)) for file in known
            ]
    return found


def with_libraries(
    root: Path, path: str, files: list[PurePosixPath]
) -> list[PurePosixPath] | None:
    """The changed files and the library of each changed part file; None when a library cannot be named."""
    found = set(files)
    for file in files:
        try:
            text = (root / file).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        if PART_OF_NAME.search(text):
            return None
        if (part := PART_OF_FILE.search(text)) is None:
            continue
        name = part.group(1) or part.group(2)
        if ":" in name:
            return None
        library = PurePosixPath(posixpath.normpath(posixpath.join(file.parent, name)))
        if (
            library.parts[:1] == ("..",)
            or not library.is_relative_to(path)
            or not (root / library).is_file()
        ):
            return None
        found.add(library)
    return sorted(found)


def early_scan(gate: Gate) -> bool:
    return gate.get("role") in SCAN_ROLES and gate.get("parallel", False) is True


def writes(gate: Gate) -> bool:
    return gate.get("role") not in READ_ONLY_ROLES


def timed(gate: Gate) -> bool:
    return gate.get("role") == "performance"


def inside(group: Group, folder: Group) -> bool:
    path, parent = PurePosixPath(group["path"]), PurePosixPath(folder["path"])
    return path == parent or parent in path.parents


def stays_after(item: Check, earlier: Check) -> bool:
    """A writer may read the results of readers inside its folder; a suite times what writers made."""
    (group, gate), (other, before) = item, earlier
    if writes(before):
        return True
    if timed(gate):
        return timed(before)
    return inside(other, group)


def gate_order(checks: list[Check]) -> list[Check]:
    """Setup first; writers and performance suites as early as what they read allows;
    then scans; then the other readers."""
    setup = [item for item in checks if item[1].get("role") == "lockfiles"]
    scans = [item for item in checks if early_scan(item[1])]
    order: list[Check] = []
    for item in checks:
        if item[1].get("role") == "lockfiles" or early_scan(item[1]):
            continue
        if writes(item[1]) or timed(item[1]):
            after = [i + 1 for i, other in enumerate(order) if stays_after(item, other)]
            order.insert(max(after, default=0), item)
        else:
            order.append(item)
    cut = max(
        (i + 1 for i, (_, gate) in enumerate(order) if writes(gate) or timed(gate)),
        default=0,
    )
    return setup + order[:cut] + scans + order[cut:]


def related(first: Group, second: Group, reach: dict[str, set[str]]) -> bool:
    return (
        inside(first, second)
        or inside(second, first)
        or second["path"] in reach.get(first["path"], ())
        or first["path"] in reach.get(second["path"], ())
    )


def clears_reports(group: Group, gate: Gate) -> bool:
    """JavaScript test runners clear coverage/, where other gates in the folder write."""
    return group.get("language") == "javascript" and gate.get("role") == "tests"


def reads_coverage(gate: Gate) -> bool:
    """A Fallow gate may reuse the coverage of the packages it depends on."""
    return gate.get("report", {}).get("type") == "fallow"


def waits(earlier: Check, later: Check, reach: dict[str, set[str]]) -> bool:
    """Setup and performance suites run alone; serial gates of a package keep their
    order; a writer keeps its order against related packages, except between two
    parallel gates, which were declared independent."""
    (first, a), (second, b) = earlier, later
    if {a.get("role"), b.get("role")} & {"lockfiles", "performance"}:
        return True
    parallel = a.get("parallel", False), b.get("parallel", False)
    if first is second and not any(parallel):
        return True
    ordered = early_scan(a) or early_scan(b) or not all(parallel)
    if (writes(a) or writes(b)) and ordered and related(first, second, reach):
        return True
    if first["path"] == second["path"] and (
        clears_reports(first, a) or clears_reports(second, b)
    ):
        return True
    return (
        reads_coverage(b)
        and a.get("role") == "tests"
        and first["path"] in reach.get(second["path"], ())
    )


def blocked_by(ordered: list[Check], index: int, failed: set[int]) -> str | None:
    """A Fallow gate cannot read coverage that a failed test gate never wrote."""
    if not reads_coverage(ordered[index][1]):
        return None
    for earlier in sorted(failed):
        group, gate = ordered[earlier]
        if gate.get("role") == "tests":
            return f"{group['path']}/{gate['name']}"
    return None


def start(
    run: Callable[[Group, Gate], bool], source: str | None
) -> Callable[[Group, Gate], bool]:
    if source is None:
        return run

    def blocked(_group: Group, gate: Gate) -> bool:
        print(
            f"BLOCKED {gate['name']}: it reads the coverage of {source}, which failed"
        )
        return True

    return blocked


def run_checks(
    checks: list[Check], run: Callable[[Group, Gate], bool], packages: list[Group]
) -> bool | None:
    """Start each gate once the gates it waits for finish; a serial gate may use every
    core, so at most max(2, CPUs / 4) run at once. None when dependency setup failed."""
    ordered = gate_order(checks)
    reach = reachable([group for group in packages if "depends_on" in group])
    needs = [
        {i for i in range(index) if waits(ordered[i], item, reach)}
        for index, item in enumerate(ordered)
    ]
    workers = os.cpu_count() or 2
    budget = max(2, workers // 4)
    waiting = list(range(len(ordered)))
    running: dict[Future[bool], int] = {}
    finished: set[int] = set()
    broken: set[int] = set()
    failed = False
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            try:
                while waiting or running:
                    serial = sum(
                        not ordered[i][1].get("parallel", False)
                        for i in running.values()
                    )
                    for index in list(waiting):
                        group, gate = ordered[index]
                        heavy = not gate.get("parallel", False)
                        if len(running) == workers:
                            break
                        if not needs[index] <= finished or (heavy and serial == budget):
                            continue
                        if heavy:
                            serial += 1
                        waiting.remove(index)
                        source = blocked_by(ordered, index, needs[index] & broken)
                        running[pool.submit(start(run, source), group, gate)] = index
                    done, _ = wait(running, return_when=FIRST_COMPLETED)
                    for future in done:
                        index = running.pop(future)
                        finished.add(index)
                        if future.result():
                            failed = True
                            broken.add(index)
                            if ordered[index][1].get("role") == "lockfiles":
                                print(
                                    "Dependency setup failed; remaining checks were not run."
                                )
                                return None
            except BaseException:
                stop_groups()
                raise
    finally:
        STOPPED.clear()
    return failed
