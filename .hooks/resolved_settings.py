"""Judge the settings that Ruff, Fallow and Dart Decimate print for each gate, so no spelling of a setting can hide a narrowed rule set."""

import subprocess
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
from pathlib import Path

from command_words import direct, launch
from dart_boundaries import nested_package_patterns
from decimate_resolved import decimate_hits, option_hits, scanned_folder
from decimate_resolved import default_config as decimate_defaults
from fallow_report import (
    named_config,
    native_fallow_command,
    native_scanner_command,
    option,
)
from fallow_resolved import default_config, fallow_hits
from gate_config import Gate, Group
from project_setup import package_script_invocation
from ruff_settings import option_words
from ruff_table import ruff_hits
from scope_check import (
    RUFF_SUFFIXES,
    governing_samples,
    left_out,
    nested_configs,
    refusal,
    requires_python_of,
)
from tool_setup import managed_command


def printed(
    prefix: list[str], arguments: list[str], directory: Path, timeout: float
) -> str:
    done = subprocess.run(
        [*prefix, "check", "--show-settings", *arguments],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if done.returncode:
        raise ValueError(
            f"HE-NO-SWITCH-OFF: ruff could not print its settings for this gate: {done.stderr.strip()}"
        )
    return done.stdout


def shown(
    prefix: list[str], arguments: list[str], directory: Path, timeout: float
) -> set[str]:
    """The files that ruff checks for this gate, relative to the gate folder."""
    done = subprocess.run(
        [*prefix, "check", "--show-files", *arguments],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if done.returncode:
        raise ValueError(
            f"HE-NO-SWITCH-OFF: ruff could not list the files of this gate: {done.stderr.strip()}"
        )
    base = directory.resolve()
    return {
        Path(line).resolve().relative_to(base).as_posix()
        for line in done.stdout.splitlines()
        if line.strip() and Path(line).resolve().is_relative_to(base)
    }


Task = Callable[[], list[str]]


class Defaults:
    """Each tool's own default settings, printed once and shared by every gate that needs them."""

    def __init__(self, pool: ThreadPoolExecutor, root: Path, timeout: float) -> None:
        self.pool, self.root, self.timeout = pool, root, timeout
        self.ruff_runs: dict[tuple[tuple[str, ...], bool], Future[str]] = {}
        self.fallow_run: Future[dict[str, object]] | None = None
        self.decimate_run: Future[dict[str, object]] | None = None

    def ruff(self, prefix: tuple[str, ...], role: object = None) -> Future[str]:
        """Ruff's own settings: its defaults, or for an annotations gate the template rule set."""
        key = (prefix, role == "annotations")
        if key not in self.ruff_runs:
            chosen = ["--select", ANNOTATION_SET, *ANNOTATION_CONFIG] if key[1] else []
            self.ruff_runs[key] = self.pool.submit(
                printed,
                list(prefix),
                ["--isolated", *chosen],
                self.root,
                self.timeout,
            )
        return self.ruff_runs[key]

    def decimate(self) -> Future[dict[str, object]]:
        if self.decimate_run is None:
            self.decimate_run = self.pool.submit(decimate_defaults, self.timeout)
        return self.decimate_run

    def fallow(self) -> Future[dict[str, object]]:
        if self.fallow_run is None:
            self.fallow_run = self.pool.submit(default_config, self.timeout)
        return self.fallow_run


Scope = tuple[Path, list[Group], Group, Gate]


ANNOTATION_SET = "ANN,TID251,RUF017,ASYNC210"
ANNOTATION_CONFIG = [
    "--config",
    'lint.flake8-tidy-imports.banned-api = {"typing.Any" = {msg = "Use a precise type instead of Any"}, "typing_extensions.Any" = {msg = "Use a precise type instead of Any"}}',
]


def group_roots(root: Path, every: list[Group]) -> frozenset[Path]:
    return frozenset((root / group["path"]).resolve() for group in every)


def ruff_roots(root: Path, every: list[Group]) -> frozenset[Path]:
    """The group roots that run Ruff: a ruff config in any other folder is read by the gate above it, whatever language owns the folder."""

    def runs_ruff(group: Group) -> bool:
        for gate in group["checks"]:
            try:
                found = direct(gate["command"], root / group["path"])
            except ValueError:
                continue
            if found and found[0] == "ruff":
                return True
        return False

    return frozenset(
        (root / group["path"]).resolve() for group in every if runs_ruff(group)
    )


def ruff_tasks(
    scope: Scope,
    defaults: Defaults,
    timeout: float,
) -> list[Task]:
    root, every, group, gate = scope
    directory = root / group["path"]
    found = launch(gate["command"], directory)
    if not found or found[1][0] != "ruff" or found[1][1:2] != ["check"]:
        return []
    launcher, judged = found
    command = managed_command([*launcher, *judged[1:]], directory)
    count = len(judged) - 1
    prefix = command[: len(command) - count]
    arguments = command[len(command) - count :]
    children = nested_package_patterns(group, every, gate.get("role", ""))
    roots = ruff_roots(root, every)
    tasks = [
        partial(
            ruff_gate_hits,
            (tuple(prefix), arguments[1:], directory, gate, timeout),
            (children, roots),
            defaults.ruff(tuple(prefix), gate.get("role")),
        )
    ]
    if launcher[:2] == ["uv", "run"]:
        tasks.append(partial(own_binary_hits, launcher[:-1], directory, gate, timeout))
        tasks.append(partial(lock_source_hits, directory, gate))
    return tasks


OWN_BINARY = """import importlib.metadata as metadata, os, shutil, sys
tool = sys.argv[1]
found = shutil.which(tool)
try:
    owned = {os.path.realpath(f.locate()) for f in metadata.distribution(tool).files or []}
except metadata.PackageNotFoundError:
    owned = set()
print("ok" if found and os.path.realpath(found) in owned else "foreign")
"""


def lock_source_hits(directory: Path, gate: Gate) -> list[str]:
    """The `ruff` package of uv.lock must come from the public index: a path, directory, editable or git source is a local package that can carry any file."""
    import tomllib

    for folder in [directory.resolve(), *directory.resolve().parents]:
        lock = folder / "uv.lock"
        if lock.is_file():
            try:
                packages = tomllib.loads(lock.read_text()).get("package", [])
            except tomllib.TOMLDecodeError:
                break
            sources = [
                package.get("source", {})
                for package in packages
                if package.get("name") == "ruff"
            ]
            if sources and all(
                source.get("registry") == "https://pypi.org/simple"
                for source in sources
            ):
                return []
            break
        if (folder / ".git").exists():
            break
    return [
        f"gate {gate['name']}: the ruff that `uv run` starts must come from the public index `https://pypi.org/simple` in uv.lock, not from a path, directory, editable, git or other index source: use the published ruff package or run `uvx ruff@<pin>`"
    ]


def own_binary_hits(
    prefix: list[str], directory: Path, gate: Gate, timeout: float
) -> list[str]:
    """`uv run` runs the file the project environment holds under the tool's name: it must be a file that the ruff package installed, not a workspace member's script or a copy."""
    done = subprocess.run(
        [*prefix, "python", "-c", OWN_BINARY, "ruff"],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if done.stdout.strip() == "ok":
        return []
    return [
        f"gate {gate['name']}: the `ruff` that `{' '.join(prefix)}` runs is not installed by the ruff package: remove the script or file that takes its name, or run `uvx ruff@<pin>`"
    ]


def ruff_gate_hits(
    run: tuple[tuple[str, ...], list[str], Path, Gate, float],
    scope: tuple[frozenset[str], frozenset[Path]],
    baseline: Future[str],
) -> list[str]:
    children, roots = scope
    prefix, arguments, directory, gate, timeout = run
    checked = shown(list(prefix), arguments, directory, timeout)
    options = option_words(arguments)
    hits: list[str] = []
    for sample in governing_samples(directory, checked) or [None]:
        settings = printed(
            list(prefix), [*options, *([sample] if sample else [])], directory, timeout
        )
        hits += [
            hit
            for hit in ruff_hits(
                settings,
                baseline.result(),
                gate.get("role"),
                requires_python_of(directory, sample),
            )
            if hit not in hits
        ]
    left = left_out(directory, RUFF_SUFFIXES, checked, children)
    nested = nested_configs(directory, "ruff", roots)
    return [
        f"gate {gate['name']}: {hit}"
        for hit in [
            *hits,
            *refusal(left, None if "." in arguments else gate.get("role")),
            *nested,
        ]
    ]


def fallow_tasks(
    scope: Scope,
    defaults: Defaults,
    timeout: float,
) -> list[Task]:
    root, every, group, gate = scope
    directory = root / group["path"]
    judged = direct(gate["command"], directory)
    invocation = native_fallow_command(judged) if judged else None
    if invocation is None:
        return []
    children = nested_package_patterns(group, every, gate.get("role", ""))
    reports = [
        other["report"]["coverage"]
        for other in group["checks"]
        if other.get("role") == "tests" and other.get("report", {}).get("coverage")
    ]
    proof = (reports, option(invocation, "--coverage"))
    return [
        partial(
            fallow_gate_hits,
            (directory, named_config(invocation), children, gate, timeout, proof),
            group_roots(root, every),
            defaults.fallow(),
        )
    ]


def fallow_gate_hits(
    run: tuple[
        Path,
        str | None,
        frozenset[str],
        Gate,
        float,
        tuple[list[str], str | None],
    ],
    roots: frozenset[Path],
    defaults: Future[dict[str, object]],
) -> list[str]:
    directory, config, children, gate, timeout, proof = run
    hits = fallow_hits(directory, config, children, defaults.result(), timeout, proof)
    return [
        f"gate {gate['name']} ({directory.name}): {hit}"
        for hit in [*hits, *nested_configs(directory, "fallow", roots)]
    ]


def decimate_tasks(
    scope: Scope,
    defaults: Defaults,
    timeout: float,
) -> list[Task]:
    root, every, group, gate = scope
    command = scan_command(root / group["path"], gate)
    scan = group.get("language") == "dart" and gate.get("role") in SCAN_ROLES
    if command[:1] != ["dart-decimate"]:
        return [partial(named_hits, gate, [unreadable_hit(command)])] if scan else []
    if command[:2] != ["dart-decimate", "check"]:
        return [partial(named_hits, gate, [subcommand_hit(command)])] if scan else []
    tasks: list[Task] = []
    if hits := option_hits(command, gate.get("role", "")):
        tasks.append(partial(named_hits, gate, hits))
    folder = scanned_folder(command)
    if folder != ".":
        tasks.append(partial(other_folder_hits, gate, folder))
    elif gate.get("role") == "dead-code-duplicates":
        children = nested_package_patterns(group, every, gate.get("role", ""))
        run = (
            root / group["path"],
            option(command, "--config"),
            children,
            gate,
            timeout,
        )
        tasks.append(partial(decimate_gate_hits, run, defaults.decimate()))
    return tasks


def scan_command(directory: Path, gate: Gate) -> list[str]:
    """The command the runner starts for a gate: a package script and a launcher such as `bun x` resolved."""
    try:
        arguments, _ = package_script_invocation(gate["command"], directory)
    except (ValueError, TypeError, OSError):
        arguments = gate["command"]
    return native_scanner_command(arguments) or gate["command"]


SCAN_ROLES = {"dead-code-duplicates", "boundaries"}


def unreadable_hit(command: list[str]) -> str:
    return f"the Dart scan runs `{' '.join(command)}`, not one `dart-decimate` command that Hard Eng can judge: run `dart-decimate check .` directly or through `bun x`"


def subcommand_hit(command: list[str]) -> str:
    return f"Dart Decimate subcommand {command[1:2] and command[1]} is a scan that is not judged: run `dart-decimate check` on a scan gate"


def named_hits(gate: Gate, hits: list[str]) -> list[str]:
    return [f"gate {gate['name']}: {hit}" for hit in hits]


def other_folder_hits(gate: Gate, folder: str) -> list[str]:
    return [
        f"gate {gate['name']}: Dart Decimate scans `{folder}`, not the gate folder, and reads the settings of that folder: scan `.` and give the folder its own gate group"
    ]


def decimate_gate_hits(
    run: tuple[Path, str | None, frozenset[str], Gate, float],
    defaults: Future[dict[str, object]],
) -> list[str]:
    directory, config, children, gate, timeout = run
    hits = decimate_hits(directory, config, children, defaults.result(), timeout)
    return [f"gate {gate['name']} ({directory.name}): {hit}" for hit in hits]


def run_task(task: Task) -> list[str]:
    return task()


def validate_resolved(
    root: Path,
    groups: list[Group],
    timeout: float,
    every: list[Group] | None = None,
    only: Gate | None = None,
) -> None:
    """Run in the full check after the tools are installed; the Stop hook never runs it. `groups` are judged, `every` names all groups, so a parent knows its children."""
    every = groups if every is None else every
    with ThreadPoolExecutor(max_workers=8) as pool:
        defaults = Defaults(pool, root, timeout)
        tasks = [
            task
            for group in groups
            for gate in group["checks"]
            if only is None or gate is only
            for task in (
                *ruff_tasks((root, every, group, gate), defaults, timeout),
                *fallow_tasks((root, every, group, gate), defaults, timeout),
                *decimate_tasks((root, every, group, gate), defaults, timeout),
            )
        ]
        refused = [hit for found in pool.map(run_task, tasks) for hit in found]
    if refused:
        raise ValueError(
            "HE-NO-SWITCH-OFF: The settings that Ruff, Fallow and Dart Decimate print switch a check off, raise a limit or drop files:\n"
            + "\n".join(f"  {line}" for line in dict.fromkeys(refused))
        )


def judge_before_run(
    root: Path, group: Group, gate: Gate, groups: list[Group] | None, timeout: float
) -> None:
    """Judge the Fallow settings again right before Fallow starts, so a script that ran earlier in the check cannot change them after the first judge."""
    try:
        judged = direct(gate["command"], root / group["path"])
    except ValueError:
        judged = None
    scanner = scan_command(root / group["path"], gate)
    scan = group.get("language") == "dart" and gate.get("role") in SCAN_ROLES
    if (judged and judged[0] == "fallow") or scan or scanner[:1] == ["dart-decimate"]:
        validate_resolved(root, [group], timeout, groups, gate)
