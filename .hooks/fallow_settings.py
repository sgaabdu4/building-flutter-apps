"""Refuse a Fallow settings file that raises a health limit, skips files from the complexity analysis or lowers a complexity rule."""

import json
import subprocess
import tomllib
from pathlib import Path, PurePosixPath

from fallow_report import HEALTH_LIMITS
from project_files import GIT_LISTING

SETTINGS_FILES = {".fallowrc.json", ".fallowrc.jsonc", "fallow.toml", ".fallow.toml"}
LIMIT_KEYS = {
    "maxCyclomatic": "max_cyclomatic_threshold",
    "maxCognitive": "max_cognitive_threshold",
    "maxCrap": "max_crap_threshold",
    "maxUnitSize": "max_unit_size_threshold",
}


def read_settings(name: str, text: str) -> dict[str, object]:
    if name.endswith(".toml"):
        try:
            return tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return {}
    from untrusted_input import jsonc_config

    try:
        return jsonc_config(name, text)
    except (ValueError, TypeError):
        return {}


def tables(value: object) -> list[dict[str, object]]:
    items = value if isinstance(value, list) else [value]
    return [item for item in items if isinstance(item, dict)]


def limit_findings(table: dict[str, object]) -> list[tuple[str, str]]:
    found = []
    for key, snake in LIMIT_KEYS.items():
        value = table.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if value > HEALTH_LIMITS[snake] or (key == "maxCrap" and value <= 0):
            found.append((key, f"to {value}, outside the limit {HEALTH_LIMITS[snake]}"))
    return found


def health_findings(config: dict[str, object]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for health in tables(config.get("health")):
        found += limit_findings(health)
        if health.get("ignore"):
            found.append(("ignore", "to skip files from the complexity analysis"))
        for override in tables(health.get("thresholdOverrides")):
            found += limit_findings(override)
    return found


def rule_findings(config: dict[str, object]) -> list[tuple[str, str]]:
    sets = tables(config.get("rules"))
    sets += [
        rules
        for item in tables(config.get("overrides"))
        for rules in tables(item.get("rules"))
    ]
    return [
        (key, f"to {level!r}, below error")
        for rules in sets
        for key, level in rules.items()
        if key.startswith("complexity-") and level != "error"
    ]


def own_hits(name: str, text: str, config: dict[str, object]) -> list[str]:
    lines = text.splitlines()
    used: set[int] = set()
    found: list[str] = []
    findings = [
        *health_findings(config),
        *rule_findings(config),
    ]
    for key, reason in findings:
        number = next(
            (n for n, line in enumerate(lines, 1) if key in line and n not in used), 1
        )
        used.add(number)
        found.append(f"{name}:{number} sets {key} {reason}")
    return found


def extended_names(config: dict[str, object]) -> list[str]:
    extends = config.get("extends")
    items = [extends] if isinstance(extends, str) else extends
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, str)]


def package_parts(spec: str) -> tuple[str, str]:
    """The package name and the file inside it that an `npm:` name asks for."""
    parts = spec.split("/", 2 if spec.startswith("@") else 1)
    size = 2 if spec.startswith("@") else 1
    return "/".join(parts[:size]), "/".join(parts[size:])


def workspace_package(root: Path, package: str) -> Path | None:
    listed = subprocess.run(
        [*GIT_LISTING, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    for name in listed.split("\0"):
        if name.endswith("package.json") and PurePosixPath(name).name == "package.json":
            try:
                found = json.loads((root / name).read_text())
            except (OSError, ValueError):
                continue
            if isinstance(found, dict) and found.get("name") == package:
                return (root / name).parent
    return None


def npm_config(root: Path, name: str, spec: str) -> Path | None:
    """The config file that Fallow loads for `npm:<spec>`, from node_modules above the extending file or from a workspace package."""
    package, inner = package_parts(spec)
    here = (root / name).parent.resolve()
    folders = [
        folder / "node_modules" / package
        for folder in (here, *here.parents)
        if folder == root.resolve() or root.resolve() in folder.parents
    ]
    folder = next((f for f in folders if f.is_dir()), None) or workspace_package(
        root, package
    )
    if folder is None:
        return None
    if inner:
        return next(
            (c for c in (folder / inner, folder / (inner + ".json")) if c.is_file()),
            None,
        )
    try:
        main = json.loads((folder / "package.json").read_text()).get("main")
    except (OSError, ValueError, AttributeError):
        main = None
    names = [main] if isinstance(main, str) else []
    names += [".fallowrc.json", ".fallowrc.jsonc", "fallow.json", "index.json"]
    return next((folder / n for n in names if (folder / n).is_file()), None)


def extended_target(root: Path, name: str, extended: str) -> Path | str | None:
    """The file an `extends` entry names, a refusal text, or None when it cannot be read here."""
    if "://" in extended:
        return "extends a remote file, which no check can read"
    if extended.startswith("npm:"):
        return npm_config(root, name, extended.removeprefix("npm:"))
    return ((root / name).parent / extended).resolve()


def file_hits(root: Path, name: str, text: str, seen: frozenset[Path]) -> list[str]:
    config = read_settings(name, text)
    found = own_hits(name, text, config)
    for extended in extended_names(config):
        target = extended_target(root, name, extended)
        if isinstance(target, str):
            found.append(f"{name}:1 {target}")
        elif target is None:
            continue
        elif not target.resolve().is_relative_to(root.resolve()):
            found.append(f"{name}:1 extends a file outside the repository")
        elif target.is_file() and target not in seen:
            relative = target.resolve().relative_to(root.resolve()).as_posix()
            found += file_hits(
                root, relative, target.read_text(errors="replace"), seen | {target}
            )
    return found


def settings_switch_offs(root: Path, name: str, text: str) -> list[str]:
    """One hit for each key line that raises a limit, skips files or lowers a complexity rule, in the file and in every file it extends."""
    return file_hits(root, name, text, frozenset({(root / name).resolve()}))


def named_config_hits(directory: Path, path: str) -> list[str]:
    """The hits of a config file that a gate command names."""
    target = (directory / path).resolve()
    if not target.is_file() or not target.is_relative_to(directory.resolve()):
        return (
            [
                f"{path}:1 {'is outside the repository' if target.is_file() else 'is not a file'}"
            ]
            if target.is_file()
            else []
        )
    relative = target.relative_to(directory.resolve()).as_posix()
    return file_hits(
        directory, relative, target.read_text(errors="replace"), frozenset({target})
    )
