"""Judge the config that Dart Decimate prints for a gate: no rule off, no limit raised, no hand-written file dropped."""

import json
import posixpath
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from dart_boundaries import SETTINGS_FILES
from fallow_report import HEALTH_LIMITS
from fallow_resolved import committed
from fallow_table import GLOB_CHARACTERS, number, strings
from scope_check import glob_regex, left_out, tracked
from tool_setup import managed_command

DART_SKIPPED = frozenset({".dart_tool", "build"})
DECIMATE_KEYS = {
    "path": "free",
    "output_format": "free",
    "entry_points": "named",
    "production": "free",
    "include_entry_exports": "free",
    "boundaries": "free",
    "boundary_presets": "free",
    "boundary_coverage": "free",
    "boundary_allow_unmatched": "free",
    "boundary_calls": "free",
    "policy_packs": "free",
    "ignore_patterns": "patterns",
    "ignore_dependencies": "equal",
    "ignore_dependency_overrides": "equal",
    "cache.enabled": "free",
    "cache.path": "free",
    "health.max_cyclomatic": "limit",
    "health.max_cognitive": "limit",
    "health.max_unit_size": "limit",
    "health.max_crap": "limit",
    "health.top": "equal",
    "health.complexity_breakdown": "free",
    "health.coverage_path": "equal",
    "health.coverage_gaps": "free",
    "health.runtime_coverage": "equal",
    "health.min_invocations_hot": "free",
    "health.min_observation_volume": "free",
    "health.low_traffic_threshold": "free",
    "health.file_scores": "free",
    "health.hotspots": "free",
    "health.targets": "free",
    "health.ownership": "free",
    "health.flutter_style": "equal",
    "health.min_score": "free",
    "health.threshold_overrides": "overrides",
    "dupes.mode": "equal",
    "dupes.min_tokens": "limit",
    "dupes.min_lines": "limit",
    "dupes.min_occurrences": "limit",
    "dupes.threshold": "limit",
    "dupes.top": "equal",
    "dupes.skip_local": "equal",
    "dupes.ignore_imports": "equal",
    "dupes.ignore_mapper_pairs": "equal",
    "flags.top": "free",
    "flags.allow": "free",
    "security.top": "free",
    "security.surface": "free",
    "security.categories": "free",
    "rules": "rules",
}
LIMITS = {
    "health.max_cyclomatic": 20,
    "health.max_cognitive": HEALTH_LIMITS["max_cognitive_threshold"],
    "health.max_unit_size": HEALTH_LIMITS["max_unit_size_threshold"],
    "health.max_crap": HEALTH_LIMITS["max_crap_threshold"],
    "dupes.min_tokens": 50,
    "dupes.min_lines": 5,
    "dupes.min_occurrences": 2,
    "dupes.threshold": 0,
}
Drop = Callable[[list[str]], list[str]]
VALUE_OPTIONS = frozenset(
    [
        "--root",
        "--format",
        "--config",
        "--entry",
        "--dart-platform",
        "--workspace",
        "--changed-workspaces",
        "--changed-since",
        "--compare",
        "--regression-baseline",
        "--save-regression-baseline",
        "--tolerance",
        "--baseline",
        "--save-baseline",
        "--boundary",
        "--boundary-call",
        "--policy-pack",
        "--max-cyclomatic",
        "--max-cognitive",
        "--max-unit-size",
        "--coverage",
        "--max-crap",
        "--runtime-coverage",
        "--min-invocations-hot",
        "--min-observation-volume",
        "--low-traffic-threshold",
        "--min-score",
        "--mode",
        "--min-tokens",
        "--min-lines",
        "--min-occurrences",
        "--top",
        "--threshold",
        "--file",
    ]
)


def printed_config(
    directory: Path, config: str | None, timeout: float
) -> dict[str, object]:
    command = ["dart-decimate", "config", ".", "--format", "json"]
    done = subprocess.run(
        managed_command(
            [*command, *(["--config", config] if config else [])], directory
        ),
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if done.returncode:
        raise ValueError(
            f"HE-NO-SWITCH-OFF: dart-decimate cannot read its config: {done.stdout.strip() or done.stderr.strip()}"
        )
    return json.loads(done.stdout)["config"]


def default_config(timeout: float) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="hard-eng-decimate-") as empty:
        return printed_config(Path(empty), None, timeout)


def flatten(config: dict[str, object]) -> dict[str, object]:
    """Each printed setting under its dotted name; a group of settings is read through, and the rules stay whole."""
    found: dict[str, object] = {}
    for key, value in config.items():
        if isinstance(value, dict) and key != "rules":
            found.update({f"{key}.{inner}": item for inner, item in value.items()})
        else:
            found[key] = value
    return found


def limit_hits(name: str, value: object) -> list[str]:
    now = number(value)
    if value is None or (
        now is not None
        and now <= LIMITS[name]
        and (name != "health.max_crap" or now > 0)
    ):
        return []
    return [f"{name} is {value!r}, above the limit {LIMITS[name]}"]


def override_hits(value: object) -> list[str]:
    hits = []
    for item in value if isinstance(value, list) else []:
        for name in ("max_cyclomatic", "max_cognitive", "max_unit_size", "max_crap"):
            hits += [
                f"health.threshold_overrides: {hit}"
                for hit in limit_hits(f"health.{name}", item.get(name))
            ]
    return hits


def rule_hits(value: object) -> list[str]:
    return [
        f"rule {name} is {level}, which no longer fails the scan"
        for name, level in (value.items() if isinstance(value, dict) else [])
        if level not in {"error", "warn"}
    ]


def key_hits(
    name: str,
    value: object,
    default: object,
    drop: Drop,
) -> list[str]:
    kind = DECIMATE_KEYS.get(name)
    if kind is None or kind == "equal":
        if value == default:
            return []
        note = "" if kind else ", and no table classes it"
        return [f"{name} is {value!r}, not its default {default!r}{note}"]
    if kind == "limit":
        return limit_hits(name, value)
    if kind == "overrides":
        return override_hits(value)
    if kind == "rules":
        return rule_hits(value)
    if kind == "named":
        return [
            f"{name} lists {text!r}, a glob that marks many files; list each file by name"
            for text in strings(value)
            if any(mark in text for mark in GLOB_CHARACTERS)
        ]
    if kind == "patterns":
        return [
            *(
                f"{name} lists {text!r}, a form this check cannot read; use only * and ** and a path below the folder"
                for text in strings(value)
                if any(mark in text for mark in "[]{}!?") or text.startswith("/")
            ),
            *(f"{name}: {hit}" for hit in drop(strings(value))),
        ]
    return []


def judge(
    config: dict[str, object],
    defaults: dict[str, object],
    drop: Drop,
) -> list[str]:
    """What the printed Dart Decimate config does wrong, key by key, compared with the tool's own defaults."""
    base = flatten(defaults)
    return [
        hit
        for name, value in flatten(config).items()
        for hit in key_hits(name, value, base.get(name), drop)
    ]


def pattern_hits(directory: Path, children: frozenset[str]) -> Drop:
    """A check for the patterns of one setting: each tracked Dart file that a pattern drops must be generated or belong to a child group."""

    def drop(patterns: list[str]) -> list[str]:
        if not patterns:
            return []
        names = tracked(directory, (".dart",))
        regexes = [glob_regex(pattern) for pattern in patterns]
        bases = {directory.as_posix(), directory.resolve().as_posix()}

        def dropped(name: str) -> bool:
            """The tool matches a pattern against the relative path and the absolute one."""
            full = [name, *(f"{base}/{name}" for base in bases)]
            return any(r.fullmatch(path) for r in regexes for path in full)

        kept = {name for name in names if not dropped(name)}
        left = left_out(directory, (".dart",), kept, children, DART_SKIPPED)
        return [f"drops {name}" for name in left[:1]] if left else []

    return drop


def untracked_configs(directory: Path) -> list[str]:
    """A settings file that Git does not track: a script can write it just before the run."""
    return [
        f"{name} is not tracked by Git: commit it, because a file that a script writes can change what Dart Decimate reports"
        for name in SETTINGS_FILES
        if (directory / name).is_file() and not committed(directory, directory / name)
    ]


def scanned_folder(command: list[str]) -> str:
    """The folder that a `dart-decimate check` command scans: its `--root` value, which the tool puts first, else its plain word, else `.`."""
    plain = "."
    skip = False
    for word in command[2:]:
        if skip:
            skip = False
        elif word.startswith("--root="):
            return posixpath.normpath(word.removeprefix("--root="))
        elif word == "--root":
            return posixpath.normpath(command[command.index(word, 2) + 1])
        elif word in VALUE_OPTIONS:
            skip = True
        elif not word.startswith("-") and plain == ".":
            plain = word
    return posixpath.normpath(plain)


INSTALLED_FLAGS = {"--strict": "", "--boundary-violations": "boundaries"}
INSTALLED_VALUES = {"--threshold": "0", "--format": "json"}


def option_hits(command: list[str], role: str) -> list[str]:
    """The options of a `dart-decimate check` command beyond the installed forms (`check . --threshold 0 --strict --format json` and `check . --boundary-violations --strict`): the tool reads each before its settings file, and each narrows the files it scans, picks what it reports or raises a limit."""
    hits = []
    words = command[2:]
    index = 0
    while index < len(words):
        name, equals, value = words[index].partition("=")
        step = 2 if name in VALUE_OPTIONS and not equals else 1
        if name.startswith("-") and name not in {"--root", "--config"}:
            given = value if equals else "".join(words[index + 1 : index + 2])
            if not equals and INSTALLED_FLAGS.get(name) in {"", role}:
                pass
            elif INSTALLED_VALUES.get(name) != given:
                hits.append(
                    f"Dart Decimate option {name} changes what the scan covers or a limit: run only `check . --threshold 0 --format json --strict` or `check . --boundary-violations --strict`, and set the rest in the settings file, which Hard Eng judges"
                )
        index += step
    return hits


def decimate_hits(
    directory: Path,
    config: str | None,
    children: frozenset[str],
    defaults: dict[str, object],
    timeout: float,
) -> list[str]:
    printed = printed_config(directory, config, timeout)
    drop = pattern_hits(directory, children)
    return [
        *judge(
            printed,
            defaults,
            drop,
        ),
        *untracked_configs(directory),
    ]
