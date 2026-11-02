"""Check out a worktree's pinned submodules, reusing a donor checkout's copies when it holds them."""

import re
import subprocess
from pathlib import Path
from typing import TextIO


def query(
    environment: dict[str, str] | None, directory: Path, *arguments: str
) -> str | None:
    found = subprocess.run(
        ["git", *arguments],
        cwd=directory,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    return found.stdout if found.returncode == 0 else None


def submodule_names(tree: Path, environment: dict[str, str] | None) -> dict[str, str]:
    declared = query(
        environment,
        tree,
        "config",
        "-f",
        ".gitmodules",
        "-z",
        "--get-regexp",
        r"^submodule\..*\.path$",
    )
    return {
        path: key.removeprefix("submodule.").removesuffix(".path")
        for key, _, path in (
            entry.partition("\n") for entry in (declared or "").split("\0") if entry
        )
    }


def donor_rewrites(
    tree: Path, donor: Path, environment: dict[str, str] | None
) -> tuple[list[str], list[str]]:
    """Paths of missing submodules that the donor holds at their pinned commit, and the URL rewrites to its copies."""
    query(environment, tree, "submodule", "init")
    names = submodule_names(tree, environment)
    copies: dict[str, Path] = {}
    paths: list[str] = []
    for line in (query(environment, tree, "submodule", "status") or "").splitlines():
        pinned = re.fullmatch(r"-([0-9a-f]{40}|[0-9a-f]{64}) (.+)", line)
        if (
            pinned is None
            or pinned[2] not in names
            or not (donor / pinned[2] / ".git").exists()
        ):
            continue
        url = (
            query(environment, tree, "config", f"submodule.{names[pinned[2]]}.url")
            or ""
        ).strip()
        held = (
            query(environment, donor / pinned[2], "rev-parse", "--absolute-git-dir")
            or ""
        ).strip()
        copy = copies.get(url) or (Path(held) if held else None)
        if (
            url
            and copy
            and query(environment, copy, "cat-file", "-e", f"{pinned[1]}^{{commit}}")
            is not None
        ):
            copies[url] = copy
            paths.append(pinned[2])
    return paths, [
        f"url.{copy.as_uri()}.insteadOf={url}" for url, copy in copies.items()
    ]


def reuse_submodules(
    tree: Path,
    donor: Path,
    environment: dict[str, str] | None,
    stdout: TextIO | None,
    timeout: float | None,
) -> None:
    """Clone each submodule the donor holds from the donor's copy, level by level; the rest is left unchanged."""
    if not (tree / ".gitmodules").is_file():
        return
    paths, rewrites = donor_rewrites(tree, donor, environment)
    if paths:
        subprocess.run(
            [
                "git",
                "-c",
                "protocol.file.allow=always",
                *(argument for rewrite in rewrites for argument in ("-c", rewrite)),
                "submodule",
                "update",
                "--init",
                "--depth=1",
                "--",
                *paths,
            ],
            cwd=tree,
            env=environment,
            stdout=stdout,
            timeout=timeout,
            check=False,
        )
    for path in submodule_names(tree, environment):
        if (tree / path / ".git").exists() and (donor / path / ".git").exists():
            reuse_submodules(tree / path, donor / path, environment, stdout, timeout)


def update_submodules(
    tree: Path,
    donor: Path | None = None,
    environment: dict[str, str] | None = None,
    stdout: TextIO | None = None,
    timeout: float | None = None,
) -> None:
    """Check out the pinned submodules, taking them from the donor's copies when it holds the pinned commits."""
    if not (tree / ".gitmodules").is_file():
        return
    if donor is not None:
        reuse_submodules(tree, donor, environment, stdout, timeout)
    subprocess.run(
        ["git", "submodule", "update", "--init", "--recursive", "--depth=1"],
        cwd=tree,
        env=environment,
        stdout=stdout,
        timeout=timeout,
        check=True,
    )
