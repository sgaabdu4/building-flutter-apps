"""A step plan names its parent plan; the parent closes only after every step."""

import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from plans import STAGES, header_status, plan_files

PARENT_LINE = re.compile(r"(?m)^Parent:[ \t]*(.*?)[ \t]*$")


def header(path: Path) -> str:
    return path.read_text().split("\n## ", 1)[0]


def parent_name(path: Path) -> str | None:
    found = PARENT_LINE.findall(header(path))
    if len(found) > 1:
        raise ValueError("plan needs one 'Parent:' line at most")
    if found and not found[0]:
        raise ValueError("'Parent:' needs the parent plan's path")
    return found[0] if found else None


def find_plan(root: Path, name: str) -> Path | None:
    wanted = PurePosixPath(name).as_posix().lower()
    return next(
        (
            path
            for path in plan_files(root)
            if path.relative_to(root).as_posix().lower() == wanted
        ),
        None,
    )


def parent_problem(root: Path, path: Path) -> None:
    """Raise when the plan's Parent line is wrong, or when a parent closes before its steps."""
    name = parent_name(path)
    if name is None:
        return close_problem(root, path)
    parent = find_plan(root, name)
    if parent is None or parent == path:
        raise ValueError(f"Parent {name} is not a plan; name an existing plan")
    if not path.parent.is_relative_to(parent.parent) or path.parent == parent.parent:
        raise ValueError(f"Parent {name} must sit above this plan's folder")
    if parent_name(parent) is not None:
        raise ValueError(f"Parent {name} has its own Parent; steps have one level")
    status_problem(
        name, header_status(parent.read_text()), header_status(path.read_text())
    )


def status_problem(name: str, parent: str, step: str) -> None:
    if parent not in {"Ready", "Complete"}:
        raise ValueError(f"Parent {name} is {parent}; it must be Ready or Complete")
    if parent == "Complete" and step != "Complete":
        raise ValueError(
            f"Parent {name} is Complete; this step is {step} and must not be open"
        )


def steps(root: Path, parent: Path) -> list[Path]:
    """The plans below the parent's folder whose Parent line names it."""
    return [
        step
        for step in plan_files(root)
        if step.is_relative_to(parent.parent)
        and step.parent != parent.parent
        and (named := parent_name(step))
        and find_plan(root, named) == parent
    ]


def may_ride_along(
    root: Path, path: Path, status: str, judged: Mapping[Path, str], stage: str
) -> bool:
    """A Draft claims no implementation; a Ready parent holds the open steps."""
    return status == "Draft" or (
        status == "Ready"
        and any(
            STAGES.index(judged[step]) >= STAGES.index(stage)
            for step in steps(root, path)
            if step in judged
        )
    )


def named_parents(texts: Mapping[str, str]) -> set[str]:
    """The plans among the texts that another plan below their folder names as its parent."""
    from plans import is_plan_path

    held = {PurePosixPath(name).as_posix().lower(): name for name in texts}
    found: set[str] = set()
    for name, text in texts.items():
        if not is_plan_path(Path(name)):
            continue
        for line in PARENT_LINE.findall(text.split("\n## ", 1)[0]):
            parent = held.get(PurePosixPath(line).as_posix().lower())
            if (
                parent
                and parent != name
                and PurePosixPath(name).parent.is_relative_to(
                    PurePosixPath(parent).parent
                )
            ):
                found.add(parent)
    return found


def close_problem(root: Path, path: Path) -> None:
    if header_status(path.read_text()) != "Complete":
        return
    for step in steps(root, path):
        status = header_status(step.read_text())
        if status != "Complete":
            raise ValueError(
                f"step {step.relative_to(root)} is {status}; "
                "a parent closes after every step is Complete"
            )
