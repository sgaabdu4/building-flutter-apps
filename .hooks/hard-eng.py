#!/usr/bin/env python3
"""Run native gate commands and handle the three agreed hook events."""

import configparser
import fcntl
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Generator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import AbstractContextManager, contextmanager, nullcontext
from pathlib import Path
from typing import TypedDict, cast
from urllib.parse import unquote, urljoin, urlparse

from gate_config import (
    Gate,
    Group,
    JsonObject,
    Report,
    dart_rule_settings,
    generated_sources,
    nonproduction_source,
    validate_dart_boundaries,
    validate_dart_exclusions,
)
from project_setup import package_script_arguments as test_arguments
from tool_setup import managed_command, provision_tools

DartAnalyzer = TypedDict(
    "DartAnalyzer",
    {"exclude": list[str], "errors": dict[str, str], "language": dict[str, bool]},
    total=False,
)
DartLinter = TypedDict(
    "DartLinter", {"rules": dict[str, bool] | list[str]}, total=False
)
DartOptions = TypedDict(
    "DartOptions",
    {"include": str | list[str], "analyzer": DartAnalyzer, "linter": DartLinter},
    total=False,
)


ROOT = Path(__file__).resolve().parents[1]
DART_TYPING: dict[str, dict[str, dict[str, bool] | list[str]]] = {
    "analyzer": {
        "exclude": [],
        "language": {
            "strict-inference": True,
        },
    },
    "linter": {
        "rules": {
            "no_dynamic_casts": True,
            "no_raw_types": True,
            "avoid_annotating_with_dynamic": True,
            "avoid_dynamic_calls": True,
            "strict_top_level_inference": True,
            "unawaited_futures": True,
        }
    },
}


def dart_options(path: Path) -> DartOptions:
    try:
        import yaml
    except ImportError as error:
        raise ValueError(
            "Dart configuration checks require PyYAML in the Python environment"
        ) from error
    try:
        options = yaml.safe_load(path.read_text())
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid Dart analysis settings: {path}") from error
    if not isinstance(options, dict):
        raise TypeError(f"Dart analysis settings must be a mapping: {path}")
    return cast(DartOptions, options)


def validate_dart_includes(
    path: Path, directory: Path, seen: set[Path] | None = None
) -> None:
    seen = set() if seen is None else seen
    path = path.resolve()
    if path in seen:
        raise ValueError(f"Recursive Dart analysis include: {path}")
    seen.add(path)
    options = dart_options(path)
    from gate_config import validate_dart_plugins

    validate_dart_plugins(cast(JsonObject, options))
    analyzer = options.get("analyzer", {})
    if {"strict-casts", "strict-raw-types"} & analyzer.get("language", {}).keys():
        raise ValueError(
            f"Remove obsolete Dart language flags; use no_dynamic_casts and no_raw_types: {path}"
        )
    validate_dart_exclusions(directory, analyzer.get("exclude", []))
    if any(value == "ignore" for value in analyzer.get("errors", {}).values()):
        raise ValueError(
            f"Dart strict analysis cannot exclude files or ignore diagnostics: {path}"
        )
    includes = options.get("include", [])
    for include in [includes] if isinstance(includes, str) else includes:
        if include.startswith("package:"):
            name, relative = include.removeprefix("package:").split("/", 1)
            registry = directory / ".dart_tool/package_config.json"
            packages = json.loads(registry.read_text())["packages"]
            package = next((item for item in packages if item["name"] == name), None)
            if package is None:
                raise ValueError(f"Unresolved Dart analysis include: {include}")
            uri = urljoin(
                urljoin(registry.as_uri(), package["rootUri"]).rstrip("/") + "/",
                package.get("packageUri", "lib/"),
            )
            uri = urlparse(urljoin(uri, relative))
            if uri.scheme != "file":
                raise ValueError(f"Unsupported Dart analysis include: {include}")
            included = Path(unquote(uri.path))
        else:
            included = path.parent / include
        validate_dart_includes(included, directory, seen.copy())


def validate_typing(
    directory: Path,
    language: str | None,
    sources: list[str] | tuple[str, ...] = (),
    package_root: Path | None = None,
) -> None:
    if language == "python":
        native = directory / "pyrefly.toml"
        options = (
            tomllib.loads(native.read_text())
            if native.exists()
            else tomllib.loads((directory / "pyproject.toml").read_text())
            .get("tool", {})
            .get("pyrefly", {})
        )
        if (
            options.get("preset") not in {"strict", "all"}
            or options.get("check-unannotated-defs", True) is not True
            or any(
                value in (False, "ignore")
                for value in options.get("errors", {}).values()
            )
            or options.get("ignore-missing-imports")
            or options.get("replace-imports-with-any")
            or options.get("replace-untyped-imports-with-any")
            or options.get("sub-config")
        ):
            raise ValueError(
                "Pyrefly requires strict checking without disabled diagnostics or Any import substitutions"
            )
    elif language == "dart":
        validate_dart_typing(directory, sources, package_root)


def validate_dart_typing(
    directory: Path, sources: list[str] | tuple[str, ...], package_root: Path | None
) -> None:
    options = dart_options(directory / "analysis_options.yaml")
    for section, groups in DART_TYPING.items():
        for group, settings in groups.items():
            section_options = cast(JsonObject, options).get(section)
            if not isinstance(section_options, dict):
                raise TypeError(f"Dart requires {section} settings")
            actual = section_options.get(group)
            if group == "rules":
                actual = dart_rule_settings(actual)
            if isinstance(settings, list):
                validate_dart_exclusions(directory, section_options.get(group, []))
                continue
            if not isinstance(actual, dict) or any(
                actual.get(key) != value for key, value in settings.items()
            ):
                raise ValueError(f"Dart requires strict {section}.{group} settings")
    validate_dart_includes(
        directory / "analysis_options.yaml", package_root or directory
    )
    for source in {*sources, "test", "tests"}:
        for nested in (directory / source).rglob("analysis_options.yaml"):
            if nested.parent != directory:
                validate_typing(
                    nested.parent, "dart", package_root=package_root or directory
                )


def reject_test_filters(
    command: list[str], directory: Path, language: str | None
) -> None:
    arguments = test_arguments(command, directory)
    if language == "python":
        short_flags = ()
        for index, argument in enumerate(arguments):
            if Path(argument).name in {"pytest", "py.test"}:
                arguments = arguments[index + 1 :]
                arguments += shlex.split(os.environ.get("PYTEST_ADDOPTS", ""))
                arguments += pytest_options(directory)
                short_flags = ("-k", "-m")
                break
        long_flags = {"--lf", "--last-failed", "--deselect", "--stepwise", "--sw"}
    elif language == "javascript":
        long_flags = {
            "--test-only",
            "--test-name-pattern",
            "--test-skip-pattern",
            "--testNamePattern",
            "--testPathPattern",
            "--testPathPatterns",
            "--testPathIgnorePatterns",
            "--grep",
            "--fgrep",
            "--changed",
            "--onlyChanged",
            "--findRelatedTests",
            "--related",
            "--onlyFailures",
        }
        short_flags = ("-t", "-g", "-f")
    else:
        long_flags = {"--name", "--plain-name", "--tags", "--exclude-tags"}
        short_flags = ("-n", "-N", "-t", "-x")
    for argument in arguments:
        if (
            argument.split("=", 1)[0] in long_flags
            or argument.startswith(short_flags)
            or (language == "python" and "::" in argument)
        ):
            raise ValueError(
                f"Focused test selection is not allowed in the full-suite gate: {argument}"
            )


def pytest_options(directory: Path) -> list[str]:
    for root in (directory, *directory.parents):
        for name in (
            "pytest.toml",
            ".pytest.toml",
            "pytest.ini",
            ".pytest.ini",
            "pyproject.toml",
            "tox.ini",
            "setup.cfg",
        ):
            path = root / name
            if path.is_file():
                options = pytest_config(path)
                if options is not None:
                    return shlex.split(options) if isinstance(options, str) else options
        if (root / ".git").exists():
            break
    return []


def pytest_config(path: Path) -> str | list[str] | None:
    if path.suffix == ".toml":
        config = tomllib.loads(path.read_text())
        if path.name == "pyproject.toml" and "pytest" not in config.get("tool", {}):
            return None
        section = (
            config.get("tool", {}).get("pytest", {})
            if path.name == "pyproject.toml"
            else config.get("pytest", {})
        )
        section = section.get("ini_options", section)
        value = section.get("addopts", [])
    else:
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(path)
        section = "tool:pytest" if path.name == "setup.cfg" else "pytest"
        if not parser.has_section(section) and path.name not in {
            "pytest.ini",
            ".pytest.ini",
        }:
            return None
        value = parser.get(section, "addopts", fallback="")
    if value is not None and not (
        isinstance(value, str)
        or isinstance(value, list)
        and all(isinstance(arg, str) for arg in value)
    ):
        raise TypeError("pytest addopts must be text or a list of arguments")
    return value


def production_files(
    directory: Path, group: Group, *, include_tests: bool = False
) -> set[Path]:
    extensions = {
        "python": {".py"},
        "javascript": {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"},
        "dart": {".dart"},
    }
    language, sources = group.get("language"), group.get("sources")
    if language not in extensions or not isinstance(sources, list) or not sources:
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
            if file.is_file() and file.suffix in extensions[language]:
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
    files -= {directory / name for name in excluded}
    if not files:
        raise ValueError("Production sources contain no supported source files")
    return files


def prepare_command(
    group: Group, gate: Gate, timeout: float, groups: list[Group] | None = None
) -> list[str]:
    command = managed_command(gate["command"], ROOT / group["path"])
    if gate.get("role") == "security" and "p/python" in command:
        index = command.index("p/python") + 1
        command = [
            *command[:index],
            "--config",
            str(ROOT / ".agents/skills/he/semgrep/python.yaml"),
            "--exclude-rule",
            "python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1",
            *command[index:],
        ]
    if command[0] == "biome" and "." in command:
        from project_setup import javascript_files

        files = javascript_files(
            ROOT / group["path"], biome_children(group, gate, groups or [])
        )
        if not files:
            return []
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
            validate_typescript(command, directory, group, timeout)
    validate_dart_boundaries(command, ROOT / group["path"], timeout)
    return command


def validate_typescript(
    command: list[str], directory: Path, group: Group, timeout: float
) -> None:
    result = subprocess.run(
        [*command, "--showConfig"],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    actual = json.loads(result.stdout)
    options = actual.get("compilerOptions", {})
    strict = (
        "noImplicitAny",
        "noImplicitThis",
        "strictNullChecks",
        "strictFunctionTypes",
        "strictBindCallApply",
        "strictPropertyInitialization",
        "strictBuiltinIteratorReturn",
        "useUnknownInCatchVariables",
        "alwaysStrict",
    )
    if (
        options.get("strict") is not True
        or any(options.get(name, True) is not True for name in strict)
        or options.get("checkJs") is not True
        or options.get("noCheck", False) is not False
    ):
        raise ValueError(
            "TypeScript requires all strict checks and JavaScript checking without noCheck"
        )
    files = {(directory / name).resolve() for name in actual.get("files", [])}
    expected = production_files(directory, group)
    if not {(directory / name).resolve() for name in expected} <= files:
        raise ValueError("TypeScript configuration omits declared production files")


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
    supported = {"python-tests", "lcov-tests", "dart-tests"} if tests else {scanner}
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
) -> bool:
    started = time.monotonic()
    print(f"CHECK {group['path']}/{gate['name']}", flush=True)
    try:
        report_path = coverage_path = None
        directory = ROOT / group["path"]
        expected_sources: set[Path] = set()
        command = prepare_command(group, gate, timeout, groups)
        if not command:
            print(
                f"COVERED {gate['name']} by selected child checks; elapsed {time.monotonic() - started:.3f}s"
            )
            return False
        from reports import SCANNERS, emit_dart_test_failure, validate_scanner_log

        report = gate.get("report", {})
        kind = report.get("type", "")
        tests = gate.get("role") == "tests"
        scanner = {
            "secrets-files": "gitleaks",
            "secrets-history": "gitleaks",
            "security": "semgrep",
            "vulnerabilities": "osv",
            "container-vulnerabilities": "osv-image",
            "react": "react-doctor",
            "deployment": "trivy",
        }.get(gate.get("role", ""), kind if kind in SCANNERS else None)
        scanner = {
            ("python", "imports"): "import-linter",
            ("python", "dependencies"): "deptry",
            ("python", "duplicates"): "jscpd",
            ("dart", "dead-code-duplicates"): "dart-decimate",
            ("javascript", "dead-code-duplicates"): "fallow",
        }.get((group.get("language", ""), gate.get("role", "")), scanner)
        if tests or scanner:
            report_path, coverage_path, directory, expected_sources = prepare_reports(
                group, report, kind, tests, scanner, command
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
                    from gitleaks_scan import run_gate_command

                    result = run_gate_command(
                        gate.get("role"),
                        command,
                        directory,
                        timeout,
                        output if capture else log,
                        log,
                    )
            finally:
                with output_lock:
                    print(f"OUTPUT {group['path']}/{gate['name']}", flush=True)
                    log.seek(0)
                    shutil.copyfileobj(log, sys.stdout)
                    emit_dart_test_failure(result, tests, kind, report_path)
            validate_scanner_log(scanner, log)
        if result.returncode == 0 and scanner and report_path is not None:
            if (
                scanner == "osv"
                and "--allow-no-lockfiles" in command
                and [arg for arg in command if arg.startswith("--lockfile")]
                == ["--lockfile=pnpm-lock.yaml"]
            ):
                from reports import validate_osv

                validate_osv(report_path, empty_pnpm=directory)
            else:
                SCANNERS[scanner](report_path)
        from reports import completed_tests, line_coverage, parallel_hint

        if (
            result.returncode == 0
            and tests
            and report_path is not None
            and not completed_tests(report_path, kind)
        ):
            raise ValueError("No tests actually ran (empty or entirely skipped report)")
        if result.returncode == 0 and coverage_path is not None:
            covered, total = line_coverage(
                coverage_path, kind, directory, expected_sources
            )
            print(
                f"Line coverage: {covered}/{total} ({100 * covered / total:.2f}%; minimum 70%)"
            )
            if covered * 100 < total * 70:
                raise ValueError("Line coverage is below the required 70%")
        print(
            f"{'PASS' if result.returncode == 0 else 'FAIL'} {gate['name']} "
            f"(exit {result.returncode}; elapsed {time.monotonic() - started:.3f}s)"
            + parallel_hint(result.returncode, tests, command),
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
        print(
            f"FAIL {gate['name']}: {error}; elapsed {time.monotonic() - started:.3f}s"
        )
        return True


@contextmanager
def check_lock(root: Path) -> Generator[None]:
    """Gates write fixed report paths, so one check runs per checkout at a time."""
    name = subprocess.check_output(
        ["git", "rev-parse", "--git-path", "hard-eng-check.lock"], cwd=root, text=True
    ).strip()
    with (root / name).open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Waiting for another Hard Eng check in this checkout", flush=True)
            fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def gate_timeout(root: Path) -> float:
    """Each gate may use the whole configured budget: CI's in CI, pre-push's elsewhere."""
    from shipping import load_policy

    policy = load_policy(root, required=False)
    if policy is None:
        return 600
    return policy["ci_seconds" if os.environ.get("CI") else "pre_push_seconds"]


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
        for child in groups
        if child["path"] != "."
        and child.get("language") == "javascript"
        and any(
            check.get("role") == gate.get("role") and check["command"] == command
            for check in child["checks"]
        )
    )


def require_ci_base(base: str | None) -> None:
    if (
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("GITHUB_EVENT_NAME")
        in {"push", "pull_request", "pull_request_target"}
        and (base is None or not base.strip())
    ):
        raise ValueError(
            "GitHub push/PR checks require --base with the comparison commit; "
            "pass github.event.pull_request.base.sha || github.event.before. "
            "Manual full checks may omit --base."
        )


def check(
    timeout: float | None = None,
    base: str | None = None,
    plan_stage: str | None = None,
    *,
    verify_plan: bool = True,
) -> int:
    from gate_config import load_groups, parse_config
    from update import check_scaffold_update

    require_ci_base(base)
    parse_config((ROOT / "hard-eng.gates.json").read_text())
    if base is not None and check_scaffold_update(ROOT, base):
        return 0

    with check_lock(ROOT):
        groups = load_groups(ROOT, base)
        timeout = timeout or gate_timeout(ROOT)
        from comments import validate_comments
        from plans import report_stage, validate_plans

        if verify_plan:
            plan_stage = validate_plans(ROOT, base, plan_stage)
        validate_comments(ROOT, base)
        provision_tools(ROOT, groups, timeout)
        output_lock = threading.Lock()

        failed = False
        pending: set[Future[bool]] = set()
        checks = [(group, gate) for group in groups for gate in group["checks"]]
        ordered = [item for item in checks if item[1].get("role") == "lockfiles"]
        ordered += [item for item in checks if item[1].get("role") != "lockfiles"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            for group, gate in ordered:
                if gate.get("parallel", False) and gate.get("role") != "lockfiles":
                    if len(pending) == 2:
                        done, pending = wait(pending, return_when=FIRST_COMPLETED)
                        for future in done:
                            failed |= future.result()
                    pending.add(
                        pool.submit(run_gate, group, gate, timeout, output_lock, groups)
                    )
                else:
                    for future in pending:
                        failed |= future.result()
                    pending.clear()
                    result = run_gate(group, gate, timeout, output_lock, groups)
                    failed |= result
                    if result and gate.get("role") == "lockfiles":
                        print("Dependency setup failed; remaining checks were not run.")
                        report_stage(True, plan_stage)
                        return 1
            for future in pending:
                failed |= future.result()
        report_stage(failed, plan_stage)
        return int(failed)


def impact(base: str) -> int:
    """Tell CI whether the check will run only the secret scan, before tools."""
    from contextlib import redirect_stdout

    from ci_setup import impact_tools
    from gate_config import affected_groups, parse_config

    require_ci_base(base)
    config = parse_config((ROOT / "hard-eng.gates.json").read_text())
    groups: list[Group] = [
        *config["packages"],
        {"path": ".", "checks": config["shared"]},
    ]
    with redirect_stdout(sys.stderr):
        selected = affected_groups(ROOT, groups, base)
    docs_only = bool(config["packages"]) and len(selected) == 1
    print(f"docs_only={str(docs_only).lower()}")
    print("tools=" + " ".join(impact_tools(ROOT, selected)))
    return 0


def pre_push() -> int:
    from ship_actions import pre_push as verify_push

    return verify_push(ROOT)


def main() -> int:
    import argparse

    if Path(sys.argv[0]).name == "pre-push":
        return pre_push()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    checks = commands.add_parser("check", help="Run applicable native checks")
    checks.add_argument(
        "--base", help="Git comparison base; unknown impact runs all checks"
    )
    checks.add_argument("--plan-stage", choices=("Draft", "Ready", "Complete"))
    impacts = commands.add_parser(
        "impact", help="Print docs_only=true when only the secret scan applies"
    )
    impacts.add_argument("--base", required=True)
    commands.add_parser("pre-push", help="Verify the actual commits being pushed")
    updating = commands.add_parser(
        "update",
        help="Install the newest CI-verified Hard Eng revision and record the result",
    )
    updating.add_argument(
        "--apply", action="store_true", help="Run inside the supervising update process"
    )
    shipping = commands.add_parser(
        "ship", help="Verify PR delivery or perform guarded shipping actions"
    )
    shipping.add_argument("--plan", required=True)
    shipping.add_argument("--pr", required=True)
    shipping.add_argument(
        "--stage", choices=("ready", "merge", "delivered", "cleanup"), default="ready"
    )
    shipping.add_argument("--worktree", help="Task worktree in the same repository")
    shipping.add_argument("--merge-method", choices=("merge", "squash", "rebase"))
    for event in ("session", "failure", "stop"):
        hook = commands.add_parser(event, help=f"Handle a native {event} hook")
        hook.add_argument("agent", choices=("claude", "codex"))
    args = parser.parse_args()
    if args.command == "check":
        from tool_setup import ensure_python_runtime

        ensure_python_runtime()
        return check(base=args.base, plan_stage=args.plan_stage)
    if args.command == "impact":
        return impact(args.base)
    if args.command == "pre-push":
        return pre_push()
    if args.command == "update":
        from update_runner import apply_update, run_update

        return apply_update(ROOT) if args.apply else run_update(ROOT)
    if args.command == "ship":
        from ship_actions import run

        return run(
            ROOT, args.plan, args.pr, args.stage, args.worktree, args.merge_method
        )
    from agent_hooks import handle_event

    return handle_event(ROOT, args.command, args.agent)


if __name__ == "__main__":
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
