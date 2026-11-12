"""Review and traverse explicit package-impact dependencies."""

from __future__ import annotations

from collections import deque
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gate_config import Group

SOURCE_SUFFIXES = {
    "python": {".py"},
    "javascript": {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"},
    "dart": {".dart"},
    "swift": {".swift"},
}


def owner_language(by_path: dict[str, Group], name: str) -> str | None:
    matches = [path for path in by_path if Path(name).is_relative_to(path)]
    return by_path[max(matches, key=len)].get("language") if matches else None


def child_groups(group: Group, role: str | None, groups: list[Group]) -> list[Group]:
    """Groups below this one in its language that have a gate of the same role."""
    return [
        child
        for child in groups
        if child["path"] != group["path"]
        and (group["path"] == "." or Path(child["path"]).is_relative_to(group["path"]))
        and child.get("language") == group.get("language")
        and any(check.get("role") == role for check in child["checks"])
    ]


def impact_inputs(group: Group) -> list[PurePosixPath]:
    inputs = group.get("impact_inputs", [])
    if not isinstance(inputs, list) or any(
        not isinstance(value, str)
        or not value.strip()
        or value.strip("./") == ""
        or PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).drive
        or ".." in PurePosixPath(value).parts
        or any(mark in value for mark in "*?[]\\")
        for value in inputs
    ):
        raise ValueError(
            "impact_inputs must list explicit repository-relative files or directory "
            "prefixes without globs or parent traversal"
        )
    return [PurePosixPath(value) for value in inputs]


def dependency_review_guidance(packages: list[Group]) -> str | None:
    if len(packages) < 2:
        return None
    missing = [group["path"] for group in packages if "depends_on" not in group]
    if missing:
        return (
            "Review `depends_on` in hard-eng.gates.json for "
            + ", ".join(missing)
            + "; list direct internal dependencies, including root "
            "packages that supply shared lockfiles or tools. Use [] only after "
            "review confirms none."
        )
    reach = reachable(packages)
    entries = [
        f"`{group['path']}` -> `{dependency}`"
        for group in packages
        for dependency in group["depends_on"]
        if dependency in reach.get(dependency, ())
        and group["path"] not in reach[dependency]
    ]
    if not entries:
        return None
    return (
        "These packages depend on a member of a dependency cycle they are not "
        "part of, so every change in that cycle checks them: "
        + ", ".join(entries)
        + ". Replace each edge with `impact_inputs` naming the files the package "
        "reads from that member."
    )


def reachable(packages: list[Group]) -> dict[str, set[str]]:
    edges: dict[str, set[str]] = {}
    for group in packages:
        edges.setdefault(group["path"], set()).update(group["depends_on"])
    reach: dict[str, set[str]] = {}
    for start, direct in edges.items():
        seen: set[str] = set()
        pending = list(direct)
        while pending:
            if (node := pending.pop()) not in seen:
                seen.add(node)
                pending.extend(edges.get(node, ()))
        reach[start] = seen
    return reach


def expand_dependents(
    packages: list[Group], by_path: dict[str, Group], selected: set[str]
) -> set[str]:
    dependents: dict[str, list[str]] = {name: [] for name in by_path}
    for group in packages:
        for dependency in group["depends_on"]:
            if dependency not in by_path:
                raise ValueError(f"Unknown package dependency: {dependency}")
            dependents[dependency].append(group["path"])
    pending = deque(selected)
    while pending:
        for dependent in dependents[pending.popleft()]:
            if dependent not in selected:
                selected.add(dependent)
                pending.append(dependent)
    return selected


def cycle_members(
    packages: list[Group], by_path: dict[str, Group], selected: set[str]
) -> set[str]:
    """Selected packages plus the ones they share a cycle with, as Fallow coverage needs."""
    if any("depends_on" not in group for group in packages):
        return selected
    reached = expand_dependents(packages, by_path, set(selected))
    return {
        path
        for path in reached
        if selected & expand_dependents(packages, by_path, {path})
    }


def is_workflow(name: str) -> bool:
    path = PurePosixPath(name)
    return path.parent == PurePosixPath(".github/workflows") and path.suffix in {
        ".yml",
        ".yaml",
    }


def shared_only(shared: Group, names: set[str]) -> Group:
    """No package reads the change; workflow edits still need workflow linting."""
    roles = {"secrets-files", "secrets-history"}
    if any(name.startswith(".github/workflows/") for name in names):
        print("No package reads this change; running workflow and secret checks.")
        roles |= {"workflows", "ci-security"}
    else:
        print("No package reads this change; running the secret scan only.")
    checks = [gate for gate in shared["checks"] if gate.get("role") in roles]
    return {**shared, "checks": checks}


def readers_above(by_path: dict[str, Group], name: str, nearest: str) -> set[str]:
    """A file of another language than its group is also read by the nearest group above it of its own."""
    suffix = Path(name).suffix
    language = next(
        (key for key, kinds in SOURCE_SUFFIXES.items() if suffix in kinds), None
    )
    if language is None or by_path[nearest].get("language") == language:
        return set()
    above = [
        path
        for path, group in by_path.items()
        if group.get("language") == language
        and path != nearest
        and Path(nearest).is_relative_to(path)
    ]
    return {max(above, key=len)} if above else set()
