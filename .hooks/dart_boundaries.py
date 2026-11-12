"""Read a Dart package's Dart Decimate boundary rules and refuse unusable ones."""

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast
from urllib.parse import unquote, urljoin, urlparse

if TYPE_CHECKING:
    from gate_config import JsonObject

SETTINGS_FILES = (
    ".dart-decimaterc",
    ".dart-decimaterc.json",
    ".dart-decimaterc.jsonc",
    "dart-decimate.toml",
    ".dart-decimate.toml",
)

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

NESTED_STEP = (
    ". This file replaces the package's settings for its folder: give it the `analyzer`"
    " and `linter` settings of the package's analysis_options.yaml, or remove it"
)


def dart_rule_settings(value: object) -> object:
    if isinstance(value, list):
        if not all(isinstance(rule, str) for rule in value):
            raise ValueError("Dart lint rule names must be strings")
        return {rule: True for rule in value}
    if isinstance(value, dict):
        for rule, enabled in value.items():
            if enabled is False:
                raise ValueError(
                    f"analysis_options.yaml: {rule} is set to false, which turns off "
                    "a lint rule of the included set; remove that entry"
                )
    return value


def validate_dart_plugins(options: "JsonObject") -> None:
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
    path: Path, directory: Path, seen: set[Path] | None = None, packaged: bool = False
) -> None:
    seen = set() if seen is None else seen
    path = path.resolve()
    if path in seen:
        raise ValueError(f"Recursive Dart analysis include: {path}")
    seen.add(path)
    from gate_config import JsonObject
    from project_setup import validate_dart_exclusions

    options = dart_options(path)

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
        package = include.startswith("package:")
        try:
            validate_dart_includes(
                included, directory, seen.copy(), packaged or package
            )
        except ValueError as error:
            if packaged or not package:
                raise
            raise ValueError(
                f"{error}. A package file cannot be changed: remove `include: {include}` "
                f"from {path} and list the lint rules that you need there"
            ) from error


def flutter_without_test(directory: Path) -> bool:
    """A Flutter project that does not list `test` cannot run its outside-lib tests on the Dart VM."""
    pubspec = directory / "pubspec.yaml"
    lines = pubspec.read_text().splitlines() if pubspec.is_file() else []
    return any(line.split() == ["sdk:", "flutter"] for line in lines) and not any(
        line.split(":")[0].strip() == "test" for line in lines
    )


def has_dart_file(directory: Path, prefix: str) -> bool:
    """Looks only below the prefix: this runs in every check, and a walk of all of lib/ is slow."""
    parent, _, start = prefix.rpartition("/")
    folder = directory / parent
    return folder.is_dir() and any(
        entry.suffix == ".dart"
        if entry.is_file()
        else next(entry.rglob("*.dart"), None) is not None
        for entry in folder.iterdir()
        if entry.name.startswith(start)
    )


def validate_dart_boundaries(
    command: list[str], directory: Path, timeout: float
) -> None:
    if command[:3] != ["dart-decimate", "check", "."]:
        return
    from tool_setup import managed_command

    try:
        output = subprocess.check_output(
            managed_command(["dart-decimate", "config", ".", "--format", "json"]),
            cwd=directory,
            text=True,
            timeout=timeout,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as error:
        lines = (error.stderr or error.output or "").strip().splitlines()
        raise ValueError(
            f"{directory.name}: dart-decimate config failed: " + " ".join(lines[-3:])
        ) from error
    settings = json.loads(output)["config"]
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
            "Dart boundaries are missing or not usable: each rule needs a `from` and a "
            "`disallow` folder prefix of this project, with no `*` or `?`. Set "
            '"boundaries": [{"from": "lib/domain", "disallow": "lib/ui"}] with your own '
            "prefixes in the package's Dart Decimate settings file; if the package "
            "has none, make .dart-decimaterc.json for it"
        )
    settings_file = next(
        (name for name in SETTINGS_FILES if (directory / name).exists()),
        "the Dart Decimate settings file",
    )
    for rule in boundaries:
        for prefix in (rule["from"], rule["disallow"]):
            if not has_dart_file(directory, prefix):
                raise ValueError(
                    f"{directory.name}: the boundary prefix {prefix} in {settings_file} "
                    "matches no .dart file; correct the prefix or remove the rule"
                )


def validate_dart_typing(
    directory: Path, sources: list[str] | tuple[str, ...], package_root: Path | None
) -> None:
    from gate_config import JsonObject
    from project_setup import validate_dart_exclusions

    path = directory / "analysis_options.yaml"
    options = dart_options(path)
    where = f": {path}" + ("" if package_root in (None, directory) else NESTED_STEP)
    for section, groups in DART_TYPING.items():
        for group, settings in groups.items():
            section_options = cast(JsonObject, options).get(section)
            if not isinstance(section_options, dict):
                raise TypeError(f"Dart requires {section} settings{where}")
            actual = section_options.get(group)
            if group == "rules":
                actual = dart_rule_settings(actual)
            if isinstance(settings, list):
                validate_dart_exclusions(directory, section_options.get(group, []))
                continue
            if not isinstance(actual, dict) or any(
                actual.get(key) != value for key, value in settings.items()
            ):
                raise ValueError(
                    f"Dart requires strict {section}.{group} settings{where}"
                )
    validate_dart_includes(path, package_root or directory)
    for source in {*sources, "test", "tests"}:
        for nested in (directory / source).rglob("analysis_options.yaml"):
            if nested.parent != directory:
                validate_dart_typing(nested.parent, (), package_root or directory)
