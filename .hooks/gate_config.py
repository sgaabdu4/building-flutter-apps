"""Validate required documents and gate configuration before execution."""

import json
import os
import re
import subprocess
from pathlib import Path
from typing import NotRequired, TypedDict, cast

from dependency_graph import (
    dependency_review_guidance,
    expand_dependents,
    impact_inputs,
    secrets_only,
)

type JsonValue = (
    str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
)
type JsonObject = dict[str, JsonValue]


def expanded(value: object) -> bool:
    if isinstance(value, dict):
        return bool(value)
    return isinstance(value, list) and any(expanded(item) for item in value)


def json_text(
    value: object, layout: tuple[str, int, int], indent: str = "", used: int = 0
) -> str:
    unit, tab, width = layout
    if isinstance(value, list) and not expanded(value):
        flat = json.dumps(value, separators=(", ", ": "))
        if used + len(flat) <= width:
            return flat
    if not isinstance(value, (dict, list)) or not value:
        return json.dumps(value)
    inner = indent + unit
    entries = (
        [(f"{json.dumps(key)}: ", item) for key, item in value.items()]
        if isinstance(value, dict)
        else [("", item) for item in value]
    )
    last = len(entries) - 1
    body = ",\n".join(
        inner
        + head
        + json_text(
            item,
            layout,
            inner,
            len((inner + head).expandtabs(tab)) + (index < last),
        )
        for index, (head, item) in enumerate(entries)
    )
    opening, closing = "{}" if isinstance(value, dict) else "[]"
    return f"{opening}\n{body}\n{indent}{closing}"


JSONC = re.compile(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', re.DOTALL)


def json_layout(root: Path) -> tuple[str, int, int]:
    """Read the root Biome config's JSON formatting, else use Prettier's defaults."""
    for name in ("biome.json", "biome.jsonc"):
        if (root / name).is_file():
            text = JSONC.sub(lambda match: match[1] or "", (root / name).read_text())
            try:
                config = json.loads(re.sub(r",(\s*[}\]])", r"\1", text))
            except ValueError:
                return "\t", 2, 80
            options = {
                **config.get("formatter", {}),
                **config.get("json", {}).get("formatter", {}),
            }
            tab = options.get("indentWidth", 2)
            unit = "\t" if options.get("indentStyle", "tab") == "tab" else " " * tab
            return unit, tab, options.get("lineWidth", 80)
    return "  ", 2, 80


def json_file(root: Path, value: object) -> str:
    return json_text(value, json_layout(root)) + "\n"


Report = TypedDict(
    "Report",
    {"type": str, "path": str, "tests": str, "coverage": str, "stdout": bool},
    total=False,
)
Gate = TypedDict(
    "Gate",
    {
        "name": str,
        "command": list[str],
        "role": NotRequired[str],
        "parallel": NotRequired[bool],
        "report": NotRequired[Report],
    },
)
Group = TypedDict(
    "Group",
    {
        "path": str,
        "checks": list[Gate],
        "name": NotRequired[str],
        "language": NotRequired[str],
        "sources": NotRequired[list[str]],
        "depends_on": NotRequired[list[str]],
        "impact_inputs": NotRequired[list[str]],
    },
)
GateConfig = TypedDict(
    "GateConfig",
    {
        "packages": list[Group],
        "shared": list[Gate],
        "version": NotRequired[int],
        "scan_git_history": NotRequired[bool],
        "shipping": NotRequired[JsonObject],
        "file_size_exceptions": NotRequired[dict[str, dict[str, str]]],
    },
)

LANGUAGES = {
    "pyproject.toml": "python",
    "package.json": "javascript",
    "pubspec.yaml": "dart",
}
LOCKFILES = {
    "python": ("uv.lock", "poetry.lock"),
    "javascript": ("pnpm-lock.yaml",),
    "dart": ("pubspec.lock",),
}


def package_manifests(root: Path, files: list[Path]) -> set[tuple[str, str]]:
    candidates = [path for path in files if path.name in LANGUAGES]
    generated = generated_sources(
        root, [str(path.relative_to(root)) for path in candidates]
    )
    manifests = [
        path
        for path in candidates
        if ".agents" not in path.relative_to(root).parts
        and str(path.relative_to(root)) not in generated
    ]
    return {
        (str(path.parent.relative_to(root)), LANGUAGES[path.name])
        for path in manifests
        if not fixture_manifest(root, path, manifests)
    }


def fixture_manifest(root: Path, manifest: Path, manifests: list[Path]) -> bool:
    """Test input: under a test directory, no own lockfile, no declaring workspace."""
    from project_setup import workspace_matches, workspace_members

    directory, language = manifest.parent, LANGUAGES[manifest.name]
    return (
        nonproduction_source(manifest.relative_to(root))
        and not any((directory / name).exists() for name in LOCKFILES[language])
        and not any(
            owner != manifest
            and owner.name == manifest.name
            and directory.is_relative_to(owner.parent)
            and workspace_matches(
                str(directory.relative_to(owner.parent)),
                workspace_members(owner.parent, language),
            )
            for owner in manifests
        )
    )


def repository_files(root: Path) -> list[Path]:
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        text=True,
    )
    return [
        root / name
        for name in sorted(set(names.split("\0")) - {""})
        if (root / name).is_file() and not (root / name).is_symlink()
    ]


def nonproduction_source(relative: Path) -> bool:
    return bool(
        {"test", "tests", "__tests__", "node_modules", "vendor"} & set(relative.parts)
        or relative.name.startswith("test_")
        or relative.stem.endswith(("_test", ".test", ".spec"))
        or relative.name.endswith((".d.ts", ".d.mts", ".d.cts"))
    )


def dart_test_support(path: str, language: str | None, packages: list[Group]) -> bool:
    """A parent Dart package's package-root analysis and formatting cover it."""
    return (
        language == "dart"
        and nonproduction_source(Path(path))
        and any(
            group.get("language") == "dart"
            and Path(path) != Path(group["path"])
            and Path(path).is_relative_to(group["path"])
            for group in packages
        )
    )


def typescript_packages(root: Path, files: list[Path]) -> set[str]:
    manifests = {path.parent for path in files if path.name == "package.json"}
    packages = set()
    for path in files:
        relative = path.relative_to(root)
        if (
            path.suffix not in {".ts", ".tsx", ".mts", ".cts"}
            or nonproduction_source(relative)
            or {".hooks", ".agents"} & set(relative.parts)
        ):
            continue
        owner = next((parent for parent in path.parents if parent in manifests), None)
        if owner is not None:
            packages.add(str(owner.relative_to(root)))
    return packages


def generated_sources(root: Path, names: list[str]) -> set[str]:
    if not names:
        return set()
    repository = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if repository.returncode:
        return set()  # Standalone source directories have no Git attributes.
    attributes = subprocess.check_output(
        [
            "git",
            "check-attr",
            "-z",
            "--stdin",
            "linguist-generated",
            "linguist-vendored",
        ],
        cwd=root,
        text=True,
        input="\0".join(names) + "\0",
    ).split("\0")
    return {
        name
        for name, _, value in zip(attributes[::3], attributes[1::3], attributes[2::3])
        if value in {"set", "true"}
    }


def dart_rule_settings(value: object) -> object:
    if isinstance(value, list):
        if not all(isinstance(rule, str) for rule in value):
            raise ValueError("Dart lint rule names must be strings")
        return {rule: True for rule in value}
    return value


def validate_dart_plugins(options: JsonObject) -> None:
    from project_setup import migrate_dart_plugins

    plugins = options.get("plugins")
    if not isinstance(plugins, dict):
        return
    migrated = dict(plugins)
    updated: JsonObject = {"plugins": migrated}
    migrate_dart_plugins(updated, Path(__file__).resolve().parents[1])
    if updated["plugins"] != plugins:
        versions = {
            name: value.get("version") if isinstance(value, dict) else value
            for name, value in plugins.items()
        }
        changes = ", ".join(
            f"{name}: {versions[name]} -> {value.get('version') if isinstance(value, dict) else value}"
            for name, value in migrated.items()
            if value != plugins.get(name)
        )
        raise ValueError(
            f"Analyzer plugin version is older than the installed canonical profile ({changes}); run the supported Hard Eng updater and verify application compatibility"
        )


def validate_dart_exclusions(directory: Path, values: object) -> None:
    from project_setup import validate_dart_exclusions as validate

    validate(directory, values)


def validate_file_sizes(root: Path, exceptions: dict[str, dict[str, str]]) -> None:
    if not isinstance(exceptions, dict):
        raise TypeError("File-size exceptions must be an object")
    extensions = {
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".mjs",
        ".cjs",
        ".mts",
        ".cts",
        ".dart",
        ".sh",
        ".bash",
    }
    files = [path for path in repository_files(root) if path.suffix in extensions]
    names = [str(path.relative_to(root)) for path in files]
    for name, justification in exceptions.items():
        if (
            name not in names
            or not isinstance(justification, dict)
            or not all(
                isinstance(justification.get(key), str) and justification[key].strip()
                for key in ("reason", "evidence")
            )
        ):
            raise ValueError(
                "File-size exceptions require an exact existing file, reason and evidence"
            )
    generated = generated_sources(root, names)
    failures = []
    for path, name in zip(files, names):
        if name in generated or name in exceptions:
            continue
        lines = len(path.read_bytes().splitlines())
        if lines > 1000:
            failures.append(f"{name}: {lines} lines")
    if failures:
        raise ValueError(
            "Handwritten files exceed 1000 physical lines: " + "; ".join(failures)
        )


def validate_documents(root: Path) -> None:
    for name, required in (
        ("PRODUCT.md", ("Users", "Problem", "Product Purpose", "Boundaries")),
        ("DESIGN.md", ("Overview", "Components", "Do's and Don'ts")),
    ):
        path = root / name
        if not path.is_file():
            raise ValueError(f"{name} is required; fill it from the actual project")
        content = path.read_text().strip()
        if not content:
            raise ValueError(f"{name} is empty; fill it from the actual project")
        if "[todo:" in content.lower():
            raise ValueError(f"{name} contains unfilled template prompts")
        if not re.search(r"(?m)^# \S[^\n]*$", content):
            raise ValueError(f"{name} needs a document title using '# Title'")
        parts = re.split(r"(?m)^##[ \t]+([^\n]+)\n", content + "\n")
        sections = dict(zip((heading.strip() for heading in parts[1::2]), parts[2::2]))
        for heading in required:
            if not sections.get(heading, "").strip():
                raise ValueError(f"{name} needs a filled '## {heading}' section")
        order = [
            heading.strip() for heading in parts[1::2] if heading.strip() in required
        ]
        if order != list(required):
            raise ValueError(
                f"{name} sections must follow the template order without duplicates"
            )


def validate_gate(gate: Gate, directory: Path, report_paths: set[Path]) -> None:
    if (
        not isinstance(gate, dict)
        or not isinstance(gate.get("name"), str)
        or not gate["name"].strip()
    ):
        raise ValueError("Each check must have a nonempty name")
    if type(gate.get("parallel", False)) is not bool:
        raise ValueError("parallel must be true or false")
    report = gate.get("report", {})
    if not isinstance(report, dict):
        raise TypeError("report must be an object")
    for key in ("path", "tests", "coverage"):
        if key in report:
            value = report[key]
            if not isinstance(value, str) or not value:
                raise ValueError("Report paths must be nonempty strings")
            path = (directory / value).resolve()
            if path in report_paths:
                raise ValueError(f"Checks must use distinct report files: {path}")
            report_paths.add(path)
    command = gate.get("command")
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(arg, str) for arg in command)
        or not command[0].strip()
    ):
        raise ValueError(
            f"{gate['name']}: command must be a nonempty list starting with an executable"
        )
    if "tool" in gate:
        raise ValueError(
            f"{gate['name']}: put the executable in command; separate tool fields are unsupported"
        )
    from gitleaks_scan import validate_current_files_gate

    validate_current_files_gate(gate.get("role"), command)
    from project_setup import validate_command_output

    validate_command_output(command, directory, report)


def dart_scan_includes_boundaries(gate: Gate) -> bool:
    command = ["dart-decimate", "check", ".", "--threshold", "0"]
    report = gate.get("report", {})
    return (
        gate.get("role") == "dead-code-duplicates"
        and gate["command"]
        in (
            [*command, "--strict", "--format", "json"],
            [*command, "--format", "json", "--strict"],
        )
        and report.get("type") == "dart-decimate"
        and report.get("stdout") is True
    )


def validate_dart_boundaries(
    command: list[str], directory: Path, timeout: float
) -> None:
    if command[:3] != ["dart-decimate", "check", "."]:
        return
    from tool_setup import managed_command

    settings = json.loads(
        subprocess.check_output(
            managed_command(["dart-decimate", "config", ".", "--format", "json"]),
            cwd=directory,
            text=True,
            timeout=timeout,
        )
    )["config"]
    boundaries = settings.get("boundaries")
    if (
        not isinstance(boundaries, list)
        or not boundaries
        or any(
            not isinstance(rule, dict)
            or not all(
                isinstance(rule.get(key), str)
                and rule[key].strip()
                and not any(mark in rule[key] for mark in "*?")
                for key in ("from", "disallow")
            )
            for rule in boundaries
        )
    ):
        raise ValueError(
            "Dart boundaries require nonempty project from/disallow prefixes, not globs"
        )


def initial_base(root: Path) -> str:
    """A new branch compares with its shipping-base merge base, else the empty tree."""
    from shipping import git, load_policy

    try:
        policy = load_policy(root, required=False)
        branch = f"refs/remotes/origin/{policy['base']}" if policy else "HEAD"
        merged = git(root, "merge-base", branch, "HEAD").strip()
        if merged != git(root, "rev-parse", "HEAD").strip():
            return merged
    except ValueError:
        pass
    return git(root, "hash-object", "-w", "-t", "tree", os.devnull).strip()


def changed_files(root: Path, base: str) -> set[str] | None:
    try:
        if re.fullmatch(r"0{40}|0{64}", base) or (
            base == "HEAD"
            and subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", "HEAD"],
                cwd=root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode
            == 1
        ):
            base = initial_base(root)
        changed = subprocess.check_output(
            ["git", "diff", "--name-only", "--no-renames", "-z", base, "--"],
            cwd=root,
            text=True,
        )
        changed += subprocess.check_output(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=root,
            text=True,
        )
    except subprocess.CalledProcessError:
        print("Impact base unavailable; checking all packages.")
        return None
    return set(changed.split("\0")) - {""}


def changed_packages(
    root: Path, by_path: dict[str, Group], base: str
) -> set[str] | None:
    from plans import is_documentation

    inputs = {path: impact_inputs(group) for path, group in by_path.items()}
    names = changed_files(root, base)
    if names is None:
        return None
    selected: set[str] = set()
    for name in names:
        if name.startswith((".hooks/", ".agents/", ".github/")) or name in {
            "hard-eng.gates.json",
            "AGENTS.md",
        }:
            return None
        consumers = {
            path
            for path, prefixes in inputs.items()
            if any(Path(name).is_relative_to(prefix) for prefix in prefixes)
        }
        if not consumers and is_documentation(Path(name)):
            continue
        matches = [path for path in by_path if Path(name).is_relative_to(path)]
        if not matches and not consumers:
            return None
        selected.update(consumers)
        if matches:
            selected.add(max(matches, key=len))
    return selected


def affected_groups(root: Path, groups: list[Group], base: str | None) -> list[Group]:
    packages = groups[:-1]
    if base is None or not packages:
        return groups
    by_path = {group["path"]: group for group in packages}
    if len(by_path) != len(packages):
        return groups
    selected = changed_packages(root, by_path, base)
    if selected is None:
        return groups
    if not selected:
        return [secrets_only(groups[-1])]
    guidance = dependency_review_guidance(packages)
    if any("depends_on" not in group for group in packages):
        if guidance is not None:
            print("Package impact is unknown; checking all packages. " + guidance)
        return groups
    selected = expand_dependents(packages, by_path, selected)
    print("Affected packages and dependents: " + ", ".join(sorted(selected)))
    return selected_services(root, packages, selected) + [groups[-1]]


def selected_services(
    root: Path, packages: list[Group], selected: set[str]
) -> list[Group]:
    """Retain ancestor-owned dependency checks without unrelated test suites."""
    affected = []
    for group in packages:
        if group["path"] in selected:
            affected.append(group)
        elif any(
            (root / path).resolve().is_relative_to((root / group["path"]).resolve())
            for path in selected
        ):
            services = [
                gate
                for gate in group["checks"]
                if gate.get("role") in {"lockfiles", "vulnerabilities"}
            ]
            if services:
                affected.append({**group, "checks": services})
    return affected


def validate_performance_gate(gate: Gate) -> None:
    if gate.get("role") != "performance":
        return
    if gate.get("parallel", False):
        raise ValueError("Performance suites must run serially")
    if gate.get("report", {}).get("type") not in {
        "performance-junit",
        "performance-dart",
        "lighthouse-ci",
    }:
        raise ValueError("Performance suite requires a supported native report")


def validate_group(root: Path, group: Group, report_paths: set[Path]) -> int:
    if (
        not isinstance(group, dict)
        or not isinstance(group.get("path"), str)
        or not isinstance(group.get("checks"), list)
    ):
        raise TypeError("Each gate group must contain a path and checks list")
    directory = (root / group["path"]).resolve()
    if not directory.is_relative_to(root) or not directory.is_dir():
        raise ValueError(
            f"Gate directory must exist inside the project: {group['path']}"
        )
    if group.get("language") not in {None, *LANGUAGES.values()}:
        raise ValueError(f"Unsupported package language: {group.get('language')}")
    impact_inputs(group)
    required = {
        "python": {
            "format",
            "lint",
            "complexity",
            "types",
            "annotations",
            "tests",
            "dead-code",
            "duplicates",
            "dependencies",
        },
        "javascript": {
            "format-lint",
            "focused-tests",
            "types",
            "typing-style",
            "tests",
            "dead-code-duplicates",
        },
        "dart": {"format", "types", "tests", "dead-code-duplicates", "boundaries"},
    }.get(group.get("language", ""), set())
    roles = {gate.get("role") for gate in group["checks"] if isinstance(gate, dict)}
    if group.get("language") == "dart" and any(
        dart_scan_includes_boundaries(gate) for gate in group["checks"]
    ):
        roles.add("boundaries")
    if required - roles:
        raise ValueError(
            f"{group['path']}: missing mandatory checks: {', '.join(sorted(required - roles))}"
        )
    if group.get("language") and "performance" not in roles:
        raise ValueError(
            "Missing mandatory performance suite; configure a workload and budget"
        )
    if group.get("language") == "javascript":
        from project_setup import javascript_manager, package_script_arguments

        javascript_manager(directory)
        for gate in group["checks"]:
            package_script_arguments(gate["command"], directory, pnpm_only=True)
    for gate in group["checks"]:
        validate_gate(gate, directory, report_paths)
        validate_performance_gate(gate)
    return len(group["checks"])


def require_roles(directory: str, required: set[str], roles: set[str]) -> None:
    if missing := required - roles:
        raise ValueError(
            f"{directory}: missing mandatory checks: {', '.join(sorted(missing))}"
        )


def validate_manifest_groups(
    root: Path, config: GateConfig, manifests: set[tuple[str, str]]
) -> None:
    from project_setup import workspace_members

    declared = {
        (str(Path(group["path"])), group.get("language")): group
        for group in config["packages"]
    }
    if len(declared) != len(config["packages"]):
        raise ValueError("Package path/language pairs must be unique")
    for path, language in manifests:
        if (path, language) in declared:
            continue
        group = declared.get((path, None))
        test_support = dart_test_support(path, language, config["packages"])
        if group is None:
            raise ValueError(
                f"Supported {language} package is missing from gate configuration: {path}"
                + (
                    "; declare a test-support package without language or sources,"
                    " with lockfile and vulnerability checks"
                    if test_support
                    else ""
                )
            )
        if group.get("sources") or not (
            test_support or workspace_members(root / path, language)
        ):
            raise ValueError(f"{path}: package language must be {language}")


def has_workflows(root: Path, files: list[Path]) -> bool:
    return any(
        path.parent == root / ".github/workflows" and path.suffix in {".yml", ".yaml"}
        for path in files
    )


def validate_required_checks(root: Path, config: GateConfig) -> None:
    from project_setup import is_deployment_file, is_shell_script

    files = repository_files(root)
    manifests = package_manifests(root, files)
    validate_manifest_groups(root, config, manifests)
    if not config["packages"] and not manifests:
        return  # Ad-hoc command groups without a supported application manifest.
    shared_roles = {gate.get("role", "") for gate in config["shared"]}
    required = {"secrets-files"}
    if config.get("scan_git_history", True):
        required.add("secrets-history")
    if has_workflows(root, files):
        required.update({"workflows", "ci-security"})
    if any(is_shell_script(path) for path in files):
        required.add("shell")
    if any(is_deployment_file(path) for path in files):
        required.add("deployment")
    for gate in config["shared"]:
        command = gate["command"]
        shared_roles.update(
            {
                "actionlint": {"workflows"},
                "zizmor": {"ci-security"},
                "shellcheck": {"shell"},
            }.get(Path(command[0]).name, set())
        )
        if Path(command[0]).name == "trivy" and "config" in command[1:]:
            shared_roles.add("deployment")
    require_roles("shared", required, shared_roles)
    workspace_languages = dict(manifests)
    by_directory = {
        (
            (root / group["path"]).resolve(),
            group.get("language")
            or workspace_languages.get(str(Path(group["path"])), ""),
        ): group
        for group in config["packages"]
    }
    typescript = typescript_packages(root, files)
    for group in config["packages"]:
        if str(Path(group["path"])) in typescript:
            require_roles(
                group["path"],
                {"boundaries"},
                {gate.get("role", "") for gate in group["checks"]},
            )
        validate_package_services(
            root,
            group,
            by_directory,
            workspace_languages,
            shared_roles,
            config["packages"],
        )


def validate_package_services(
    root: Path,
    group: Group,
    by_directory: dict[tuple[Path, str], Group],
    manifests: dict[str, str],
    shared_roles: set[str],
    package_groups: list[Group] | None = None,
) -> None:
    from project_setup import (
        dependency_command,
        python_roots,
        workspace_matches,
        workspace_members,
    )

    directory = (root / group["path"]).resolve()
    language = group.get("language") or manifests.get(str(Path(group["path"])), "")
    roles = {gate.get("role", "") for gate in group["checks"]}
    inherited = set(shared_roles)
    for owner in directory.parents:
        parent = by_directory.get((owner, language))
        if parent is not None and workspace_matches(
            str(directory.relative_to(owner)), workspace_members(owner, language)
        ):
            inherited.update(gate.get("role", "") for gate in parent["checks"])
    require_roles(group["path"], {"lockfiles", "vulnerabilities"}, roles | inherited)
    if language == "python":
        dependency_command(directory, language)  # Raises when no lockfile exists.
    if not group.get("language"):
        return
    require_roles(group["path"], {"security"}, roles | shared_roles)
    if language == "python" and python_roots(directory, group):
        require_roles(group["path"], {"imports"}, roles)
    if language == "javascript":
        from fallow_report import owns_package_fallow

        manifest = json.loads((directory / "package.json").read_text())
        if "check:fallow" in manifest.get("scripts", {}) and not any(
            owns_package_fallow(group, gate, manifest["scripts"], package_groups)
            for gate in group["checks"]
        ):
            raise ValueError(
                "Wire check:fallow into this package's gate with a native fallow report; a separate combined scan does not verify that audit"
            )
        dependencies = {
            **manifest.get("dependencies", {}),
            **manifest.get("devDependencies", {}),
        }
        required = {"react"} if "react" in dependencies else set()
        required.update(
            role
            for script, role in {
                "build": "build",
                "test:integration": "integration",
                "test:ui": "ui",
                "check:generated": "generated",
                "lint:boundaries": "boundaries",
            }.items()
            if script in manifest.get("scripts", {})
        )
        require_roles(group["path"], required, roles)


def parse_config(content: str) -> GateConfig:
    config = cast(GateConfig, json.loads(content))
    if (
        not isinstance(config, dict)
        or not isinstance(config.get("packages"), list)
        or not isinstance(config.get("shared"), list)
    ):
        raise TypeError(
            "Gate configuration must contain packages and shared lists; rerun the Hard Eng installer to regenerate a retired families configuration from the current templates"
        )
    return config


def load_groups(root: Path, base: str | None = None) -> list[Group]:
    validate_documents(root)
    config = parse_config((root / "hard-eng.gates.json").read_text())
    if type(config.get("scan_git_history", True)) is not bool:
        raise TypeError("scan_git_history must be true or false")
    if "shipping" in config:
        from shipping import load_policy

        load_policy(root)
    validate_file_sizes(root, config.get("file_size_exceptions", {}))
    if config.get("scan_git_history", True) is False:
        config["shared"] = [
            gate for gate in config["shared"] if gate.get("role") != "secrets-history"
        ]
    groups: list[Group] = [
        *config["packages"],
        {"path": ".", "checks": config["shared"]},
    ]
    report_paths: set[Path] = set()
    count = sum(validate_group(root, group, report_paths) for group in groups)
    if not count:
        raise ValueError("No checks configured; verification cannot pass")
    validate_required_checks(root, config)
    from gitleaks_scan import new_commits_command

    for gate in config["shared"]:
        if gate.get("role") == "secrets-history":
            gate["command"] = new_commits_command(gate["command"], root, base)
    return affected_groups(root, groups, base)
