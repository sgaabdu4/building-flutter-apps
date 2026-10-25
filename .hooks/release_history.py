"""Place an installed Hard Eng release in upstream history, rewrites included."""

import subprocess
import sys
from pathlib import Path


class StaleRelease(ValueError):
    """The recorded release cannot be placed in upstream history."""


def _git(source: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=source,
        check=False,
        timeout=120,
        capture_output=True,
        text=True,
    )


def ordered(source: Path, revision: str, previous: str) -> None:
    """A history rewrite leaves the recorded release off main; GitHub still serves it by ID."""
    if (
        _git(source, "cat-file", "-e", previous + "^{commit}").returncode
        and _git(
            source, "fetch", "--quiet", "--filter=blob:none", "origin", previous
        ).returncode
    ):
        raise StaleRelease(
            f"Recorded Hard Eng release {previous} in .hooks/hard-eng-source.json is "
            "not in upstream history; rerun the Hard Eng installer from the README "
            "to refresh the record"
        )
    if _git(source, "merge-base", "--is-ancestor", previous, revision).returncode:
        times = [
            int(_git(source, "log", "-1", "--format=%ct", name).stdout)
            for name in (previous, revision)
        ]
        if times[0] >= times[1]:
            raise StaleRelease(
                f"Recorded Hard Eng release {previous} is not older than {revision}"
            )
        print(
            f"Hard Eng: recorded release {previous} left upstream history (a "
            "rewrite); updating from its own tree.",
            file=sys.stderr,
        )
