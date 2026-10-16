"""Swift groups for the Xcode projects in a Flutter app's ios/ and macos/ folders."""

import hashlib
import json
import os
import re
import shutil
from collections.abc import Iterable
from functools import cache
from pathlib import Path
from typing import NamedTuple

from gate_config import (
    GateConfig,
    Group,
    generated_sources,
    package_manifests,
    repository_files,
)

PLATFORMS = ("ios", "macos")
NOT_AUTHORED = {"Flutter", "Pods"}
TEST_FLAGS = (
    "-only-testing",
    "-skip-testing",
    "-only-test-configuration",
    "-skip-test-configuration",
    "-testPlan",
)
STARTER_NAMES = {
    "AppDelegate.swift",
    "SceneDelegate.swift",
    "MainFlutterWindow.swift",
    "RunnerTests.swift",
}
# Fingerprints of the released Flutter app templates for the files above.
RELEASED_STARTERS = frozenset(
    {
        "1eff988992eb32b0",
        "25fb1e3fb54302ea",
        "6251df1a8fde5169",
        "6928c708042f490b",
        "815cfc0b59f4cb43",
        "86f43c5b2d1d3c55",
        "968d685a6b01ce2a",
        "9f5a4831570b4f04",
        "a4d2c4a98ede38d7",
        "a73afd9acac29914",
        "bf11566752275639",
        "c0d7b928e905c1bc",
        "d71330b02bace6a0",
        "dfb836aa6951c81d",
        "e5fecc57b992ed4a",
        "f22e19fc036a16ef",
    }
)
TEMPLATE = Path(__file__).resolve().parents[1] / (
    ".agents/skills/he/templates/hard-eng.swift.json"
)


class SwiftProject(NamedTuple):
    sources: list[str]
    tests: list[str]
    pods: bool


def fingerprint(text: str) -> str:
    """The text without comments, whitespace and the plugin-only template sections."""
    text = re.sub(r"\{\{\^(\w+)\}\}(.*?)\{\{/\1\}\}", r"\2", text, flags=re.DOTALL)
    text = re.sub(r"\{\{#(\w+)\}\}.*?\{\{/\1\}\}", "", text, flags=re.DOTALL)
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.DOTALL)
    return hashlib.sha256(re.sub(r"\s+", "", text).encode()).hexdigest()[:16]


@cache
def installed_templates() -> frozenset[str]:
    """Fingerprints of the app templates in the installed Flutter SDK, newer than the list."""
    flutter = shutil.which("flutter")
    if flutter is None:
        return frozenset()
    templates = Path(flutter).resolve().parents[1] / "packages/flutter_tools/templates"
    return frozenset(
        fingerprint(path.read_text(errors="replace"))
        for path in templates.glob("app*/*/*/*.swift*")
        if path.name.removesuffix(".tmpl") in STARTER_NAMES
    )


def unchanged_starters(files: Iterable[Path]) -> set[Path]:
    """Swift files that `flutter create` wrote and the project has not changed."""
    known = RELEASED_STARTERS | installed_templates()
    return {
        file
        for file in files
        if file.name == "GeneratedPluginRegistrant.swift"
        or (
            file.name in STARTER_NAMES
            and fingerprint(file.read_text(errors="replace")) in known
        )
    }


def flutter_apps(root: Path, files: list[Path]) -> list[str]:
    from project_setup import dependency_command

    return sorted(
        path
        for path, language in package_manifests(root, files)
        if language == "dart"
        and dependency_command(root / path, "dart")[0] == "flutter"
    )


def swift_projects(
    root: Path, files: list[Path] | None = None
) -> dict[str, SwiftProject]:
    """Platform folders of Flutter apps that hold an Xcode project and authored Swift."""
    files = repository_files(root) if files is None else files
    names = [str(path.relative_to(root)) for path in files]
    authored = set(names) - generated_sources(root, names)
    found: dict[str, SwiftProject] = {}
    for app in flutter_apps(root, files):
        for platform in PLATFORMS:
            base = Path(app) / platform
            if str(base / "Runner.xcodeproj/project.pbxproj") not in authored:
                continue
            swift = [
                name
                for name in authored
                if name.endswith(".swift") and Path(name).is_relative_to(base)
            ]
            starters = {
                str(file.relative_to(root))
                for file in unchanged_starters(root / name for name in swift)
            }

            def folders(names: Iterable[str], base: Path = base) -> set[str]:
                return {Path(name).relative_to(base).parts[0] for name in names}

            tests = {
                f for f in folders(swift) if f.removesuffix(".swift").endswith("Tests")
            }
            if sources := sorted(folders(set(swift) - starters) - tests - NOT_AUTHORED):
                found[str(base)] = SwiftProject(
                    sources,
                    sorted(tests),
                    str(base / "Podfile") in authored,
                )
    return found


def swift_group(root: Path, path: str, project: SwiftProject) -> Group:
    package = json.loads(TEMPLATE.read_text())["packages"][0]
    directory = root / path
    expansion = {"Runner": project.sources, "RunnerTests": project.tests}
    package["name"] = package["path"] = path
    package["sources"] = project.sources
    for gate in package["checks"]:
        gate["command"] = [
            value
            for argument in gate["command"]
            for value in (
                [os.path.relpath(root / argument, directory)]
                if argument == ".agents/skills/he/security"
                else expansion.get(argument, [argument])
            )
        ]
    if project.pods:
        package["checks"].insert(
            0,
            {
                "name": "pods-locked",
                "role": "lockfiles",
                "command": [
                    "sh",
                    "-c",
                    'flutter precache --"$(basename "$PWD")" && pod install --deployment',
                ],
            },
        )
    return package


def local_plugin_folders(root: Path, app: Path, path: str) -> list[str]:
    """Native folders of the path dependencies, whose Swift builds into the app."""
    import yaml

    manifest = yaml.safe_load((root / app / "pubspec.yaml").read_text()) or {}
    folders: list[str] = []
    for section in ("dependencies", "dev_dependencies", "dependency_overrides"):
        for value in (manifest.get(section) or {}).values():
            if isinstance(value, dict) and isinstance(value.get("path"), str):
                plugin = Path(os.path.normpath(root / app / value["path"]))
                if plugin.is_relative_to(root):
                    relative = plugin.relative_to(root)
                    folders += [
                        str(relative / Path(path).name),
                        str(relative / "darwin"),
                    ]
    return folders


def watched_inputs(root: Path, app: Path, path: str) -> list[str]:
    """Files whose change can alter the Swift build: dependency files and local plugins."""
    from project_setup import workspace_matches, workspace_members

    files = [app / "pubspec.yaml", app / "pubspec.lock"]
    for owner in app.parents:
        if (root / owner / "pubspec.yaml").is_file() and workspace_matches(
            str(app.relative_to(owner)), workspace_members(root / owner, "dart")
        ):
            files += [owner / "pubspec.yaml", owner / "pubspec.lock"]
    return [*map(str, files), *local_plugin_folders(root, app, path)]


def add_swift_groups(root: Path, config: GateConfig) -> None:
    """Add a group for each Swift platform folder the configuration lacks."""
    projects = swift_projects(root)
    stale = {
        group["path"]
        for group in config["packages"]
        if group.get("language") == "swift"
        and Path(group["path"]).name in PLATFORMS
        and str(Path(group["path"])) not in projects
    }
    config["packages"][:] = [g for g in config["packages"] if g["path"] not in stale]
    for group in config["packages"]:
        if "depends_on" in group:
            group["depends_on"] = [d for d in group["depends_on"] if d not in stale]
    declared = {str(Path(group["path"])): group for group in config["packages"]}
    single = len(declared) == 1
    for path, project in projects.items():
        if path in declared:
            continue
        app = Path(path).parent
        parent = declared.get(str(app))
        group = swift_group(root, path, project)
        group["depends_on"] = []
        group["impact_inputs"] = watched_inputs(root, app, path)
        if parent is not None and single:
            parent.setdefault("depends_on", [])
        config["packages"].append(group)


def require_swift_groups(root: Path, config: GateConfig, files: list[Path]) -> None:
    declared = {str(Path(group["path"])): group for group in config["packages"]}
    projects = swift_projects(root, files)
    for path, group in declared.items():
        if (
            group.get("language") == "swift"
            and Path(path).name in PLATFORMS
            and path not in projects
        ):
            raise ValueError(
                f"{path}: all of its Swift is Flutter starter code; rerun setup to remove the group"
            )
    if missing := sorted(set(projects) - declared.keys()):
        raise ValueError(
            f"Swift code is missing from gate configuration: {', '.join(missing)}; "
            "rerun setup to add its group"
        )
    for path, project in projects.items():
        if declared[path].get("language") != "swift":
            raise ValueError(
                f"{path}: the group holding Swift code must declare language swift"
            )
        app = Path(path).parent
        group = declared[path]
        stale = set(watched_inputs(root, app, path)) - set(
            group.get("impact_inputs", [])
        )
        if stale and str(app) not in group.get("depends_on", []):
            raise ValueError(
                f"{path}: impact_inputs must list {', '.join(sorted(stale))} "
                "so a change to them selects the Swift checks"
            )
        roles = {gate.get("role") for gate in group["checks"]}
        if project.pods and "lockfiles" not in roles:
            raise ValueError(
                f"{path}: a Podfile needs the pods-locked gate (`pod install --deployment`) "
                "before the tests; add it as a lockfiles check"
            )
        if folders := unscanned(declared[path], project):
            raise ValueError(
                f"{path}: Swift folders {', '.join(folders)} are outside the group's "
                "sources or its format, duplicate and security commands; add them to each"
            )


def parent_roles(
    directory: Path, by_directory: dict[tuple[Path, str], Group]
) -> set[str]:
    """Roles a Flutter app supplies to the Swift group in its ios/ or macos/ folder."""
    from project_setup import workspace_matches, workspace_members

    app = directory.parent
    parent = by_directory.get((app, "dart"))
    if directory.name not in PLATFORMS or parent is None:
        return set()
    roles = {gate.get("role", "") for gate in parent["checks"]}
    for owner in app.parents:
        workspace = by_directory.get((owner, "dart"))
        if workspace is not None and workspace_matches(
            str(app.relative_to(owner)), workspace_members(owner, "dart")
        ):
            roles |= {gate.get("role", "") for gate in workspace["checks"]}
    return roles


def unscanned(group: Group, project: SwiftProject) -> list[str]:
    scopes = {
        "format-lint": [*project.sources, *project.tests],
        "duplicates": project.sources,
        "security": [*project.sources, *project.tests],
    }
    folders = {name for name in project.sources if name not in group["sources"]}
    for gate in group["checks"]:
        folders |= {
            name
            for name in scopes.get(gate.get("role", ""), [])
            if name not in gate["command"]
        }
    return sorted(folders)


def reject_test_filters(command: list[str]) -> None:
    for flag in TEST_FLAGS:
        if any(flag in argument for argument in command):
            raise ValueError(
                f"Focused test selection is not allowed in the full-suite gate: {flag}"
            )
