"""Ask a tool which files it checks and compare that with the files git tracks."""

import re
import subprocess
import tomllib
from pathlib import Path, PurePosixPath

from generated_marks import generated_sources
from project_files import GIT_LISTING

SOURCE_FOLDERS = frozenset(
    {
        ".bzr",
        ".direnv",
        ".eggs",
        ".git",
        ".git-rewrite",
        ".hg",
        ".ipynb_checkpoints",
        ".mypy_cache",
        ".nox",
        ".pants.d",
        ".pyenv",
        ".pytest_cache",
        ".pytype",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".venv",
        ".vscode",
        "__pypackages__",
        "_build",
        "buck-out",
        "dist",
        "node_modules",
        "site-packages",
        "venv",
    }
)
MARKER = ".hooks/hard-eng-source.json"


def glob_regex(pattern: str) -> re.Pattern[str]:
    """A glob as Fallow reads it; `*` is taken to cross folders, so a pattern never drops fewer files than it names."""
    pattern = pattern + "**" if pattern.endswith("/") else pattern
    out = "" if "/" in pattern else "(?:.*/)?"
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out += "(?:.*/)?"
            index += 3
        elif pattern[index] == "*":
            out += ".*"
            index += 2 if pattern.startswith("**", index) else 1
        elif pattern[index] == "?":
            out += "[^/]"
            index += 1
        else:
            out += re.escape(pattern[index])
            index += 1
    return re.compile(out)


def tracked(directory: Path, suffixes: tuple[str, ...]) -> list[str]:
    """Tracked and new files below a folder, relative to it, with one of the suffixes."""
    listed = subprocess.run(
        [*GIT_LISTING, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return [
        name
        for name in listed.split("\0")
        if name.endswith(suffixes) and (directory / name).is_file()
    ]


def installed_files(directory: Path) -> set[str]:
    """The files Hard Eng writes into a project, which the project does not check; Hard Eng's own source has no such files."""
    if not (directory / MARKER).is_file():
        return set()
    from update import scaffold_files

    names = {
        path.relative_to(directory).as_posix()
        for path in (directory / ".hooks").rglob("*")
        if path.is_file()
    }
    if (directory / ".agents/skills").is_dir():
        names |= scaffold_files(directory)
    return names


def left_out(
    directory: Path,
    suffixes: tuple[str, ...],
    checked: set[str],
    children: frozenset[str],
    skipped: frozenset[str] = SOURCE_FOLDERS,
) -> list[str]:
    """Tracked files that the tool does not check, less the installed files, the linguist-generated files, the files of a child group and the tool's own default folders."""
    names = [
        name
        for name in tracked(directory, suffixes)
        if name not in checked and not skipped & set(PurePosixPath(name).parts)
    ]
    if not names:
        return []
    own = installed_files(directory) | generated_sources(
        directory, names, generated_only=True
    )
    nested = [glob_regex(child) for child in children]
    return [
        name
        for name in names
        if name not in own and not any(child.fullmatch(name) for child in nested)
    ]


def refusal(left: list[str], role: object = None) -> list[str]:
    if not left:
        return []
    more = f" and {len(left) - 1} more" if len(left) > 1 else ""
    fix = f"; add {left[0]} to the {role} gate's paths" if role else ""
    return [
        f"the tool does not check {left[0]}{more}, which git tracks; every tracked source file must be checked, or be linguist-generated or belong to a child gate group{fix}"
    ]


RUFF_CONFIGS = {"ruff.toml", ".ruff.toml", "pyproject.toml"}
FALLOW_CONFIGS = {".fallowrc.json", ".fallowrc.jsonc", "fallow.toml", ".fallow.toml"}


def requires_python(directory: Path) -> tuple[int, int] | None:
    """The lowest Python version the project supports, which Ruff uses as its target when no target is set."""
    try:
        project = tomllib.loads((directory / "pyproject.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None
    found = MINIMUM_VERSION.search(
        str(project.get("project", {}).get("requires-python", ""))
    )
    return (int(found[1]), int(found[2])) if found else None


def requires_python_of(directory: Path, sample: str | None) -> tuple[int, int] | None:
    """The minimum of the nearest `pyproject.toml` at or above the sample file, up to the gate folder; a member package has its own."""
    base = directory.resolve()
    if sample is None:
        return requires_python(base)
    for folder in [(base / sample).parent, *(base / sample).parent.parents]:
        if (folder / "pyproject.toml").is_file() and (found := requires_python(folder)):
            return found
        if folder == base:
            break
    return requires_python(base)


def ruff_config_of(folder: Path) -> bool:
    """A folder holds a config that Ruff reads: a `ruff.toml`, a `.ruff.toml` or a `pyproject.toml` with a ruff table."""
    if (folder / "ruff.toml").is_file() or (folder / ".ruff.toml").is_file():
        return True
    try:
        project = tomllib.loads((folder / "pyproject.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return False
    tool = project.get("tool")
    return isinstance(tool, dict) and "ruff" in tool


MINIMUM_VERSION = re.compile(r"(?:>=|~=)\s*(\d+)\.(\d+)")
TARGET_VERSION = re.compile(r"py(\d)(\d+)")
RUFF_SUFFIXES = (".py", ".pyi", ".pyw", ".ipynb")


def governing_samples(directory: Path, checked: set[str]) -> list[str]:
    """One checked Python file for each distinct Ruff config that governs a file of the gate, so each config is judged."""
    base = directory.resolve()
    chosen: dict[Path, str] = {}
    own = installed_files(directory)
    for name in sorted(checked):
        if not name.endswith(RUFF_SUFFIXES) or name in own:
            continue
        folder = (base / name).parent
        found = base
        for candidate in [folder, *folder.parents]:
            if ruff_config_of(candidate):
                found = candidate
                break
            if candidate == base or (candidate / ".git").exists():
                found = candidate
                break
        chosen.setdefault(found, name)
    return list(chosen.values())


def harmless_ruff_config(name: str, directory: Path) -> bool:
    """A `pyproject.toml` with no ruff table, or a ruff config that sets only a target version at the `requires-python` minimum; any other key can change what is reported."""
    try:
        config = tomllib.loads((directory / name).read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return False
    if PurePosixPath(name).name == "pyproject.toml":
        tool = config.get("tool")
        if not (isinstance(tool, dict) and "ruff" in tool):
            return True
        config = tool["ruff"]
    minimum = requires_python_of(directory, name)
    found = TARGET_VERSION.fullmatch(str(config.get("target-version", "")))
    return (
        set(config) == {"target-version"}
        and minimum is not None
        and found is not None
        and (int(found[1]), int(found[2])) == minimum
    )


def nested_configs(directory: Path, tool: str, roots: frozenset[Path]) -> list[str]:
    """A tool config below a gate root that is not a gate root itself: the tool would read it for some files and the gate would not judge it."""
    wanted = RUFF_CONFIGS if tool == "ruff" else FALLOW_CONFIGS
    own = installed_files(directory)
    found = []
    for name in tracked(directory, tuple(wanted)):
        path = PurePosixPath(name)
        if path.name not in wanted or not path.parent.parts or name in own:
            continue
        if (directory / path.parent).resolve() in roots:
            continue
        if tool == "ruff" and harmless_ruff_config(name, directory):
            continue
        found.append(name)
    return [
        f"{name} configures {tool} below the gate root {directory.name or '.'}; give it its own gate group"
        for name in found
    ]
