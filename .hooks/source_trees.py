"""Keep each fetched pair of Hard Eng source trees for the rest of the run."""

import atexit
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

Trees = tuple[Path, Path]
Key = tuple[str, str, str]
HELD: dict[Key, tuple[tempfile.TemporaryDirectory[str], Trees]] = {}


def pristine(tree: Path, revision: str) -> bool:
    """Whether the tree still sits on the revision with nothing changed, submodules included."""
    state = [
        subprocess.run(
            ["git", *arguments],
            cwd=tree,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        for arguments in (
            ["rev-parse", "HEAD"],
            ["status", "--porcelain", "--untracked-files=all"],
        )
    ]
    return (
        all(result.returncode == 0 for result in state)
        and state[0].stdout.strip() == revision
        and not state[1].stdout
    )


def forget(key: Key) -> None:
    held = HELD.pop(key, None)
    if held is not None:
        held[0].cleanup()


def forget_all() -> None:
    for key in list(HELD):
        forget(key)


def shared(
    repository: str,
    revision: str,
    previous: str,
    fetch: Callable[[Path, str, str], Trees],
) -> Trees:
    """The trees for these revisions, fetched once; a tree a caller changed is fetched again."""
    key = (repository, revision, previous)
    held = HELD.get(key)
    if held is not None:
        if all(map(pristine, held[1], (revision, previous))):
            return held[1]
        forget(key)
    directory = tempfile.TemporaryDirectory(
        prefix="hard-eng-scaffold-check-", ignore_cleanup_errors=True
    )
    try:
        trees = fetch(Path(directory.name), revision, previous)
    except BaseException:
        directory.cleanup()
        raise
    HELD[key] = (directory, trees)
    return trees


atexit.register(forget_all)
