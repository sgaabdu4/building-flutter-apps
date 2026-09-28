"""Adapt native template commands to the target project's existing stack."""

import configparser
import json
import os
import re
import shlex
import subprocess
import tomllib
from fnmatch import fnmatchcase
from pathlib import Path

from fallow_report import fallow_report_path, validate_scanner_command
from gate_config import (
    GateConfig,
    Group,
    JsonObject,
    Report,
    dart_scan_includes_boundaries,
    generated_sources,
    nonproduction_source,
    repository_files,
    typescript_packages,
)

PACKAGE_MANAGERS = {"npm", "npx", "pnpm", "yarn", "yarnpkg", "bun", "bunx"}
FLUTTER_PLATFORM_ROOTS = {"android", "ios", "web", "windows", "macos", "linux"}


def migrate_dart_plugins(options: JsonObject, source: Path) -> None:
    """Upgrade ordinary older pins to the installed canonical Dart profile."""
    import yaml

    plugins = options.get("plugins")
    if not isinstance(plugins, dict):
        return
    template = (
        source / ".agents/skills/building-flutter-apps/references/analysis_options.yaml"
    )
    canonical = yaml.safe_load(template.read_text())
    for name in ("flutter_skill_lints", "riverpod_lint"):
        entry = plugins.get(name)
        if isinstance(entry, dict) and {"path", "git", "hosted"} & entry.keys():
            continue
        version = entry.get("version") if isinstance(entry, dict) else entry
        installed = (
            re.fullmatch(r"\^?(\d+)\.(\d+)\.(\d+)", version)
            if isinstance(version, str)
            else None
        )
        if installed is None:
            continue
        current = canonical["plugins"][name]
        latest = re.fullmatch(r"\^?(\d+)\.(\d+)\.(\d+)", current)
        if latest is None:
            raise ValueError(
                "Canonical Flutter lint version must be an exact or caret version"
            )
        if tuple(map(int, installed.groups())) < tuple(map(int, latest.groups())):
            plugins[name] = (
                {**entry, "version": current} if isinstance(entry, dict) else current
            )


def validate_dart_exclusions(directory: Path, values: object) -> None:
    allowed = {
        ".dart_tool/**",
        "**/*.g.dart",
        "**/*.freezed.dart",
        "**/*.gr.dart",
        "**/*.arb",
    }
    flutter = (directory / "pubspec.yaml").is_file() and dependency_command(
        directory, "dart"
    )[0] == "flutter"
    native = {"build/**"} if flutter else set()
    native.update(
        f"{root}/**"
        for root in FLUTTER_PLATFORM_ROOTS
        if flutter and (directory / root).is_dir()
    )
    if not isinstance(values, list) or any(
        not isinstance(value, str) or value not in allowed | native for value in values
    ):
        raise ValueError("Dart strict analysis cannot exclude project files")
    roots = {pattern.split("/", 1)[0] for pattern in set(values) & native}
    matches = {
        path
        for pattern in set(values) - native - {".dart_tool/**"}
        for path in directory.glob(pattern)
        if path.relative_to(directory).parts[0] not in roots
    }
    if roots:
        names = subprocess.check_output(
            ["git", "ls-files", "-zco", "--exclude-standard", "--", *sorted(roots)],
            cwd=directory,
            text=True,
        ).split("\0")
        matches.update(
            directory / name
            for name in names
            if name
            and (Path(name).suffix == ".dart" or (directory / name).is_symlink())
        )
    names = [str(path.relative_to(directory)) for path in matches]
    generated = generated_sources(directory, names)
    for path in matches:
        relative = path.relative_to(directory)
        if ".dart_tool/**" in values and relative.parts[0] == ".dart_tool":
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Dart generated exclusion matches an unsafe path: {path}")
        if path.suffix != ".dart" or str(relative) in generated:
            continue
        with path.open("rb") as source:
            header = source.read(2048).splitlines()[:10]
        if b"// GENERATED CODE - DO NOT MODIFY BY HAND" not in header:
            raise ValueError(f"Dart exclusion matches handwritten source: {path}")


def validate_command_output(
    command: list[str], directory: Path, report: Report
) -> None:
    arguments = package_script_arguments(command, directory)
    options = shlex.split(os.environ.get("NODE_OPTIONS", ""))
    suppressed = os.environ.get("NODE_NO_WARNINGS") == "1"
    for argument in arguments:
        key, _, value = argument.partition("=")
        if key == "NODE_OPTIONS":
            options.extend(shlex.split(value))
        suppressed |= key == "NODE_NO_WARNINGS" and value == "1"
    if suppressed or "--no-warnings" in [*arguments, *options]:
        raise ValueError(
            "Verification cannot suppress all Node warnings; repair the warning owner or use a justified narrow native exception"
        )
    validate_scanner_command(arguments, report)


def is_shell_script(path: Path) -> bool:
    if path.suffix in {".sh", ".bash"}:
        return True
    if path.suffix:
        return False
    with path.open("rb") as source:
        return bool(re.match(rb"^#![^\n]*\b(?:bash|sh)(?:\s|$)", source.readline(4096)))


def is_deployment_file(path: Path) -> bool:
    return path.name in {"Dockerfile", "Containerfile", "Chart.yaml", "tfplan"} or str(
        path
    ).endswith((".tf", ".tf.json", ".tfvars", ".tfplan"))


def package_script_arguments(
    command: list[str], directory: Path, pnpm_only: bool = False
) -> list[str]:
    return package_script_invocation(command, directory, pnpm_only)[0]


def package_script_invocation(
    command: list[str], directory: Path, pnpm_only: bool = False
) -> tuple[list[str], Path]:
    arguments = list(command)
    scripts_seen = set()
    while arguments:
        executable = Path(arguments[0]).name
        if pnpm_only and executable in PACKAGE_MANAGERS - {"pnpm"}:
            raise ValueError(f"JavaScript checks must use pnpm, not: {executable}")
        if executable in {"npm", "pnpm", "yarn", "bun"}:
            while len(arguments) > 2 and arguments[1].split("=", 1)[0] in {
                "--dir",
                "--prefix",
                "-C",
            }:
                _, separator, value = arguments[1].partition("=")
                directory = (
                    directory / (value if separator else arguments[2])
                ).resolve()
                arguments = [arguments[0], *arguments[2 if separator else 3 :]]
            if (
                len(arguments) > 1
                and arguments[1].startswith("-")
                and any(value in arguments for value in ("run", "run-script"))
            ):
                raise ValueError(
                    "Use an explicit package directory and run script for verification; package selectors are not supported"
                )
        if (
            executable not in {"npm", "pnpm", "yarn", "bun"}
            or len(arguments) <= 2
            or arguments[1] not in {"run", "run-script"}
        ):
            break
        identity = (directory.resolve(), arguments[2])
        if identity in scripts_seen:
            raise ValueError("Recursive package test script")
        scripts_seen.add(identity)
        package = json.loads((directory / "package.json").read_text())
        script = package.get("scripts", {}).get(arguments[2])
        if not isinstance(script, str):
            raise TypeError("Configured package test script is missing")
        arguments = shlex.split(script) + arguments[3:]
        if not arguments:
            raise ValueError("Configured package test script is empty")
    return arguments, directory


def javascript_manager(directory: Path) -> tuple[str, list[str], str]:
    manifest = json.loads((directory / "package.json").read_text())
    if manifest.get("workspaces") and not (directory / "pnpm-workspace.yaml").is_file():
        raise ValueError(
            "pnpm workspaces require pnpm-workspace.yaml; migrate the workspace declaration"
        )
    declared = manifest.get("packageManager")
    if declared is not None and (
        not isinstance(declared, str) or not declared.startswith("pnpm@")
    ):
        raise ValueError(
            f"{directory}: pnpm is required; migrate packageManager to pnpm@VERSION"
        )
    legacy = [
        name
        for name in (
            "package-lock.json",
            "npm-shrinkwrap.json",
            "yarn.lock",
            "bun.lock",
            "bun.lockb",
        )
        if (directory / name).exists()
    ]
    if legacy:
        raise ValueError(
            f"{directory}: pnpm is required; migrate and remove legacy lockfiles: "
            + ", ".join(legacy)
        )
    lockfile = "pnpm-lock.yaml"
    if not (directory / lockfile).exists() and not (directory / ".git").exists():
        for parent in directory.parents:
            if (parent / "package.json").exists() and workspace_matches(
                str(directory.relative_to(parent)),
                workspace_members(parent, "javascript"),
            ):
                return javascript_manager(parent)
            if (parent / ".git").exists():
                break
    if not (directory / lockfile).exists():
        raise ValueError(
            f"{directory}: pnpm-lock.yaml is required; run pnpm install and review the migration"
        )
    return "pnpm", ["pnpm", "install", "--frozen-lockfile"], lockfile


def adapt_sources(root: Path, package: Group, files: list[Path]) -> None:
    directory = root / package["path"]
    extensions = {
        "python": {".py"},
        "javascript": {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"},
        "dart": {".dart"},
    }
    sources = set()
    for path in files:
        if (
            not path.is_relative_to(directory)
            or path.suffix not in extensions[package["language"]]
        ):
            continue
        relative = path.relative_to(directory)
        if nonproduction_source(relative) or {".hooks", ".agents"} & set(
            relative.parts
        ):
            continue
        sources.add(relative.parts[0])
    if sources:
        previous = package["sources"]
        package["sources"] = sorted(sources)
        for gate in package["checks"]:
            command = []
            for argument in gate["command"]:
                if argument in previous:
                    command.extend(package["sources"])
                elif argument.startswith("--cov="):
                    command.extend(
                        f"--cov={Path(source).stem if source.endswith('.py') else source}"
                        for source in package["sources"]
                    )
                else:
                    command.append(argument)
            gate["command"] = command


def dependency_command(directory: Path, language: str) -> tuple[str, list[str], str]:
    if language == "javascript":
        return javascript_manager(directory)
    if language == "python":
        if (directory / "poetry.lock").exists():
            return "poetry", ["poetry", "sync"], "poetry.lock"
        uv = ("uv", ["uv", "sync", "--locked"], "uv.lock")
        if (directory / "uv.lock").exists():
            return uv
        for parent in [] if (directory / ".git").exists() else directory.parents:
            if (
                (parent / "pyproject.toml").exists()
                and (parent / "uv.lock").exists()
                and workspace_matches(
                    str(directory.relative_to(parent)),
                    workspace_members(parent, "python"),
                )
            ):
                return uv  # A uv workspace member uses its root's lockfile.
            if (parent / ".git").exists():
                break
        raise ValueError(
            f"{directory}: uv.lock or poetry.lock is required; run `uv lock` after "
            "declaring dependencies in pyproject.toml (`uv add -r requirements.txt` "
            "imports a requirements file), then review and commit the lockfile"
        )
    import yaml

    manifest = yaml.safe_load((directory / "pubspec.yaml").read_text())
    dependencies = {
        **manifest.get("dependencies", {}),
        **manifest.get("dev_dependencies", {}),
    }
    manager = (
        "flutter"
        if any(
            isinstance(value, dict) and value.get("sdk") == "flutter"
            for value in dependencies.values()
        )
        else "dart"
    )
    return manager, [manager, "pub", "get", "--enforce-lockfile"], "pubspec.lock"


def adapt_packages(root: Path, config: GateConfig) -> None:
    owned: dict[Path, list[Path]] = {
        root / package["path"]: [] for package in config["packages"]
    }
    files = repository_files(root)
    for path in files:
        owner = next((parent for parent in path.parents if parent in owned), None)
        if owner is not None:
            owned[owner].append(path)
    typescript = typescript_packages(root, files)
    for package in config["packages"]:
        directory = root / package["path"]
        adapt_sources(root, package, owned[directory])
        adapt_package(directory, package)
        adapt_boundaries(package, typescript)
        for gate in package["checks"]:
            if gate.get("role") == "security":
                gate["command"] = [
                    os.path.relpath(root / argument, directory)
                    if argument == ".agents/skills/he/security"
                    else argument
                    for argument in gate["command"]
                ]
    adapt_workspaces(root, config)


def adapt_boundaries(package: Group, typescript: set[str]) -> None:
    if package.get("language") == "dart" and any(
        dart_scan_includes_boundaries(gate) for gate in package["checks"]
    ):
        generated = [
            {
                "name": name,
                "role": "boundaries",
                "command": [
                    "dart-decimate",
                    "check",
                    ".",
                    "--boundary-violations",
                    "--strict",
                ],
            }
            for name in ("import-boundaries", "lint:boundaries")
        ]
        package["checks"] = [
            gate for gate in package["checks"] if gate not in generated
        ]
        return
    required = (
        str(Path(package["path"])) in typescript or package.get("language") == "dart"
    )
    if required and not any(
        gate.get("role") == "boundaries" for gate in package["checks"]
    ):
        package["checks"].append(
            {
                "name": "lint:boundaries",
                "role": "boundaries",
                "command": (
                    ["dart-decimate", "check", ".", "--boundary-violations", "--strict"]
                    if package.get("language") == "dart"
                    else ["pnpm", "run", "lint:boundaries"]
                ),
            }
        )


def workspace_members(directory: Path, language: str) -> list[str]:
    if language == "python":
        project = tomllib.loads((directory / "pyproject.toml").read_text())
        workspace = project.get("tool", {}).get("uv", {}).get("workspace", {})
        return [
            *workspace.get("members", []),
            *("!" + value for value in workspace.get("exclude", [])),
        ]
    if language == "javascript" and not (directory / "pnpm-workspace.yaml").exists():
        return []
    import yaml

    name = "pubspec.yaml" if language == "dart" else "pnpm-workspace.yaml"
    manifest = yaml.safe_load((directory / name).read_text())
    return manifest.get("workspace" if language == "dart" else "packages", [])


def workspace_matches(relative: str, members: list[str]) -> bool:
    return any(
        fnmatchcase(relative, pattern)
        for pattern in members
        if not pattern.startswith("!")
    ) and not any(
        fnmatchcase(relative, pattern[1:])
        for pattern in members
        if pattern.startswith("!")
    )


def adapt_workspaces(root: Path, config: GateConfig) -> None:
    for owner in config["packages"]:
        directory, language = root / owner["path"], owner["language"]
        members = workspace_members(directory, language)
        if not members:
            continue
        for child in config["packages"]:
            path = root / child["path"]
            if (
                child is owner
                or child.get("language") != language
                or not path.is_relative_to(directory)
            ):
                continue
            relative = str(path.relative_to(directory))
            if workspace_matches(relative, members):
                child["checks"] = [
                    gate
                    for gate in child["checks"]
                    if gate.get("role") not in {"lockfiles", "vulnerabilities"}
                ]
        if language == "python":
            for gate in owner["checks"]:
                if gate.get("role") == "lockfiles" and gate["command"][:2] == [
                    "uv",
                    "sync",
                ]:
                    gate["command"].append("--all-packages")
        if not any((directory / source).exists() for source in owner["sources"]):
            owner["checks"] = [
                gate
                for gate in owner["checks"]
                if gate.get("role")
                in {
                    "lockfiles",
                    "vulnerabilities",
                    "build",
                    "integration",
                    "ui",
                    "generated",
                }
            ]
            owner.pop("language")
            owner.pop("sources")


def adapt_package(directory: Path, package: Group) -> None:
    language = package["language"]
    manager, install, lockfile = dependency_command(directory, language)
    for gate in package["checks"]:
        if gate.get("role") == "lockfiles":
            gate["command"] = install
        elif gate.get("role") == "vulnerabilities":
            gate["command"] = [
                f"--lockfile={lockfile}" if arg.startswith("--lockfile=") else arg
                for arg in gate["command"]
            ]
        elif language == "python" and gate["command"][0] in {
            "pytest",
            "deptry",
            "lint-imports",
        }:
            gate["command"] = python_gate_command(gate["command"], manager)
        elif language == "dart" and manager == "dart" and gate.get("role") == "tests":
            gate["command"] = [
                "dart",
                "run",
                "coverage:test_with_coverage",
                "--branch-coverage",
                "--",
                "--file-reporter=json:coverage/tests.jsonl",
            ]
            gate["report"]["stdout"] = False
    if language == "javascript":
        adapt_javascript(directory, package, manager)
    elif language == "python" and not python_roots(directory, package):
        package["checks"] = [
            gate for gate in package["checks"] if gate.get("role") != "imports"
        ]
    adapt_performance(directory, package)


def adapt_performance(directory: Path, package: Group) -> None:
    if any(
        (directory / name).is_file()
        for name in (
            "lighthouserc.js",
            "lighthouserc.cjs",
            "lighthouserc.json",
            "lighthouserc.yml",
            "lighthouserc.yaml",
            ".lighthouserc.js",
            ".lighthouserc.cjs",
            ".lighthouserc.json",
            ".lighthouserc.yml",
            ".lighthouserc.yaml",
        )
    ):
        for gate in package["checks"]:
            if gate.get("role") == "performance":
                gate["command"] = [
                    "lhci",
                    "autorun",
                    "--assert.includePassedAssertions",
                    "--upload.target=filesystem",
                    "--upload.outputDir=coverage/lighthouse",
                ]
                gate["report"] = {
                    "type": "lighthouse-ci",
                    "path": ".lighthouseci/assertion-results.json",
                }
    # Production builds and generators must finish before measurement begins.
    checks = package["checks"]
    package["checks"] = [
        gate for gate in checks if gate.get("role") != "performance"
    ] + [gate for gate in checks if gate.get("role") == "performance"]


def python_gate_command(command: list[str], manager: str) -> list[str]:
    packages = {
        "pytest": ["pytest", "pytest-cov"],
        "deptry": ["deptry"],
        "lint-imports": ["import-linter"],
    }[command[0]]
    prefix = ["uv", "run", "--no-sync"]
    if manager == "poetry":
        prefix = ["poetry", "run", "uv", "run", "--no-project", "--active"]
    for package in packages:
        prefix.extend(["--with", package, "--upgrade-package", package])
    return [*prefix, *command]


def strict_scanner_flags(package: Group) -> None:
    """Give an older scanner gate the flags the check now requires of it."""
    from fallow_report import native_scanner_command, option

    for gate in package["checks"]:
        invocation = native_scanner_command(gate["command"])
        if invocation is None or "&&" in gate["command"]:
            continue
        required: list[str] = []
        if invocation[0] == "react-doctor":
            required = ["--no-respect-inline-disables"]
        elif invocation[0] == "dart-decimate":
            required = ["--strict"] if "check" in invocation else required
        elif "audit" in invocation:
            required = required if option(invocation, "--gate") else ["--gate", "all"]
        else:
            required = ["--fail-on-issues"]
        if required and required[0] not in invocation:
            gate["command"] = [*gate["command"], *required]


FLUTTER_TESTS = [
    "flutter",
    "test",
    "--no-pub",
    "--machine",
    "--coverage",
    "--coverage-path=coverage/lcov.info",
]
BROWSER_IMPORT = re.compile(
    r"""^\s*import\s+['"](?:dart:(?:html|js|js_util|js_interop|js_interop_unsafe"""
    r"""|indexed_db|svg|web_audio|web_gl)|package:web/)""",
    re.MULTILINE,
)


SELECT_BROWSER_TESTS = (
    'tests=$(grep -rlE "^@TestOn\\([\'\\"] *(browser|chrome)" test || true); '
)


def run_browser_tests(options: str) -> str:
    return (
        'if [ -z "$tests" ]; then echo "Browser libraries need tests under test/ marked'
        " @TestOn('browser') that import package:test/test.dart (not flutter_test);"
        ' declare test as a dev dependency and provide Chrome." >&2; exit 0; fi; '
        f"dart test --platform=chrome{options} --reporter=json"
        " --coverage-path=coverage/browser.lcov $tests; "
        "cat coverage/browser.lcov >> coverage/lcov.info"
    )


def browser_tests(options: str) -> list[str]:
    return [
        "sh",
        "-c",
        "set -e; rm -f coverage/browser.lcov coverage/lcov.info; "
        + SELECT_BROWSER_TESTS
        + 'if find test -name "*_test.dart" | grep -qvxF -e "$tests"; then '
        + shlex.join(FLUTTER_TESTS)
        + "; fi; "
        + run_browser_tests(options),
    ]


PREVIOUS_BROWSER_TESTS = [
    [
        "sh",
        "-c",
        "set -e; rm -f coverage/browser.lcov; "
        + shlex.join(FLUTTER_TESTS)
        + "; "
        + SELECT_BROWSER_TESTS
        + run_browser_tests(""),
    ],
    browser_tests(""),
]
# dart2js inlining leaves one-line forwarders without source-map coverage lines.
BROWSER_TESTS = browser_tests(" --dart2js-args=--disable-inlining")


def browser_test_coverage(directory: Path, package: Group) -> None:
    """Add browser-test LCOV where Flutter's VM run cannot load browser libraries.

    `flutter test --platform chrome --coverage` writes no LCOV, so the gate also
    runs `@TestOn('browser')` tests with `dart test` on Chrome and appends
    that run's LCOV to the package report.
    """
    if package.get("language") != "dart" or not any(
        BROWSER_IMPORT.search(file.read_text(errors="replace"))
        for source in package.get("sources", [])
        for file in (directory / source).rglob("*.dart")
    ):
        return
    for gate in package["checks"]:
        if gate.get("role") == "tests" and gate["command"] in (
            FLUTTER_TESTS,
            *PREVIOUS_BROWSER_TESTS,
        ):
            gate["command"] = list(BROWSER_TESTS)


def parallel_pytest(package: Group) -> None:
    """Run a generated pytest gate on every core; `-n 0` keeps a suite serial."""
    for gate in package["checks"]:
        command = gate["command"]
        runners = [
            index
            for index, argument in enumerate(command)
            if argument == "pytest"
            and command[index - 1] not in {"--with", "--upgrade-package"}
        ]
        if gate.get("role") != "tests" or not runners or "--with" not in command:
            continue
        options = command[runners[0] + 1 :]
        if "no:xdist" in options or any(
            option.startswith(("-n", "--numprocesses", "--dist")) for option in options
        ):
            continue
        xdist = ["--with", "pytest-xdist", "--upgrade-package", "pytest-xdist"]
        gate["command"] = [
            *command[: runners[0]],
            *([] if "pytest-xdist" in command else xdist),
            "pytest",
            "-n",
            "auto",
            *options,
        ]


def python_interpreter(directory: Path, timeout: float) -> str:
    from tool_setup import managed_command

    manager, _, _ = dependency_command(directory, "python")
    command = (
        ["uv", "run", "--no-sync", "python", "-c", "import sys; print(sys.executable)"]
        if manager == "uv"
        else ["poetry", "env", "info", "--executable"]
    )
    environment = dict(os.environ)
    environment.pop("VIRTUAL_ENV", None)
    return subprocess.check_output(
        managed_command(command),
        cwd=directory,
        text=True,
        timeout=timeout,
        env=environment,
    ).strip()


def javascript_files(directory: Path, excluded: tuple[Path, ...] = ()) -> list[str]:
    directory = directory.resolve()
    excluded = tuple(owner.resolve() for owner in excluded)
    extensions = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"}
    files = [
        str(path.relative_to(directory))
        for path in repository_files(directory)
        if path.suffix in extensions
        and not any(path.is_relative_to(owner) for owner in excluded)
        and not {"node_modules", "vendor", ".hooks", ".agents"}
        & set(path.relative_to(directory).parts)
    ]
    if not files and not excluded:
        raise ValueError("No JavaScript or TypeScript source files found")
    return files


def adapt_javascript(directory: Path, package: Group, manager: str) -> None:
    manifest = json.loads((directory / "package.json").read_text())
    if "check:fallow" in manifest.get("scripts", {}):
        for gate in package["checks"]:
            if gate.get("role") == "dead-code-duplicates":
                gate["command"] = [manager, "run", "check:fallow"]
                output = fallow_report_path(
                    package_script_arguments(gate["command"], directory)
                )
                if output is not None:
                    gate.setdefault("report", {})["path"] = output
    dependencies = {
        **manifest.get("dependencies", {}),
        **manifest.get("devDependencies", {}),
    }
    if "react" in dependencies:
        package["checks"].append(
            {
                "name": "react-doctor",
                "role": "react",
                "command": [
                    "react-doctor",
                    "--scope",
                    "full",
                    "--blocking",
                    "warning",
                    "--no-respect-inline-disables",
                    "--json",
                    "--json-out",
                    "coverage/react-doctor.json",
                ],
                "report": {
                    "type": "react-doctor",
                    "path": "coverage/react-doctor.json",
                },
            }
        )
    for script, role in (
        ("build", "build"),
        ("test:integration", "integration"),
        ("test:ui", "ui"),
        ("check:generated", "generated"),
        ("lint:boundaries", "boundaries"),
    ):
        if script in manifest.get("scripts", {}):
            package["checks"].append(
                {"name": script, "role": role, "command": [manager, "run", script]}
            )


def python_roots(directory: Path, package: Group) -> list[str]:
    roots = set()
    for name in package["sources"]:
        path = directory / name
        if not path.is_dir():
            continue
        if (path / "__init__.py").exists() and name.isidentifier():
            roots.add(name)
        elif name == "src":
            roots.update(
                child.name
                for child in path.iterdir()
                if child.is_dir()
                and child.name.isidentifier()
                and (child / "__init__.py").exists()
            )
    return sorted(roots)


def import_linter_owner(
    directory: Path,
) -> tuple[Path, configparser.ConfigParser] | None:
    for name in ("setup.cfg", ".importlinter"):
        owner = directory / name
        if not owner.is_file():
            continue
        parser = configparser.ConfigParser()
        parser.read(owner)
        if parser.has_section("importlinter"):
            return owner, parser
    return None


def has_recursive_import_contract(
    parser: configparser.ConfigParser, roots: list[str]
) -> bool:
    root_option = (
        "root_packages"
        if parser.has_option("importlinter", "root_packages")
        else "root_package"
    )
    configured_roots = {
        value.strip()
        for value in parser.get("importlinter", root_option, fallback="").splitlines()
        if value.strip()
    }
    if not set(roots).issubset(configured_roots):
        return False
    contracts = [
        parser[section]
        for section in parser.sections()
        if section.startswith("importlinter:")
    ]
    ancestors = set()
    for contract in contracts:
        if (
            contract.get("name", "").strip()
            and contract.get("type", "").strip() == "acyclic_siblings"
            and contract.get("depth", "").strip() == "0"
        ):
            ancestors.update(
                value.strip()
                for value in contract.get("ancestors", "").splitlines()
                if value.strip()
            )
    return all({root, root + ".**"} <= ancestors for root in roots)


def import_configuration(directory: Path, package: Group, content: str) -> str:
    roots = python_roots(directory, package)
    if not roots:
        return content
    configured = import_linter_owner(directory)
    if configured is not None:
        owner, parser = configured
        if has_recursive_import_contract(parser, roots):
            return content
        raise ValueError(
            f"Import Linter prioritizes {owner.name}; preserve its existing contracts "
            "and add a depth-zero acyclic_siblings contract covering each root and its descendants there"
        )
    if "importlinter" in tomllib.loads(content).get("tool", {}):
        return content
    ancestors = [value for root in roots for value in (root, root + ".**")]
    return content + (
        "\n[tool.importlinter]\nroot_packages = " + json.dumps(roots) + "\n"
        '\n[[tool.importlinter.contracts]]\nname = "No sibling dependency cycles"\n'
        'type = "acyclic_siblings"\nancestors = '
        + json.dumps(ancestors)
        + "\ndepth = 0\n"
    )
