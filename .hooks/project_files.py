"""Read a project file that a person edits; a syntax error names the file."""

import json
import subprocess
import sys
import threading
from collections.abc import Callable, Container, Generator, Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from gate_config import Group

INSTALL_LOCKS = {
    "uv": "uv.lock",
    "poetry": "poetry.lock",
    "bun": "bun.lock",
    "dart": "pubspec.lock",
    "flutter": "pubspec.lock",
}
INSTALL_STEP = "run the project's install to write the file, "
KINDS = {".toml": "TOML", ".yaml": "YAML", ".yml": "YAML"}
KEPT: dict[str, dict[tuple[str, ...], object]] = {}


@contextmanager
def keeping(*scopes: str) -> Generator[None]:
    """Keep what keep() answers in each named scope until the block ends, also on an error."""
    opened = [name for name in scopes if name not in KEPT]
    for name in opened:
        KEPT[name] = {}
    try:
        yield
    finally:
        for name in opened:
            KEPT.pop(name, None)


def stop_keeping(scope: str) -> None:
    """End a scope before its block ends."""
    KEPT.pop(scope, None)


def keep[T](scope: str, key: tuple[str, ...], make: Callable[[], T]) -> T:
    """The answer of make() for this key, asked one time while the scope is open; asked each time when it is not."""
    store = KEPT.get(scope)
    if store is None:
        return make()
    if key not in store:
        store[key] = make()
    return cast(T, store[key])


def tell_once(text: str) -> None:
    """Write the text to the error stream; while a check keeps its listings, each line only one time."""
    if "listings" not in KEPT:
        sys.stderr.write(text)
        return
    told: set[str] = keep("listings", ("told",), set)
    for line in text.splitlines(keepends=True):
        if line not in told:
            told.add(line)
            sys.stderr.write(line)


def background[T](
    work: Callable[[], T], errors: tuple[type[Exception], ...]
) -> Callable[[], T]:
    """Start work on its own thread now; the returned call waits, then gives the answer or raises the named error that ended the work."""
    done: list[T | Exception] = []

    def run() -> None:
        try:
            done.append(work())
        except errors as error:
            done.append(error)

    thread = threading.Thread(target=run)
    thread.start()

    def answer() -> T:
        thread.join()
        outcome = done[0] if done else OSError("background work stopped")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return answer


def clean_tree(root: Path) -> tuple[str, bool] | None:
    """The commit that HEAD names and whether Git sees no change, submodules included."""
    status = subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "status",
            "--porcelain=v2",
            "--branch",
            "--no-ahead-behind",
            "--ignore-submodules=none",
            "--untracked-files=normal",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    lines = status.stdout.splitlines()
    heads = [line.split()[2] for line in lines if line.startswith("# branch.oid ")]
    if status.returncode or len(heads) != 1 or not heads[0].isalnum():
        return None
    return heads[0], all(line.startswith("# ") for line in lines)


def syntax_errors() -> tuple[type[Exception], ...]:
    """PyYAML's error is no ValueError, and PyYAML is loaded only when a caller parses YAML."""
    yaml = sys.modules.get("yaml")
    return (ValueError, yaml.YAMLError) if yaml else (ValueError,)


def syntax_error(name: str, error: Exception) -> ValueError:
    mark = getattr(error, "problem_mark", None)
    where = f": line {mark.line + 1} column {mark.column + 1}" if mark else ""
    reason = getattr(error, "problem", None) or (str(error).splitlines() or [""])[0]
    kind = KINDS.get(Path(name).suffix, "JSON")
    return ValueError(f"{name} is not valid {kind}: {reason}{where}")


def parse_project_text[T](
    text: str, name: str, parse: Callable[[str], T] = json.loads
) -> T:
    try:
        return parse(text)
    except syntax_errors() as error:
        raise syntax_error(name, error) from error


def repository_name(path: Path, root: Path | None) -> str:
    if root is None:
        root = next(
            (
                parent
                for parent in path.parents
                if (parent / "hard-eng.gates.json").exists()
                or (parent / ".git").exists()
            ),
            path.parent,
        )
    return path.relative_to(root).as_posix()


def read_project_file[T](
    path: Path, root: Path | None = None, parse: Callable[[str], T] = json.loads
) -> T:
    try:
        return parse(path.read_text())
    except syntax_errors() as error:
        raise syntax_error(repository_name(path, root), error) from error


def group_locks(root: Path, groups: Iterable["Group"]) -> Generator[Path]:
    """The lock file that the install command of each group's lockfile gate reads."""
    for group in groups:
        for check in group["checks"]:
            name = INSTALL_LOCKS.get(check["command"][0])
            if check.get("role") == "lockfiles" and name:
                yield root / group["path"] / name


def ignored_text(relative: object, step: str) -> str:
    return (
        f"{relative} is ignored by Git, so the install fails in a fresh clone. "
        f"`git check-ignore -v {relative}` names the rule, often in .gitignore; "
        f"remove that rule, {step}then commit {relative}"
    )


def missing_lock_error(directory: Path, name: str, message: str) -> ValueError:
    """The missing-lockfile message; when Git ignores the file, which need not exist, it names the rule to remove too."""
    ignored = not subprocess.run(
        ["git", "check-ignore", "-q", name], cwd=directory, check=False
    ).returncode
    if not ignored:
        return ValueError(message)
    prefix = subprocess.run(
        ["git", "rev-parse", "--show-prefix"],
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return ValueError(f"{message}. {ignored_text(prefix + name, '')}")


def refuse_ignored_locks(
    root: Path, locks: Iterable[Path], listed: Container[str], *, ask_git: bool
) -> None:
    """A lock file that Git ignores is missing from a fresh clone; ask Git when the file is not on disk yet or is a link at setup."""
    for lockfile in locks:
        relative = lockfile.relative_to(root)
        written = lockfile.is_file()
        if written and not (ask_git and lockfile.is_symlink()):
            ignored = str(relative) not in listed
        else:
            ignored = (
                ask_git
                and not subprocess.run(
                    ["git", "check-ignore", "-q", str(relative)], cwd=root, check=False
                ).returncode
            )
        if ignored:
            raise ValueError(ignored_text(relative, "" if written else INSTALL_STEP))


def dependency_free(directory: Path) -> bool:
    """Bun deletes the lockfile of a package that declares nothing to install."""
    path = directory / "package.json"
    manifest = read_project_file(path) if path.is_file() else None
    fields = (
        "dependencies",
        "devDependencies",
        "optionalDependencies",
        "peerDependencies",
    )
    return (
        isinstance(manifest, dict)
        and not manifest.get("workspaces")
        and not any(manifest.get(key) for key in fields)
    )


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
