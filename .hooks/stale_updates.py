"""Remove what an ended update or push check left behind: candidate worktrees and temporary folders."""

import os
import re
import shutil
import subprocess
import tempfile
import time
from contextlib import suppress
from pathlib import Path

OWNER = re.compile(r"hard-eng-update (\d+)")
TEMPORARY = re.compile(
    r"hard-eng-(?:update|push|gate|gitleaks|dart-parser|scaffold-check|mutation)-[a-z0-9_]{8}"
)
WORKTREE = re.compile(r"hard-eng-(?:update-.+/candidate|push-.+/project)")


def alive(process: int) -> bool:
    try:
        os.kill(process, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def abandoned(path: Path, owner: re.Match[str] | None) -> bool:
    """Updaters before the lock ran under a one-hour hook, and a push's checks end within a day."""
    if owner is not None:
        return not alive(int(owner[1]))
    hours = 6 if path.name == "candidate" else 24
    try:
        return time.time() - path.parent.stat().st_mtime > hours * 3600
    except FileNotFoundError:
        return False


def sweep_temporary() -> None:
    """Directories a killed Hard Eng process left behind; none of its runs lasts a day."""
    for path in Path(tempfile.gettempdir()).iterdir():
        with suppress(OSError):
            if (
                TEMPORARY.fullmatch(path.name)
                and path.is_dir()
                and not path.is_symlink()
                and time.time() - path.stat().st_mtime > 24 * 3600
            ):
                shutil.rmtree(path)


def stop_idle_watcher(worktree: Path) -> None:
    """Git restarts a file watcher on the next command, so stopping an idle one loses nothing."""
    with suppress(OSError, subprocess.SubprocessError):
        index = subprocess.check_output(
            ["git", "rev-parse", "--path-format=absolute", "--git-path", "index"],
            cwd=worktree,
            text=True,
            timeout=30,
        ).strip()
        if time.time() - Path(index).stat().st_mtime > 24 * 3600:
            subprocess.run(
                ["git", "fsmonitor--daemon", "stop"],
                cwd=worktree,
                capture_output=True,
                timeout=30,
                check=False,
            )


def registered_worktrees(root: Path) -> list[dict[str, str]]:
    listing = subprocess.check_output(
        ["git", "worktree", "list", "--porcelain"], cwd=root, text=True
    )
    return [
        {
            key: value
            for key, _, value in (line.partition(" ") for line in block.splitlines())
        }
        for block in listing.split("\n\n")
    ]


def remove_stale_candidates(root: Path) -> None:
    """Remove candidates whose update has exited; the caller holds the lock."""
    for fields in registered_worktrees(root):
        path = Path(fields.get("worktree", ""))
        owner = OWNER.fullmatch(fields.get("locked", ""))
        if not WORKTREE.fullmatch(f"{path.parent.name}/{path.name}"):
            if path.is_dir() and path.resolve() != root.resolve():
                stop_idle_watcher(path)
            continue
        if not abandoned(path, owner):
            continue
        if owner is not None and not path.exists():
            subprocess.run(
                ["git", "worktree", "unlock", str(path)], cwd=root, check=True
            )
        elif not subprocess.run(
            ["git", "worktree", "remove", "--force", "--force", str(path)],
            cwd=root,
            check=False,
            timeout=120,
        ).returncode:
            shutil.rmtree(path.parent, ignore_errors=True)
    sweep_temporary()
    subprocess.run(["git", "worktree", "prune"], cwd=root, check=True, timeout=60)


MARKER = "# Hard Eng worktree launcher, local to this checkout"


def git_run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments], cwd=root, capture_output=True, text=True, check=False
    )


def common_dir(root: Path) -> Path:
    found = git_run(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(found.stdout.strip()).resolve()


def worktree_place(root: Path, target: Path) -> tuple[str, str, Path]:
    """Where a hook file sits: in Git's folder, tracked, ignored or loose in the main checkout, or elsewhere."""
    common = common_dir(root)
    place = target.resolve()
    main = common.parent
    if place.is_relative_to(common):
        return "git", "", main
    folder = next(path for path in place.parents if path.is_dir())
    top = git_run(folder, "rev-parse", "--show-toplevel").stdout.strip()
    if common.name != ".git" or not top or Path(top).resolve() != main:
        return "elsewhere", "", main
    name = place.relative_to(main).as_posix()
    if git_run(main, "ls-files", "--error-unmatch", "--", name).returncode == 0:
        return "tracked", name, main
    if git_run(main, "check-ignore", "-q", "--", name).returncode == 0:
        return "ignored", name, main
    return "loose", name, main


def committed_bytes(root: Path, name: str) -> bytes | None:
    revision = "HEAD:" + name
    shown = subprocess.run(
        ["git", "show", revision], cwd=root, capture_output=True, check=False
    )
    return None if shown.returncode else shown.stdout


def exclude_file(root: Path) -> Path:
    found = git_run(
        root, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude"
    )
    return Path(found.stdout.strip())


def hide(root: Path, name: str) -> None:
    """Keep the loose launcher out of status once the install commit holds the source file."""
    from gate_config import SOURCE_FILE

    exclude = exclude_file(root)
    text = exclude.read_text() if exclude.is_file() else ""
    line = "/" + name
    if line in text.splitlines() or committed_bytes(root, SOURCE_FILE) is None:
        return
    exclude.parent.mkdir(parents=True, exist_ok=True)
    separator = "" if not text or text.endswith("\n") else "\n"
    with exclude.open("a") as handle:
        handle.write(f"{separator}{MARKER}\n{line}\n")


def unhide(root: Path, name: str) -> None:
    """Remove the exclude line that hide wrote, and only that one."""
    exclude = exclude_file(root)
    if not exclude.is_file():
        return
    lines = exclude.read_text().splitlines(keepends=True)
    for index in range(1, len(lines)):
        if (
            lines[index].rstrip("\r\n") == "/" + name
            and lines[index - 1].rstrip("\r\n") == MARKER
        ):
            del lines[index - 1 : index + 1]
            exclude.write_text("".join(lines))
            return


def give_back(root: Path, target: Path, name: str) -> None:
    """Restore the tracked hook that a rerun replaced, when its kept copy still equals the committed hook."""
    import hook_chain

    copy = hook_chain.project_copy(target)
    committed = committed_bytes(root, name)
    mode = git_run(root, "ls-tree", "HEAD", "--", name).stdout.split(" ", 1)[0]
    if (
        committed is None
        or mode not in {"100644", "100755"}
        or copy.is_symlink()
        or not copy.is_file()
        or copy.read_bytes() != committed
        or git_run(
            root, "ls-files", "--error-unmatch", "--", copy.relative_to(root).as_posix()
        ).returncode
        == 0
        or not (hook_chain.is_own(root, target) or target.read_bytes() == committed)
    ):
        return
    target.unlink(missing_ok=True)
    target.write_bytes(committed)
    target.chmod(0o755 if mode == "100755" else 0o644)
    copy.unlink()


def without_launchers(
    root: Path, shared: list[dict[str, list[str]]], listed: set[str]
) -> None:
    """Take the launchers that the committed gates file does not list out of each shellcheck command."""
    import hook_chain

    for gate in list(shared):
        command = gate["command"]
        if Path(command[0]).name != "shellcheck" or "--" not in command:
            continue
        gate["command"] = [
            part
            for part in command
            if part in listed or not hook_chain.is_own(root, root / part)
        ]
        if gate["command"] != command and gate["command"][-1] == "--":
            shared.remove(gate)


def drop_launcher_entries(root: Path) -> None:
    """Undo a rerun that listed Hard Eng's launcher in the shell gate, when nothing else in the file changed."""
    import json

    gates = root / "hard-eng.gates.json"
    committed = committed_bytes(root, gates.name)
    if (
        committed is None
        or gates.is_symlink()
        or not gates.is_file()
        or gates.read_bytes() == committed
    ):
        return
    try:
        config, head = json.loads(gates.read_bytes()), json.loads(committed)
        listed = {part for gate in head["shared"] for part in gate["command"]}
        without_launchers(root, config["shared"], listed)
    except (ValueError, KeyError, TypeError, IndexError):
        return
    if config == head:
        gates.write_bytes(committed)


def settle_main(main: Path, own: bool) -> None:
    import hook_chain

    target = hook_chain.locate(main, "post-checkout")[1]
    place, name, _ = worktree_place(main, target)
    if place == "loose" and hook_chain.is_own(main, target):
        hide(main, name)
    elif (
        place == "ignored" and target.is_file() and not hook_chain.is_own(main, target)
    ):
        unhide(main, name)
    elif place == "tracked" and own:
        give_back(main, target, name)
    if own:
        drop_launcher_entries(main)


def settle_worktree_hook(root: Path) -> None:
    """Undo what an earlier setup rerun left in a hooks folder inside the main checkout."""
    common = common_dir(root)
    if common.name != ".git":
        return
    try:
        settle_main(common.parent, common.parent == root.resolve())
    except (ValueError, OSError, subprocess.SubprocessError):
        return
