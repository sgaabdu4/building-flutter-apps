"""Run native gate commands and handle the three agreed hook events."""

import fcntl
import os
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Generator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from pathlib import Path
from typing import IO, TYPE_CHECKING

import swift_setup
from ci_jobs import (
    NO_LANGUAGES,
    LanguageFilter,
    add_language_filters,
    add_shard_option,
    language_filter,
    language_groups,
)
from dart_boundaries import validate_dart_boundaries, validate_dart_typing
from debt import OUTPUTS, remember, ruff_check
from dependency_graph import SOURCE_SUFFIXES, child_groups
from gate_config import (
    Gate,
    Group,
    Report,
    generated_sources,
    nonproduction_source,
)
from project_files import keeping, stop_keeping
from project_setup import package_script_arguments as test_arguments
from python_setup import (
    leave_out_children,
    pytest_options,
    require_import_contract,
    validate_pyrefly,
)
from tool_setup import lost_scanner_note, managed_command, provision_tools
from untrusted_input import (
    next_route_types,
    project_command,
    reject_jsdoc_casts,
    typescript_projects,
    validate_typescript,
)

if TYPE_CHECKING:
    from argparse import Namespace

ROOT = Path(__file__).resolve().parents[1]
FAILED_GATES: list[str] = []
CHANGED_DART: dict[str, list[str]] = {}
RECORDING = threading.Event()
TEST_REPORTS = {"python-tests", "lcov-tests", "dart-tests", "xcode-tests"}
SUITE_FILTERS = {
    "python": "--lf --last-failed --deselect --stepwise --sw --ignore --ignore-glob",
    "javascript": "--test-only --test-name-pattern --test-skip-pattern --testNamePattern "
    "--testPathPattern --testPathPatterns --testPathIgnorePatterns --grep --fgrep "
    "--changed --onlyChanged --findRelatedTests --related --onlyFailures "
    "--shard --project --selectProjects",
    "dart": "--name --plain-name --tags --exclude-tags --total-shards --shard-index",
}


def validate_typing(
    directory: Path,
    language: str | None,
    sources: list[str] | tuple[str, ...] = (),
    package_root: Path | None = None,
) -> None:
    if language == "python":
        validate_pyrefly(directory, ROOT)
    elif language == "dart":
        validate_dart_typing(directory, sources, package_root)


def reject_test_filters(
    command: list[str], directory: Path, language: str | None
) -> None:
    if language == "swift":
        return swift_setup.reject_test_filters(command)
    arguments = test_arguments(command, directory)
    short_flags: tuple[str, ...] = ("-n", "-N", "-t", "-x")
    if language == "python":
        short_flags = ()
        for index, argument in enumerate(arguments):
            if Path(argument).name in {"pytest", "py.test"}:
                arguments = arguments[index + 1 :]
                arguments += shlex.split(os.environ.get("PYTEST_ADDOPTS", ""))
                arguments += pytest_options(directory)
                short_flags = ("-k", "-m")
                break
    elif language == "javascript":
        short_flags = ("-t", "-g", "-f")
    long_flags = SUITE_FILTERS.get(language or "", SUITE_FILTERS["dart"]).split()
    for argument in arguments:
        if (
            argument.split("=", 1)[0] in long_flags
            or argument.startswith(short_flags)
            or (language == "python" and "::" in argument)
        ):
            raise ValueError(
                f"Focused test selection is not allowed in the full-suite gate: {argument}"
            )


def production_files(
    directory: Path, group: Group, *, include_tests: bool = False
) -> set[Path]:
    language, sources = group.get("language"), group.get("sources")
    if language not in SOURCE_SUFFIXES or not isinstance(sources, list) or not sources:
        raise ValueError(
            "Test packages must declare their language and production sources"
        )
    files = set()
    for source in sources:
        if not isinstance(source, str) or not source:
            raise ValueError("Production sources must be nonempty paths")
        root = (directory / source).resolve()
        if not root.is_relative_to(directory) or not root.exists():
            raise ValueError(
                f"Production source must exist inside its package: {source}"
            )
        for file in [root] if root.is_file() else root.rglob("*"):
            if file.is_file() and file.suffix in SOURCE_SUFFIXES[language]:
                if file.name.endswith((".d.ts", ".d.mts", ".d.cts")) or (
                    not include_tests
                    and nonproduction_source(file.relative_to(directory))
                ):
                    continue
                resolved = file.resolve()
                if not resolved.is_relative_to(directory):
                    raise ValueError(
                        f"Production source points outside its package: {file}"
                    )
                files.add(resolved)
    excluded = generated_sources(
        directory,
        [] if include_tests else [str(file.relative_to(directory)) for file in files],
    )
    files -= {directory / name for name in excluded} | swift_setup.unchanged_starters(
        files
    )
    if not files:
        raise ValueError("Production sources contain no supported source files")
    return files


def without_fixes(command: list[str]) -> list[str]:
    """`fix = true` in ruff's settings makes `ruff check` rewrite files and exit 0."""
    tool = ruff_check(command)
    if tool < 0:
        return command
    return [*command[: tool + 2], "--no-fix", *command[tool + 2 :]]


def prepare_command(
    group: Group, gate: Gate, timeout: float, groups: list[Group] | None = None
) -> list[str]:
    from reports import osv_lockfiles

    command = osv_lockfiles(
        managed_command(gate["command"], ROOT / group["path"]), ROOT / group["path"]
    )
    if not command:
        return []
    from hot_paths import semgrep_options

    command = without_fixes(semgrep_options(ROOT, group, gate, command))
    if command[0] == "biome" and "." in command:
        from project_setup import javascript_files

        files = javascript_files(
            ROOT / group["path"], biome_children(group, gate, groups or [])
        )
        if not files:
            return []
        if gate.get("role") == "typing-style":
            reject_jsdoc_casts(ROOT / group["path"], files)
        command = [
            value
            for argument in command
            for value in (files if argument == "." else [argument])
        ]
    if gate.get("role") == "types":
        directory = ROOT / group["path"]
        language = group.get("language")
        validate_typing(directory, language, group.get("sources", []))
        if language == "python":
            from project_setup import python_interpreter

            native = (
                "pyrefly.toml"
                if (directory / "pyrefly.toml").exists()
                else "pyproject.toml"
            )
            scope: Group = {
                **group,
                "sources": [
                    *group.get("sources", []),
                    *(
                        name
                        for name in ("test", "tests")
                        if (directory / name).is_dir()
                    ),
                ],
            }
            command = [
                *command,
                "--config",
                native,
                "--python-interpreter-path",
                python_interpreter(directory, timeout),
                *map(
                    str, sorted(production_files(directory, scope, include_tests=True))
                ),
            ]
        elif language == "javascript":
            next_route_types(directory, timeout)
            expected = production_files(directory, group)
            validate_typescript(ROOT, command, directory, expected, timeout)
    validate_dart_boundaries(command, ROOT / group["path"], timeout)
    require_import_contract(ROOT / group["path"], group, gate)
    return command


def prepare_reports(
    group: Group,
    report: Report,
    kind: str | None,
    tests: bool,
    scanner: str | None,
    command: list[str],
) -> tuple[Path, Path | None, Path, set[Path]]:
    coverage_path = None
    expected_sources = set()
    supported = TEST_REPORTS if tests else {scanner}
    names = ("tests", "coverage") if tests else ("path",)
    if kind not in supported or any(
        not isinstance(report.get(name), str) or not report[name] for name in names
    ):
        raise ValueError("Check must declare complete supported reports")
    directory = (ROOT / group["path"]).resolve()
    paths = [(directory / report[name]).resolve() for name in names]
    if len(set(paths)) != len(paths) or any(
        not path.is_relative_to(directory) or path == directory for path in paths
    ):
        raise ValueError("Reports must be separate package files")
    report_path = paths[0]
    if tests:
        coverage_path = paths[1]
        expected_sources = production_files(directory, group)
        reject_test_filters(command, directory, group["language"])
    elif scanner == "import-linter" and any(
        argument.split("=", 1)[0] == "--contract" for argument in command
    ):
        raise ValueError("Import Linter must run all configured contracts")
    if scanner in {"performance-junit", "performance-dart"}:
        reject_test_filters(command, directory, group.get("language"))
        from gate_config import performance_suites

        for suite in performance_suites(command):
            if not (directory / suite).is_dir():
                raise ValueError(
                    f"HE-PERFORMANCE-SUITE: {suite} does not exist; add a test there "
                    "with a real workload and a time budget, or, after review, record a "
                    "performance_exception and remove this check "
                    "(.agents/skills/he/references/gates.md). "
                    "A new project starts without one: the first code change adds it"
                )
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
    return report_path, coverage_path, directory, expected_sources


def run_gate(
    group: Group,
    gate: Gate,
    timeout: float,
    output_lock: AbstractContextManager[object],
    groups: list[Group] | None = None,
    related_base: str | None = None,
) -> bool:
    """Run a gate under its own limit and record how long a pass took."""
    from gate_times import gate_limit, record_gate_time
    from process_group import install_key, note_install

    key = f"{group['path']}/{gate['name']}" + ("@related" if related_base else "")
    if part := gate.get("part"):
        key += "@shard" if part.isdecimal() else "@merge"
    limit = gate_limit(ROOT, key, timeout)
    name = f"{group['path']}/{gate['name']}"
    OUTPUTS.pop(name, None)
    files = CHANGED_DART.get(name)
    if files is not None and changed_dart_pass(group, gate, files, limit, groups):
        return False
    started = time.monotonic()
    failed = run_limited_gate(group, gate, limit, output_lock, groups, related_base)
    if not RECORDING.is_set():
        from debt import judge

        failed = judge(ROOT, group, gate, failed, OUTPUTS.get(name, ""))
    note_install(install_key(group), gate.get("role"), failed)
    if failed:
        FAILED_GATES.append(key)
        if note := lost_scanner_note(OUTPUTS.get(name, "")):
            with output_lock:
                print(note, flush=True)
    else:
        record_gate_time(ROOT, key, time.monotonic() - started)
    return failed


def changed_dart_pass(
    group: Group,
    gate: Gate,
    files: list[str],
    timeout: float,
    groups: list[Group] | None,
) -> bool:
    """A quick check passes the Dart analysis on its changed files alone; a finding there leaves the verdict, and each record, to the package run."""
    from gate_schedule import DART_ANALYSIS

    if gate["command"] not in DART_ANALYSIS:
        return False
    started = time.monotonic()
    first: Gate = {**gate, "command": [*DART_ANALYSIS[0], *files]}
    try:
        command = prepare_command(group, first, timeout, groups)
        with tempfile.TemporaryFile(mode="w+") as log:
            passed = (
                not files
                or not run_projects(
                    group, first, command, ROOT / group["path"], timeout, log, log
                ).returncode
            )
    except (ImportError, OSError, TypeError, ValueError, subprocess.SubprocessError):
        passed = False
    if not passed:
        print(
            f"Dart analysis of the changed files @ {group['path']} did not pass; "
            "the package analysis decides.",
            flush=True,
        )
        return False
    print(
        f"PASS {gate['name']} (changed Dart files only: {len(files)}; elapsed "
        f"{time.monotonic() - started:.3f}s) @ {group['path']}; "
        "the full check analyses the package.",
        flush=True,
    )
    return True


def run_projects(
    group: Group,
    gate: Gate,
    command: list[str],
    directory: Path,
    timeout: float,
    stdout: IO[str] | None,
    stderr: IO[str],
) -> subprocess.CompletedProcess[bytes]:
    """Run the gate once, or a TypeScript types gate once per referenced config."""
    if not command:
        return subprocess.CompletedProcess(command, 0)
    from gitleaks_scan import run_gate_command

    projects: list[list[str]] = [[]]
    if gate.get("role") == "types" and group.get("language") == "javascript":
        projects = typescript_projects(ROOT, command, directory)
    results = [
        run_gate_command(
            gate.get("role"),
            project_command(command, project),
            directory,
            timeout,
            stdout,
            stderr,
        )
        for project in projects
    ]
    return next((result for result in results if result.returncode), results[-1])


def gate_scanner(group: Group, gate: Gate, scanner: str | None) -> str | None:
    scanner = {
        "secrets-files": "gitleaks",
        "secrets-history": "gitleaks",
        "security": "semgrep",
        "vulnerabilities": "osv",
        "freshness": "freshness",
        "container-vulnerabilities": "osv-image",
        "react": "react-doctor",
        "deployment": "trivy",
    }.get(gate.get("role", ""), scanner)
    return {
        ("python", "imports"): "import-linter",
        ("python", "dependencies"): "deptry",
        ("python", "duplicates"): "jscpd",
        ("swift", "duplicates"): "jscpd",
        ("dart", "dead-code-duplicates"): "dart-decimate",
        ("javascript", "dead-code-duplicates"): "fallow",
    }.get((group.get("language", ""), gate.get("role", "")), scanner)


def shard_command(
    group: Group,
    gate: Gate,
    command: list[str],
    coverage: Path | None,
    timeout: float,
) -> tuple[list[str], Path | None]:
    """A shard gate runs its own files and skips the coverage minimum; others pass through."""
    if not gate.get("part"):
        if gate.get("shards"):
            from shards import require_default_settings, require_no_path

            require_default_settings(ROOT, group, gate, command, variables=False)
            require_no_path(ROOT, group, gate, command)
        return command, coverage
    from shards import part_command

    return part_command(ROOT, group, gate, command, coverage, timeout)


def shard_reports(group: Group, gate: Gate) -> None:
    if gate.get("part"):
        from shards import keep_reports

        keep_reports(ROOT, group, gate)


def remembered_output(
    group: Group,
    gate: Gate,
    command: list[str],
    result: subprocess.CompletedProcess[bytes] | None,
    log: IO[str],
) -> str:
    """The text of a gate log, with the step to take first when a Dart analysis lacks generated files."""
    from process_group import generated_files_note

    log.seek(0)
    text = log.read()
    note = generated_files_note(command, result.returncode, text) if result else ""
    return note + remember(group, gate, text)


def run_limited_gate(
    group: Group,
    gate: Gate,
    timeout: float,
    output_lock: AbstractContextManager[object],
    groups: list[Group] | None = None,
    related_base: str | None = None,
) -> bool:
    started = time.monotonic()
    print(f"CHECK {group['path']}/{gate['name']}", flush=True)
    try:
        report_path = coverage_path = None
        directory = ROOT / group["path"]
        expected_sources: set[Path] = set()
        command = prepare_command(group, gate, timeout, groups)
        if not command:
            reason = (
                ": uv.lock locks no third-party package to scan"
                if gate.get("role") == "vulnerabilities"
                else " by selected child checks"
            )
            print(
                f"COVERED {gate['name']}{reason}; elapsed {time.monotonic() - started:.3f}s"
            )
            return False
        from reports import (
            SCANNERS,
            emit_dart_test_failure,
            related_command,
            scanner_result,
            validate_scanner_log,
        )

        report = gate.get("report", {})
        kind = report.get("type", "")
        tests = gate.get("role") == "tests"
        scanner = gate_scanner(group, gate, kind if kind in SCANNERS else None)
        if tests or scanner:
            report_path, coverage_path, directory, expected_sources = prepare_reports(
                group, report, kind, tests, scanner, command
            )
        command = leave_out_children(ROOT, command, group, gate)
        command, coverage_path = related_command(
            command, coverage_path, gate, groups or [group], directory, related_base
        )
        command, coverage_path = shard_command(
            group, gate, command, coverage_path, timeout
        )
        capture = (tests and kind == "dart-tests" and report.get("stdout", True)) or (
            scanner and report.get("stdout") is True
        )
        result = None
        with tempfile.TemporaryFile(
            mode="w+", encoding="utf-8", errors="replace"
        ) as log:
            try:
                with (
                    report_path.open("w")
                    if capture and report_path is not None
                    else nullcontext()
                ) as output:
                    result = run_projects(
                        group,
                        gate,
                        command,
                        directory,
                        timeout,
                        output if capture else log,
                        log,
                    )
            finally:
                with output_lock:
                    print(f"OUTPUT {group['path']}/{gate['name']}", flush=True)
                    sys.stdout.write(
                        remembered_output(group, gate, command, result, log)
                    )
                    emit_dart_test_failure(result, tests, kind, report_path)
            validate_scanner_log(scanner, log)
        shard_reports(group, gate)
        if scanner and report_path is not None:
            report_args = (gate, report_path, command, directory, timeout)
            scanner_result(result.returncode == 0, scanner, *report_args)
        from process_group import parallel_hint, stopped_note
        from reports import check_coverage, completed_tests

        if (
            result.returncode == 0
            and tests
            and coverage_path is not None
            and report_path is not None
            and not completed_tests(report_path, kind)
        ):
            raise ValueError("No tests actually ran (empty or entirely skipped report)")
        if result.returncode == 0 and coverage_path is not None:
            check_coverage(coverage_path, kind, directory, expected_sources)
        stop = stopped_note(result.returncode)
        print(
            f"{'PASS' if result.returncode == 0 else 'FAIL'} {gate['name']} "
            f"(exit {result.returncode}; elapsed {time.monotonic() - started:.3f}s)"
            f" @ {group['path']}"
            + (stop or parallel_hint(result.returncode, tests, command, report_path)),
            flush=True,
        )
        return result.returncode != 0
    except (
        ImportError,
        OSError,
        TypeError,
        ValueError,
        ET.ParseError,
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError,
    ) as error:
        unrun = isinstance(error, (ImportError, OSError, subprocess.TimeoutExpired))
        text = str(error) if unrun else remember(group, gate, str(error))
        print(
            f"FAIL {gate['name']}: {text}; "
            f"elapsed {time.monotonic() - started:.3f}s @ {group['path']}"
        )
        return True


@contextmanager
def check_lock(root: Path) -> Generator[IO[str]]:
    """Gates write fixed report paths, so one check runs per checkout at a time."""
    from process_group import check_lock_file

    with check_lock_file(root) as (lock, held):
        if held:
            print("Waiting for another Hard Eng check in this checkout", flush=True)
            fcntl.flock(lock, fcntl.LOCK_EX)
        yield lock


def biome_children(group: Group, gate: Gate, groups: list[Group]) -> tuple[Path, ...]:
    command = gate["command"]
    if (
        group["path"] != "."
        or group.get("language") != "javascript"
        or gate.get("role") not in {"format-lint", "focused-tests", "typing-style"}
        or gate.get("report")
        or command[:2] not in (["biome", "ci"], ["biome", "lint"])
        or "." not in command
        or any(
            arg not in {".", "--error-on-warnings"} and not arg.startswith("--only=")
            for arg in command[2:]
        )
    ):
        return ()
    return tuple(
        ROOT / child["path"]
        for child in child_groups(group, gate.get("role"), groups)
        if any(
            check.get("role") == gate.get("role") and check["command"] == command
            for check in child["checks"]
        )
    )


def proven_elsewhere(base: str | None, quick: bool = False) -> bool:
    """A merged PR or verified upstream release already proved this change."""
    from update import check_scaffold_update

    if base is None:
        return False
    if os.environ.get("GITHUB_ACTIONS") == "true":
        from ci_usage import reused_pull_request

        if head := reused_pull_request(ROOT, base):
            print(
                f"Commit {head} passed the required checks on this exact tree; "
                "not repeating them.",
                flush=True,
            )
            return True
    return check_scaffold_update(ROOT, base, sources=not quick)


def plan_base(base: str | None, plan_stage: str | None) -> str | None:
    from shipping import passed_branch_point

    if base is not None or plan_stage is None:
        return base
    if point := passed_branch_point(ROOT):
        print(
            f"Base-branch commit {point} passed the required CI checks; "
            "checking only changes since it.",
            flush=True,
        )
    return point


def run_gates(groups: list[Group], timeout: float, related: str | None) -> bool | None:
    """Gate chains of separate packages overlap; None when dependency setup failed."""
    from gate_config import parse_config
    from gate_schedule import run_checks

    output_lock = threading.Lock()
    FAILED_GATES.clear()
    config = parse_config((ROOT / "hard-eng.gates.json").read_text())
    return run_checks(
        [(group, gate) for group in groups for gate in group["checks"]],
        lambda group, gate: run_gate(
            group, gate, timeout, output_lock, groups, related
        ),
        config["packages"],
    )


@keeping("references", "listings")
def check(
    timeout: float | None = None,
    base: str | None = None,
    plan_stage: str | None = None,
    *,
    verify_plan: bool = True,
    dependents: bool = True,
    related_tests: bool = False,
    quick: bool = False,
    languages: LanguageFilter = NO_LANGUAGES,
    shard: str | None = None,
) -> int:
    from ci_setup import push_base, require_ci_base
    from gate_config import load_groups, parse_config
    from process_group import clean_start, read_installed, record_pass, save_installed
    from reports import quick_groups
    from shipping import gate_budget

    require_ci_base(base)
    base = push_base(ROOT, base)
    parse_config((ROOT / "hard-eng.gates.json").read_text())
    if shard == "merge":
        from shards import proven_shard

        if proven_shard(ROOT):
            return 0
    elif proven_elsewhere(base, quick):
        if shard:
            from shards import mark_shard

            mark_shard(ROOT, shard, True)
        return 0

    with check_lock(ROOT) as lock:
        installed = read_installed(lock, ROOT)
        partial = (
            quick
            or languages != NO_LANGUAGES
            or not dependents
            or related_tests
            or shard is not None
        )
        start = clean_start(lock, ROOT, base, plan_stage, partial)
        groups = load_groups(ROOT, plan_base(base, plan_stage), dependents=dependents)
        groups = quick_groups(language_groups(groups, languages), quick, installed)
        if shard:
            from shards import shard_groups

            groups = shard_groups(groups, shard)
        from debt import require_shrink

        require_shrink(ROOT, base)
        timeout = timeout or gate_budget(ROOT)
        import change_size
        import plans
        from comments import validate_comments, validate_suppressions

        if verify_plan:
            plan_stage = change_size.judged_stage(ROOT, base, plan_stage)
        validate_comments(ROOT, base)
        validate_suppressions(ROOT, base)
        plans.validate_records(ROOT, base)
        before_gates(groups, quick, base)
        stop_keeping("listings")
        if shard != "merge":
            provision_tools(ROOT, groups, timeout)
        related = base if related_tests else None
        started, failed = time.time(), run_gates(groups, timeout, related) is not False
        save_installed(lock, installed, ROOT)
        failed |= verify_plan and change_size.plan_skips(
            ROOT, base, groups, int(started)
        )
        plans.report_stage(failed, plan_stage, FAILED_GATES, quick)
        record_pass(lock, ROOT, start, failed)
        if shard:
            from shards import mark_shard

            mark_shard(ROOT, shard, False)
        return int(failed)


def before_gates(groups: list[Group], quick: bool, base: str | None) -> None:
    """A full check prints the commit note; a quick check with a base names the changed Dart files of its first runs."""
    CHANGED_DART.clear()
    if not quick:
        import change_size

        change_size.commit_note(ROOT)
    elif base:
        from gate_config import changed_files
        from gate_schedule import changed_dart

        CHANGED_DART.update(changed_dart(ROOT, groups, changed_files(ROOT, base)))


def impact(base: str, languages: LanguageFilter = NO_LANGUAGES) -> int:
    """Tell CI the runner, the tools and whether Swift is affected, before tools."""
    from ci_jobs import impact_outputs

    return impact_outputs(ROOT, base, proven_elsewhere, languages)


def pre_push() -> int:
    from ship_actions import pre_push as verify_push

    return verify_push(ROOT)


def deliver(args: "Namespace") -> int:
    if args.command == "adopt":
        return adopt()
    if args.command == "ci-usage":
        from ci_usage import ci_usage

        return ci_usage(ROOT, args.repo, args.days, args.runs)
    if args.command == "hot-paths":
        from hot_paths import scan_all

        return scan_all(ROOT, paths=args.paths)
    if args.command == "gap-issue":
        from gap_issue import file_gap

        return file_gap(ROOT, args.text)
    if args.command == "challenge":
        from challenge import challenge

        return challenge(ROOT, args.base, args.host)
    from ship_actions import run

    return run(ROOT, args.plan, args.pr, args.stage, args.worktree, args.merge_method)


def adopt() -> int:
    """Record the findings the existing code fails with as shrink-only debt."""
    from debt import record, settled_run
    from gate_config import load_groups
    from shipping import gate_budget
    from tool_setup import ensure_python_runtime

    ensure_python_runtime()
    with check_lock(ROOT):
        groups = load_groups(ROOT)
        timeout = gate_budget(ROOT)
        provision_tools(ROOT, groups, timeout)
        RECORDING.set()
        try:
            settled_run(ROOT, lambda: run_gates(groups, timeout, None))
        finally:
            RECORDING.clear()
        return record(ROOT, groups, set(FAILED_GATES), OUTPUTS)


def check_command(args: "Namespace") -> int:
    from process_group import exit_when_stopped
    from tool_setup import ensure_python_runtime

    if args.shard != "merge":
        ensure_python_runtime()
    exit_when_stopped()
    return check(
        base=args.base,
        plan_stage=args.plan_stage,
        dependents=not args.without_dependents,
        related_tests=args.related_tests,
        quick=args.quick,
        languages=language_filter(args),
        shard=args.shard,
    )


def main() -> int:
    import argparse

    if "pre-push" in (Path(sys.argv[0]).name, *sys.argv[1:2]) and not {
        "-h",
        "--help",
    } & set(sys.argv[1:]):
        return pre_push()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.set_defaults(apply=False, merge=True)
    commands = parser.add_subparsers(dest="command", required=True)
    checks = add_shard_option(
        add_language_filters(
            commands.add_parser("check", help="Run applicable native checks")
        )
    )
    checks.add_argument("--base", help="Git base; unknown impact runs all checks")
    checks.add_argument("--plan-stage", choices=("Draft", "Ready", "Complete"))
    checks.add_argument(
        "--without-dependents",
        action="store_true",
        help="Check changed packages only; CI checks their dependents",
    )
    checks.add_argument(
        "--related-tests",
        action="store_true",
        help="Run only JavaScript tests related to the change; CI runs them all",
    )
    checks.add_argument(
        "--quick",
        action="store_true",
        help="Run only format, lint, types and the file secret scan; the Stop hook uses it",
    )
    impacts = add_language_filters(
        commands.add_parser(
            "impact",
            help="Print docs_only, tools, runner and apple for the change, for CI jobs",
        )
    )
    impacts.add_argument("--base", required=True)
    commands.add_parser("pre-push", help="Verify the actual commits being pushed")
    commands.add_parser("adopt", help="Record old findings once as shrink-only debt")
    usage = commands.add_parser(
        "ci-usage", help="Report billed GitHub Actions minutes by workflow and job"
    )
    usage.add_argument("--repo", help="owner/name; defaults to origin")
    usage.add_argument("--days", type=int, default=14)
    usage.add_argument(
        "--runs", type=int, help="Use the newest N runs instead of --days"
    )
    commands.add_parser(
        "hot-paths",
        help="List known slow patterns in the named files, else the whole repository",
    ).add_argument("paths", nargs="*")
    mutating = commands.add_parser(
        "mutation",
        help="Report changed lines whose tests miss small deliberate bugs",
    )
    mutating.add_argument("--base", required=True)
    mutating.add_argument("--seconds", type=float, help="Stop after this many seconds")
    mutating.add_argument(
        "--in-place",
        action="store_true",
        help="Mutate this checkout, which must be disposable, instead of a snapshot",
    )
    updating = commands.add_parser(
        "update",
        help="Install the newest CI-verified Hard Eng revision and record the result",
    )
    updating.add_argument(
        "--apply", action="store_true", help="Run inside the supervising update process"
    )
    commands.add_parser(
        "update-pr",
        help="Push the prepared Hard Eng update branch, open its PR and merge it once its checks pass; --no-merge prints the merge command instead",
    ).add_argument("--no-merge", dest="merge", action="store_false")
    challenging = commands.add_parser(
        "challenge",
        help="Have the other agent CLI review this branch read-only and record the result",
    )
    challenging.add_argument(
        "--base", help="Git comparison base; defaults to the merge base"
    )
    challenging.add_argument(
        "--host",
        choices=("claude", "codex"),
        help="The running agent, only when it cannot be detected",
    )
    commands.add_parser(
        "gap-issue", help="File a Hard Eng issue for a check it lacks"
    ).add_argument("text", help="the missing check, described generically")
    shipping = commands.add_parser(
        "ship", help="Verify PR delivery or perform guarded shipping actions"
    )
    shipping.add_argument(
        "--plan", help="Task plan; optional only when `check` reports Size: small"
    )
    shipping.add_argument("--pr", required=True)
    shipping.add_argument(
        "--stage", choices=("ready", "merge", "delivered", "cleanup"), default="ready"
    )
    shipping.add_argument("--worktree", help="Task worktree in the same repository")
    shipping.add_argument("--merge-method", choices=("rebase",), default="rebase")
    for event in ("session", "stop"):
        hook = commands.add_parser(event, help=f"Handle a native {event} hook")
        hook.add_argument("agent", choices=("claude", "codex"))
    args = parser.parse_args()
    if args.command == "check":
        return check_command(args)
    if args.command == "impact":
        return impact(args.base, language_filter(args))
    if args.command == "mutation":
        from ship_actions import mutate

        return mutate(ROOT, args.base, args.seconds, args.in_place, production_files)
    if args.command in {"update", "update-pr"}:
        from update_runner import update_main

        return update_main(ROOT, args.command == "update-pr", args.apply, args.merge)
    if args.command in {
        "adopt",
        "challenge",
        "ship",
        "gap-issue",
        "ci-usage",
        "hot-paths",
    }:
        return deliver(args)
    from agent_hooks import handle_event

    return handle_event(ROOT, args.command, args.agent)


def run() -> None:
    """Run the command line; print one `Hard Eng:` line and exit 1 on an error."""
    try:
        # ssh under `git push` shares this pipe and leaves it non-blocking.
        for stream in (sys.stdout, sys.stderr):
            os.set_blocking(stream.fileno(), True)
        raise SystemExit(main())
    except (
        ImportError,
        OSError,
        TypeError,
        ValueError,
        KeyError,
        subprocess.SubprocessError,
    ) as error:
        print(f"Hard Eng: {error}", file=sys.stderr)
        raise SystemExit(1) from error
