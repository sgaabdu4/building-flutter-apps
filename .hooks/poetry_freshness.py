"""Name the Poetry step for stale rows from the section of pyproject.toml that declares each one."""

import os
import re
import shlex
import subprocess
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

from freshness import Stale, newer
from tool_setup import managed_command

REQUIREMENT = re.compile(
    r"\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*(?P<extras>\[[^\]]*\])?"
    r"\s*(?P<spec>[^;]*?)\s*(?:;\s*(?P<marker>.*?))?\s*"
)
LOWER_BOUND = re.compile(r"(?:>=|~=|\^|~)\s*(\d+(?:\.\d+)*)")
SEPARATORS = re.compile(r"[-_.]+")
OPERATION = re.compile(
    r"^\s*- (?:Installing|Updating|Downgrading) (?P<name>\S+) \((?P<versions>[^)]*)\)",
    re.MULTILINE,
)
LEGACY = ("dev-dependencies",)
LOCK_STEP = "POETRY_SOLVER_MIN_RELEASE_AGE=2 uvx poetry lock"
STEP = "POETRY_SOLVER_MIN_RELEASE_AGE=2 uvx poetry add"
TABLE_FLAGS = {
    "markers": "--markers",
    "python": "--python",
    "platform": "--platform",
    "source": "--source",
}


class Declared(NamedTuple):
    options: tuple[str, ...]
    head: str
    tail: str
    unsupported: str = ""
    lower: str = ""


def canonical(name: str) -> str:
    return SEPARATORS.sub("-", name).lower()


def lower_bound(spec: object) -> str:
    found = LOWER_BOUND.search(spec) if isinstance(spec, str) else None
    return found[1] if found else ""


def table(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def sections(data: dict[str, object]) -> Iterator[tuple[tuple[str, ...], object]]:
    project = table(data.get("project"))
    yield (), project.get("dependencies", [])
    for extra, items in table(project.get("optional-dependencies")).items():
        yield ("--optional", extra), items
    for group, items in table(data.get("dependency-groups")).items():
        yield ("--group", group), items
    poetry = table(table(data.get("tool")).get("poetry"))
    yield (), poetry.get("dependencies", {})
    yield LEGACY, poetry.get("dev-dependencies", {})
    for group, body in table(poetry.get("group")).items():
        yield ("--group", group), table(body).get("dependencies", {})


def requirement(options: tuple[str, ...], text: str) -> tuple[str, Declared] | None:
    found = REQUIREMENT.fullmatch(text)
    if found is None:
        return None
    name, spec = found["name"], found["spec"]
    marker = f"; {found['marker']}" if found["marker"] else ""
    if spec.startswith("@"):
        return name, Declared(options, name, marker, "url")
    head = name + (found["extras"] or "")
    return name, Declared(options, head, marker, lower=lower_bound(spec))


def poetry_entry(options: tuple[str, ...], name: str, value: object) -> Declared:
    if isinstance(value, str):
        return Declared(options, name, "", lower=lower_bound(value))
    body = table(value)
    allowed = {"version", "extras", "allow-prereleases", *TABLE_FLAGS}
    other = sorted(set(body) - allowed) or ([] if "version" in body else ["version"])
    if other or not body:
        return Declared(options, name, "", other[0] if other else "version")
    flags = [
        item
        for key, flag in TABLE_FLAGS.items()
        if key in body
        for item in (flag, str(body[key]))
    ]
    if body.get("allow-prereleases"):
        flags.append("--allow-prereleases")
    listed = body.get("extras")
    extras = ",".join(map(str, listed)) if isinstance(listed, list) else ""
    head = f"{name}[{extras}]" if extras else name
    return Declared((*options, *flags), head, "", lower=lower_bound(body["version"]))


def declarations(directory: Path) -> dict[str, list[Declared]]:
    path = directory / "pyproject.toml"
    if not path.is_file():
        return {}
    found: dict[str, list[Declared]] = {}
    for options, items in sections(tomllib.loads(path.read_text())):
        if isinstance(items, list):
            parsed = [
                requirement(options, item) for item in items if isinstance(item, str)
            ]
            entries = [item for item in parsed if item]
        else:
            entries = [
                (name, poetry_entry(options, name, value))
                for name, value in table(items).items()
                if name != "python"
            ]
        for name, entry in entries:
            found.setdefault(canonical(name), []).append(entry)
    return found


def lock_floors(directory: Path) -> dict[str, str]:
    """The lowest version of each name in poetry.lock, which a split lock holds once for each Python range."""
    path = directory / "poetry.lock"
    packages = (
        tomllib.loads(path.read_text()).get("package", []) if path.is_file() else []
    )
    floors: dict[str, str] = {}
    for package in packages:
        name, version = canonical(package["name"]), package["version"]
        if name not in floors or newer(floors[name], version):
            floors[name] = version
    return floors


def floor(item: Declared, floors: dict[str, str], name: str, current: str) -> str:
    """The lowest locked version, raised to the declared lower bound when that is higher."""
    locked = floors.get(canonical(name), current)
    return item.lower if newer(item.lower, locked) else locked


def poetry_steps(directory: Path, stale: list[Stale]) -> str:
    declared = declarations(directory)
    floors = lock_floors(directory)
    lines: dict[tuple[str, ...], list[str]] = {}
    legacy = False
    by_hand: list[str] = []
    for name, current, _ in stale:
        items = declared.get(canonical(name), [])
        legacy = legacy or any(item.options == LEGACY for item in items)
        by_hand += [] if items else [name]
        for item in items:
            if not item.unsupported and item.options != LEGACY:
                lines.setdefault(item.options, []).append(
                    f"{item.head}>={floor(item, floors, name, current)}{item.tail}"
                )
    commands = [
        " ".join([STEP, *map(shlex.quote, options), *map(shlex.quote, entries)])
        for options, entries in lines.items()
    ]
    parts = [
        f"Run `{'`, then `'.join(commands)}` in a separate PR first (baseline repair)."
    ] * bool(commands)
    if legacy:
        parts.append(
            "Move the entries of [tool.poetry.dev-dependencies] to [tool.poetry.group.dev.dependencies] "
            "(Poetry reads the old section as the dev group), "
            f"then run `{LOCK_STEP}` and the check again."
        )
    if by_hand:
        parts.append(f"Raise {' and '.join(by_hand)} by hand in pyproject.toml.")
    return " ".join(parts)


def solver_versions(directory: Path, args: list[str]) -> dict[str, str]:
    """The version that Poetry's solver picks for each package that its dry run lists."""
    environment = {**os.environ, "POETRY_SOLVER_MIN_RELEASE_AGE": "2"}
    done = subprocess.run(
        managed_command(["poetry", *args]),
        cwd=directory,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    if done.returncode:
        shown = " ".join(shlex.quote(argument) for argument in args)
        raise ValueError(
            f"`uvx poetry {shown}` failed: {(done.stdout + done.stderr).strip()}"
        )
    return {
        canonical(found["name"]): found["versions"].rpartition("-> ")[2]
        for found in OPERATION.finditer(done.stdout)
    }


def print_stays(
    stale: list[Stale], first: dict[str, tuple[str, ...]], picked: dict[str, str]
) -> None:
    for name, current, latest in stale:
        if name in first and name not in picked:
            shown = " ".join(
                ["uvx poetry add --dry-run", *map(shlex.quote, first[name])]
                + [f"'{name}=={latest}'"]
            )
            print(
                f"{name} stays at {current}: {latest} does not install with this project's Python range or pins; `{shown}` shows why"
            )


def poetry_targets(directory: Path, stale: list[Stale]) -> list[Stale]:
    """Replace each latest version by the newest one that installs with the project's pins."""
    declared = declarations(directory)
    plans: dict[tuple[str, ...], list[tuple[Stale, Declared]]] = {}
    first: dict[str, tuple[str, ...]] = {}
    kept = []
    for row in stale:
        name, _, latest = row
        items = declared.get(canonical(name), [])
        if not items or any(item.options == LEGACY for item in items):
            kept.append(row)
            continue
        raisable = [item for item in items if not item.unsupported]
        for item in raisable or items:
            if not raisable:
                print(
                    f"{name} {latest}: Hard Eng cannot raise a {item.unsupported} entry; update it by hand"
                )
        for item in raisable:
            plans.setdefault(item.options, []).append((row, item))
            first.setdefault(name, item.options)
    picked: dict[str, str] = {}
    floors = lock_floors(directory) if plans else {}
    for options, plan in plans.items():
        entries = [
            f"{item.head}>={floor(item, floors, row[0], row[1])}{item.tail}"
            for row, item in plan
        ]
        versions = solver_versions(
            directory, ["add", "--dry-run", "--no-ansi", "-n", *options, *entries]
        )
        for (name, current, latest), _ in plan:
            version = versions.get(canonical(name), latest)
            if newer(version, picked.get(name, current)):
                picked[name] = version
    print_stays(stale, first, picked)
    moved = {
        name: (name, current, picked[name])
        for name, current, _ in stale
        if name in picked
    }
    return [moved.get(row[0], row) for row in stale if row[0] in moved or row in kept]
