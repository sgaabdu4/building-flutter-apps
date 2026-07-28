#!/usr/bin/env python3
"""Git subprocess environment sanitation for the bundled Dart Decimate gate."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Baseline mirror of `git rev-parse --local-env-vars` plus the hook-only
# variables Git omits from that list. The live list is unioned in at runtime.
LOCAL_ENV_VARS = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_CONFIG",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_PARAMETERS",
    "GIT_DIR",
    "GIT_GRAFT_FILE",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_INDEX_VERSION",
    "GIT_NAMESPACE",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_OBJECT_DIRECTORY",
    "GIT_PREFIX",
    "GIT_QUARANTINE_PATH",
    "GIT_REPLACE_REF_BASE",
    "GIT_SHALLOW_FILE",
    "GIT_WORK_TREE",
)

_STRIPPED: frozenset[str] | None = None


def stripped_variables() -> frozenset[str]:
    """Variable names removed from every sanitized environment."""
    global _STRIPPED
    if _STRIPPED is None:
        try:
            reported = subprocess.run(
                ["git", "rev-parse", "--local-env-vars"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.split()
        except (OSError, subprocess.SubprocessError):
            reported = []
        _STRIPPED = frozenset(LOCAL_ENV_VARS) | frozenset(reported)
    return _STRIPPED


def git_env(
    base: dict[str, str] | None = None,
    *,
    ceiling: str | os.PathLike[str] | None = None,
) -> dict[str, str]:
    """Return an environment without Git's per-invocation variables."""
    stripped = stripped_variables()
    source = os.environ if base is None else base
    env = {key: value for key, value in source.items() if key not in stripped}
    if ceiling is not None:
        env["GIT_CEILING_DIRECTORIES"] = str(Path(ceiling))
    return env


def scrub_environ(*, ceiling: str | os.PathLike[str] | None = None) -> None:
    """Sanitize this process's environment before it creates child processes."""
    for name in stripped_variables():
        os.environ.pop(name, None)
    if ceiling is not None:
        os.environ["GIT_CEILING_DIRECTORIES"] = str(Path(ceiling))
