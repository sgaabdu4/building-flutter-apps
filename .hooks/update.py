"""Install a CI-verified upstream revision with an isolated local Git commit."""

import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from operator import itemgetter
from pathlib import Path

from mcp_setup import retired_settings
from update_runner import (
    commit_update,
    current_head,
    known_failure,
    link_state,
    rebase_sessions,
    relink_verified,
    remember_failure,
    roll_back,
    snapshot,
    stale_error,
    update_attempt,
    update_blocker,
    write_verified,
)

UPSTREAM = "sgaabdu4/hard-eng"
REPOSITORY = f"https://github.com/{UPSTREAM}.git"
SOURCE_FILE = ".hooks/hard-eng-source.json"


def github_token() -> str | None:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token and shutil.which("gh"):
        auth = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if auth.returncode == 0:
            token = auth.stdout.strip()
    return token or None


def github_response(endpoint: str, headers: dict[str, str]) -> bytes:
    auth = {"Authorization": f"Bearer {token}"} if (token := github_token()) else {}
    url = f"https://api.github.com/{endpoint}"
    request = urllib.request.Request(url, headers={**headers, **auth})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
    except http.client.HTTPException as error:
        raise OSError(f"GitHub response for {endpoint} was cut short") from error


def github_json(endpoint: str) -> object:
    return json.loads(
        github_response(endpoint, {"Accept": "application/vnd.github+json"})
    )


def upstream_moved(previous: str) -> bool:
    """One 40-byte request instead of a 100-commit page; an authenticated 304 is free."""
    headers = {"Accept": "application/vnd.github.sha", "If-None-Match": f'"{previous}"'}
    try:
        head = github_response(f"repos/{UPSTREAM}/commits/main", headers)
    except urllib.error.HTTPError as error:
        if error.code == 304:
            return False
        raise
    return head.decode().strip() != previous


def verified_revision(revision: str) -> bool:
    report = github_json(f"repos/{UPSTREAM}/commits/{revision}/check-runs?per_page=100")
    if not isinstance(report, dict):
        raise TypeError("GitHub check response must be an object")
    checks: list[dict[str, object]] = [
        check
        for check in report.get("check_runs", [])
        if isinstance(check, dict)
        and check.get("name") == "hard-eng"
        and isinstance(check.get("app"), dict)
        and check.get("app", {}).get("slug") == "github-actions"
    ]
    if not checks:
        return False
    latest = max(checks, key=itemgetter("id"))
    return (
        latest.get("status") == "completed"
        and latest.get("conclusion") == "success"
        and latest.get("head_sha") == revision
    )


def latest_verified(previous: str) -> str | None:
    if not upstream_moved(previous):
        return None
    page = 1
    while True:
        commits = github_json(
            f"repos/{UPSTREAM}/commits?sha=main&per_page=100&page={page}"
        )
        if not isinstance(commits, list):
            raise TypeError("GitHub commits response must be a list")
        if not commits:
            return None
        for commit in commits:
            if not isinstance(commit, dict):
                raise TypeError("GitHub commit must be an object")
            revision = commit["sha"]
            if revision == previous:
                return None
            if not isinstance(revision, str) or not re.fullmatch(
                r"[0-9a-f]{40}", revision
            ):
                raise ValueError("GitHub returned an invalid commit")
            if verified_revision(revision):
                return revision
        page += 1


def require_current(root: Path) -> None:
    """Check installed-scaffold freshness without changing verified work."""
    marker = root / SOURCE_FILE
    if not marker.exists():
        return
    try:
        metadata = json.loads(marker.read_text())
        previous = metadata.get("revision") if isinstance(metadata, dict) else None
        if not isinstance(previous, str) or not re.fullmatch(r"[0-9a-f]{40}", previous):
            raise ValueError("installed revision is not a published commit")
        revision = latest_verified(previous)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        raise ValueError(
            f"Hard Eng freshness could not be verified: {error}"
        ) from error
    if revision is not None:
        raise stale_error(root, revision)


def fetch_sources(temporary: Path, revision: str, previous: str) -> tuple[Path, Path]:
    source, old = temporary / "source", temporary / "previous"
    subprocess.run(
        [
            "git",
            "clone",
            "--quiet",
            "--filter=blob:none",
            REPOSITORY,
            str(source),
        ],
        check=True,
        timeout=120,
    )
    subprocess.run(
        ["git", "checkout", "--quiet", "--detach", revision],
        cwd=source,
        check=True,
        timeout=60,
    )
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", previous, revision],
        cwd=source,
        check=True,
        timeout=30,
    )
    subprocess.run(
        ["git", "worktree", "add", "--quiet", "--detach", str(old), previous],
        cwd=source,
        check=True,
        timeout=60,
    )
    for tree in (source, old):
        if (tree / ".gitmodules").is_file():
            subprocess.run(
                ["git", "submodule", "update", "--init", "--recursive", "--depth=1"],
                cwd=tree,
                check=True,
                timeout=120,
            )
    return source, old


def scaffold_files(source: Path) -> set[str]:
    from gate_config import repository_files

    skills = list((source / ".agents/skills").iterdir())
    if any(skill.is_symlink() and not skill.is_dir() for skill in skills):
        raise ValueError(
            "Unresolved skill link; run git submodule update --init --recursive"
        )
    return (
        {
            str(path.relative_to(source))
            for pattern in ("*.py", "ruff.toml", "dart_declarations.pubspec.*")
            for path in (source / ".hooks").glob(pattern)
        }
        | {
            str(path.relative_to(source))
            for skill in [
                source / ".agents/skills",
                *(skill for skill in skills if skill.is_symlink()),
            ]
            for path in repository_files(skill)
        }
        | {str(path.relative_to(source)) for path in source.glob(".agents/biome.json")}
    )


def without_skills(files: set[str], skills: set[str]) -> set[str]:
    return {
        name
        for name in files
        if not any(name.startswith(f".agents/skills/{skill}/") for skill in skills)
    }


def install_paths(names: list[str]) -> str:
    """Name installed paths by scaffold directory rather than every file."""
    paths = set()
    for name in names:
        parts = Path(name).parts
        if parts[0] == ".hooks":
            paths.add(".hooks/")
        elif parts[:2] == (".agents", "skills") and len(parts) > 3:
            paths.add("/".join(parts[:3]) + "/")
        else:
            paths.add(name)
    return " ".join(sorted(paths))


def pre_push_missing(root: Path) -> bool:
    from agent_hooks import project_pre_push

    hook = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--git-path", "hooks/pre-push"],
            cwd=root,
            text=True,
        ).strip()
    )
    hook = hook if hook.is_absolute() else root / hook
    target = project_pre_push(root, hook)
    return not target.exists() and not target.is_symlink()


def planned_hook(root: Path, plan: object) -> tuple[str, str]:
    if not isinstance(plan, dict):
        raise TypeError("Setup plan must be an object")
    hook = plan.get("hook")
    if not isinstance(hook, dict):
        raise TypeError("Setup plan is missing the pre-push hook")
    hook_path, hook_content = hook.get("path"), hook.get("content")
    if not isinstance(hook_path, str) or not isinstance(hook_content, str):
        raise TypeError("Setup plan has an invalid pre-push hook")
    if hook_path == ".husky/pre-push":
        if (root / hook_path).is_symlink():
            raise ValueError("Preserve the existing hook symlink before updating")
        files = plan.get("files")
        if not isinstance(files, dict):
            raise TypeError("Setup plan must include file changes")
        files[hook_path] = hook_content
    return hook_path, hook_content


def update_plan(
    root: Path, source: Path, previous: Path
) -> tuple[dict[str, str | None], dict[str, str | None], tuple[str, str], list[str]]:
    output = subprocess.check_output(
        [
            "uv",
            "run",
            "--project",
            str(source),
            "--locked",
            "--no-dev",
            "--python",
            sys.executable,
            "python",
            str(source / "setup.py"),
            str(root),
            "--plan",
            "--previous-source",
            str(previous),
        ],
        cwd=root,
        text=True,
        timeout=60,
    )
    plan = json.loads(output)
    hook = planned_hook(root, plan)
    changes: dict[str, str | None] = {
        name: content
        for name, content in plan["files"].items()
        if not (root / name).is_file()
        or (root / name).read_text() != content
        or retired_parent(root, name)
    }
    skills = {path.name for path in (source / ".agents/skills").iterdir()}
    unused = skills - {Path(name).name for name in plan["links"]}
    for name in scaffold_files(previous) - without_skills(
        scaffold_files(source), unused
    ):
        target = root / name
        if target.exists():
            if (
                target.is_symlink()
                or target.read_bytes() != (previous / name).read_bytes()
            ):
                raise ValueError(
                    f"Local scaffold edit in {name}; preserve it and ask before updating"
                )
            changes[name] = None
    links: dict[str, str | None] = {
        name: target
        for name, target in plan["links"].items()
        if not (root / name).is_symlink() or retired_link(root, root / name)
    }
    for name in plan["files"]:
        parent = retired_parent(root, name)
        if parent is not None:
            links[parent.relative_to(root).as_posix()] = None
    removed_skills = {path.name for path in (previous / ".agents/skills").iterdir()} - (
        skills - unused
    )
    for skill in removed_skills:
        name = ".claude/skills/" + skill
        link = root / name
        if link.is_symlink() and link.resolve() == root / ".agents/skills" / skill:
            links[name] = None
        elif link.exists() or link.is_symlink():
            raise ValueError(f"Local skill link differs: {name}")
    retired = [name for name, content in plan["files"].items() if content is None]
    return changes, links, hook, retired


OLD_GENERATION = (
    ".hard-eng/bootstrap.sh",
    ".hard-eng/hook.sh",
    "AGENTS.override.md",
    ".github/instructions/hard-eng.instructions.md",
)


def old_generation_files(root: Path) -> list[str]:
    return [
        name
        for name in OLD_GENERATION
        if (root / name).is_file()
        and (root / name).resolve() == root.resolve() / name
        and "Generated by Hard Eng"
        in (root / name).read_text(errors="replace").split("<!-- hard-eng:end -->")[-1]
    ]


def old_generation(root: Path, changes: dict[str, str]) -> list[str]:
    """Name tracked old-generation files and an import-only CLAUDE.md for removal."""
    from agent_hooks import CLAUDE_IMPORT

    found = old_generation_files(root)
    tracked = (
        found
        and subprocess.check_output(
            ["git", "ls-files", "--", *found], cwd=root, text=True
        ).splitlines()
    )
    retired = [name for name in found if name in tracked]
    claude = root / "CLAUDE.md"
    if (
        "CLAUDE.md" not in changes
        and not claude.is_symlink()
        and claude.is_file()
        and claude.read_text() == CLAUDE_IMPORT
    ):
        retired.append("CLAUDE.md")
    for name in {*found, *retired}:
        changes.pop(name, None)
    return retired


LEGACY_FOLDERS = (
    ".agents/skills",
    ".claude/skills",
    ".claude/agents",
    ".claude/output-styles",
    ".codex/agents",
    ".github/agents",
)


def legacy_link(path: Path) -> bool:
    return (
        path.is_symlink()
        and ".agents/hard-eng/" in os.path.normpath(path.parent / path.readlink()) + "/"
    )


def retired_link(root: Path, path: Path) -> bool:
    """An old per-checkout link directly inside a skills or agents folder of this checkout."""
    return (
        path.parent.relative_to(root).as_posix() in LEGACY_FOLDERS
        and contained(root, path)
        and legacy_link(path)
    )


def retired_parent(root: Path, name: str) -> Path | None:
    return next(
        (
            parent
            for parent in (root / name).parents
            if parent != root
            and parent.is_relative_to(root)
            and retired_link(root, parent)
        ),
        None,
    )


def contained(root: Path, path: Path) -> bool:
    """Refuse paths reached through a linked directory, which may hold shared files."""
    return not any(
        parent.is_symlink()
        for parent in path.parents
        if parent.is_relative_to(root) and parent != root
    )


def retire_local_generation(root: Path) -> None:
    settings = root / ".claude/settings.local.json"
    kept_settings = local_settings(root)
    write_changes(root, dict.fromkeys(old_generation_files(root)))
    for folder in LEGACY_FOLDERS:
        for link in (root / folder).glob("*"):
            if retired_link(root, link):
                link.unlink()
    for name in (".agents/hard-eng", ".context-mode", ".codebase-memory"):
        cache = root / name
        if contained(root, cache):
            if cache.is_symlink():
                cache.unlink()
            elif cache.is_dir():
                shutil.rmtree(cache)
    retire_local_import(root / "CLAUDE.local.md")
    if kept_settings is not None:
        settings.write_text(kept_settings)
    if block := exclude_block(root):
        block[0].write_text(block[1])


def local_settings(root: Path) -> str | None:
    settings = root / ".claude/settings.local.json"
    for local in (settings, root / "CLAUDE.local.md"):
        if (
            (local.is_symlink() or not contained(root, local))
            and local.is_file()
            and any(
                name in local.read_text(errors="replace")
                for name in (".agents/hard-eng/", "context-mode", "codebase-memory")
            )
        ):
            raise ValueError(
                f"{local.relative_to(root)} is linked and still loads retired integrations or the old Hard Eng "
                "copy; remove those entries from its target, then rerun setup"
            )
    return retired_settings(settings)


def local_generation(root: Path) -> bool:
    return (
        any(
            contained(root, root / name)
            and ((root / name).is_symlink() or (root / name).is_dir())
            for name in (".agents/hard-eng", ".context-mode", ".codebase-memory")
        )
        or any(
            retired_link(root, link)
            for folder in LEGACY_FOLDERS
            for link in (root / folder).glob("*")
        )
        or retired_settings(root / ".claude/settings.local.json") is not None
        or bool(old_generation_files(root))
        or LOCAL_IMPORT in read_lines(root / "CLAUDE.local.md")
        or exclude_block(root) is not None
    )


def read_lines(path: Path) -> list[str]:
    if not path.is_file() or path.is_symlink():
        return []
    return [line.strip() for line in path.read_text().splitlines()]


LOCAL_IMPORT = "@.agents/hard-eng/current/AGENTS.md"


def retire_local_import(local: Path) -> None:
    if not local.is_file() or local.is_symlink():
        return
    lines = local.read_text().splitlines(keepends=True)
    kept = [line for line in lines if line.strip() != LOCAL_IMPORT]
    if not "".join(kept).strip():
        local.unlink()
    elif kept != lines:
        local.write_text("".join(kept))


def exclude_block(root: Path) -> tuple[Path, str] | None:
    """The shared exclude file without the old markers; worktrees may still need its patterns."""
    command = ["git", "rev-parse", "--path-format=absolute", "--git-path"]
    path = subprocess.check_output([*command, "info/exclude"], cwd=root, text=True)
    exclude = Path(path.strip())
    text = exclude.read_text() if exclude.is_file() else ""
    start, end = (
        "# >>> hard-eng repository fallback >>>",
        "# <<< hard-eng repository fallback <<<",
    )
    if start not in text or end not in text:
        return None
    lines = text.splitlines(keepends=True)
    return exclude, "".join(line for line in lines if line.strip() not in {start, end})


def local_state(root: Path, names: list[str]) -> list[str]:
    return subprocess.check_output(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--ignored",
            "--",
            *names,
        ],
        cwd=root,
        text=True,
    ).splitlines()


def write_changes(root: Path, changes: dict[str, str | None]) -> None:
    for name, content in changes.items():
        target = root / name
        if content is None:
            target.unlink(missing_ok=True)
            for parent in target.parents:
                if parent == root or not parent.is_dir() or any(parent.iterdir()):
                    break
                parent.rmdir()
        else:
            replace_file(target, content.encode())


def replace_file(
    target: Path, content: bytes, ready: Callable[[], bool] = lambda: True
) -> bool:
    """Swap in the whole file if `ready` holds just before, so a write is never partial."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        if not ready():
            return False
        target.write_bytes(content)
        return True
    pending = target.with_name(target.name + ".hard-eng-pending")
    try:
        pending.write_bytes(content)
        if target.exists():
            shutil.copymode(target, pending)
        if not ready():
            return False
        pending.replace(target)
    finally:
        pending.unlink(missing_ok=True)
    return True


def write_links(root: Path, links: dict[str, str | None]) -> None:
    for name, target in links.items():
        link = root / name
        if target is None:
            link.unlink(missing_ok=True)
        else:
            link.parent.mkdir(parents=True, exist_ok=True)
            link.unlink(missing_ok=True)
            link.symlink_to(target, target_is_directory=True)


def install_planned_hook(root: Path, hook: tuple[str, str]) -> bool:
    name, content = hook
    target = root / name
    if (
        target.is_file()
        and not target.is_symlink()
        and target.read_text() == content
        and target.stat().st_mode & 0o111
    ):
        return False
    if target.is_symlink():
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    target.chmod(0o755)
    return True


GATE_CHECK = """import sys
sys.path.insert(0, sys.argv[1])
from gate_config import parse_config
from gitleaks_scan import validate_current_files_gate
config = parse_config(sys.stdin.read())
gates = config['shared'] + [gate for group in config['packages'] for gate in group['checks']]
for gate in gates:
    validate_current_files_gate(gate.get('role'), gate['command'])
"""


def validate_gates(root: Path, source: Path, changes: dict[str, str | None]) -> None:
    """Upstream CI proved the hooks; pre-push and CI run the project's gates on the commit."""
    name = "hard-eng.gates.json"
    result = subprocess.run(
        [sys.executable, "-I", "-c", GATE_CHECK, str(source / ".hooks")],
        input=changes.get(name) or (root / name).read_text(),
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode:
        sys.stderr.write(result.stderr)
        reason = (result.stderr.strip().splitlines() or [f"exit {result.returncode}"])[
            -1
        ]
        raise ValueError(f"the updated hooks reject {name}: {reason}")


def repair_current_hook(root: Path, previous: str) -> str:
    if not pre_push_missing(root):
        return "No newer CI-verified Hard Eng revision is available."
    with tempfile.TemporaryDirectory(prefix="hard-eng-update-") as temporary:
        source, old = fetch_sources(Path(temporary), previous, previous)
        _, _, hook, _ = update_plan(root, source, old)
        install_planned_hook(root, hook)
    return "No newer CI-verified Hard Eng revision is available; installed the missing pre-push hook."


def repair_installation(root: Path, previous: str) -> str:
    """Restore missing installed files and retire old-generation ones at the installed revision."""
    with tempfile.TemporaryDirectory(prefix="hard-eng-update-") as temporary:
        source, old = fetch_sources(Path(temporary), previous, previous)
        changes, links, hook, retired = update_plan(root, source, old)
    from agent_hooks import OLD_GENERATION_SCRIPT

    missing: dict[str, str | None] = {
        name: content
        for name, content in changes.items()
        if content is not None
        and (
            not (root / name).exists()
            or retired_parent(root, name)
            or name in {"AGENTS.md", "CLAUDE.md", "AGENTS.override.md"}
            or any(old in (root / name).read_text(errors="replace") for old in retired)
            or OLD_GENERATION_SCRIPT.search((root / name).read_text(errors="replace"))
        )
    }
    missing.update(dict.fromkeys(retired))
    added: dict[str, str | None] = {
        name: link for name, link in links.items() if link is not None
    }
    status = "No newer CI-verified Hard Eng revision is available"
    if install_planned_hook(root, hook):
        status += "; installed the missing pre-push hook"
    names = sorted({*missing, *added})
    clean = bool(names) and not local_state(root, names)
    moved = {name for name in missing if retired_parent(root, name)}
    retire_local_generation(root)
    if not names:
        return status + "."
    # Files beneath a retired link must still be absent when the repair writes them.
    before = {
        name: None if name in moved else content
        for name, content in snapshot(root, missing).items()
    }
    before_links = link_state(root, added)
    applied: list[str] = []
    try:
        write_verified(root, missing, before, (), applied)
        relink_verified(root, added, before_links, applied)
    except (OSError, ValueError) as error:
        if kept := roll_back(root, missing, added, before, before_links, applied):
            raise ValueError(
                f"{error}; kept later edits to {', '.join(kept)} instead of rolling them back"
            ) from error
        raise
    return f"{status}; repaired {install_paths(names)}. " + commit_install(
        root, names, clean, {**missing, **added}
    )


def commit_install(
    root: Path,
    names: list[str],
    clean: bool,
    expected: dict[str, str | None] | None = None,
) -> str:
    reason = "these paths already had local changes"
    if clean:
        subprocess.run(["git", "add", "--force", "--", *names], cwd=root, check=True)
        if not subprocess.run(
            ["git", "diff", "--cached", "--quiet", "--", *names], cwd=root, check=False
        ).returncode:
            return "Installed files already match the current commit."
        head = current_head(root)
        result = subprocess.run(
            ["git", "commit", "--only", "-m", "Install Hard Eng", "--", *names],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            rebase_sessions(root, head, "Install Hard Eng", expected)
            return "Committed the installed files locally without pushing."
        subprocess.run(["git", "reset", "--quiet", "--", *names], cwd=root, check=False)
        reason = " | ".join(result.stdout.strip().splitlines()[-3:])
    return (
        f"Installed files are not committed ({reason}). Commit them so updates and "
        "worktrees include them: " + install_paths(names)
    )


def refuse_local_state(root: Path, names: list[str]) -> None:
    status = local_state(root, names)
    if status and all(line.startswith("?? ") for line in status):
        raise ValueError(
            "Installed Hard Eng files are not committed: "
            + install_paths([line[3:].strip('"') for line in status])
            + "; commit them, then rerun the update"
        )
    if status:
        raise ValueError(
            "The update overlaps local edits; preserve them and ask before updating"
        )


def update(root: Path, repair: bool = False, *, remember: bool = False) -> str:
    """The background run remembers a refusal; setup always retries."""
    if (blocker := update_blocker(root)) is not None:
        return blocker
    previous = json.loads((root / SOURCE_FILE).read_text())["revision"]
    revision = latest_verified(previous)
    if revision is None:
        if repair or local_generation(root):
            return repair_installation(root, previous)
        return repair_current_hook(root, previous)
    attempt = update_attempt(root, revision) if remember else None
    if attempt is not None and (known := known_failure(root, attempt)):
        return known
    with tempfile.TemporaryDirectory(prefix="hard-eng-update-") as temporary:
        source, old = fetch_sources(Path(temporary), revision, previous)
        try:
            return install_revision(root, source, old, revision)
        except (ValueError, TypeError, subprocess.CalledProcessError) as error:
            if attempt is not None:
                remember_failure(root, attempt, error)
            raise


def install_revision(root: Path, source: Path, old: Path, revision: str) -> str:
    changes, links, hook, _ = update_plan(root, source, old)
    if not changes and not links:
        install_planned_hook(root, hook)
        return "Hard Eng already matches the verified source."
    names = sorted({*changes, *links})
    refuse_local_state(root, names)
    local_settings(root)
    before = snapshot(root, changes)
    validate_gates(root, source, changes)
    if snapshot(root, changes) != before:
        raise ValueError(
            "Files changed during verification; the update was not applied"
        )
    if subprocess.check_output(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--ignored",
            "--",
            *names,
        ],
        cwd=root,
        text=True,
    ):
        raise ValueError(
            "The update paths changed during verification; nothing was applied"
        )
    commit_update(root, changes, links, revision, before)
    retire_local_generation(root)
    if hook[0] not in changes:
        install_planned_hook(root, hook)
    return f"Updated Hard Eng to {revision}; created an isolated local commit without pushing."


INSTALLED_FILES = {
    SOURCE_FILE,
    "AGENTS.md",
    "CLAUDE.md",
    "AGENTS.override.md",
    ".husky/pre-push",
}


def maybe_installed(name: str) -> bool:
    """A path a Hard Eng update can write, checked before any network proof."""
    return name in INSTALLED_FILES | {".agents/biome.json"} or name.startswith(
        (".hooks/", ".agents/skills/", ".claude/skills/")
    )


def update_in_diff(root: Path, base: str) -> tuple[str, str, set[str]] | None:
    """The installed and previous revisions and changed paths of a committed update."""
    marker = root / SOURCE_FILE
    if not marker.is_file():
        return None
    # Only a clean, committed installation update may narrow the application checks.
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True):
        return None
    try:
        revision = json.loads(marker.read_text()).get("revision")
        previous = json.loads(
            subprocess.check_output(
                ["git", "show", f"{base}:{SOURCE_FILE}"],
                cwd=root,
                text=True,
                stderr=subprocess.DEVNULL,
            )
        ).get("revision")
        names = set(
            subprocess.check_output(
                ["git", "diff", "--name-only", "--no-renames", "-z", base, "--"],
                cwd=root,
                text=True,
            ).split("\0")
        ) - {""}
    except (subprocess.CalledProcessError, ValueError, AttributeError):
        return None
    if (
        SOURCE_FILE not in names
        or not isinstance(previous, str)
        or not isinstance(revision, str)
        or revision == previous
        or not re.fullmatch(r"[0-9a-f]{40}", previous)
        or not re.fullmatch(r"[0-9a-f]{40}", revision)
    ):
        return None
    return revision, previous, names


def release_installed(
    root: Path, base: str, names: set[str], revision: str, previous: str
) -> bool:
    """Whether these paths hold exactly what the verified release installs."""
    with tempfile.TemporaryDirectory(prefix="hard-eng-scaffold-check-") as temporary:
        source, old = fetch_sources(Path(temporary), revision, previous)
        allowed = scaffold_files(source) | scaffold_files(old) | INSTALLED_FILES
        allowed |= {
            ".claude/skills/" + path.name
            for tree in (source, old)
            for path in (tree / ".agents/skills").iterdir()
            if path.is_dir()
        }
        changes, links, _, _ = update_plan(root, source, source)
        if (
            not names <= allowed
            or changes
            or links
            or any(
                (root / name).exists()
                for name in scaffold_files(old) - scaffold_files(source)
            )
            or not preserved_instructions(root, base, names)
        ):
            return False
        validate_gates(root, source, {})
    return True


def check_scaffold_update(root: Path, base: str) -> bool:
    found = update_in_diff(root, base)
    if found is None or not all(maybe_installed(name) for name in found[2]):
        return False
    revision, previous, names = found
    if not verified_revision(revision):
        raise ValueError(
            "Scaffold update does not identify a successful upstream hard-eng check"
        )
    if not release_installed(root, base, names, revision, previous):
        return False
    print(
        "Scaffold-only update: source CI verified and the gate configuration accepted.",
        flush=True,
    )
    return True


def installed_update_paths(root: Path, base: str) -> set[str]:
    """Changed paths a verified update installed exactly; they add no package scope."""
    found = update_in_diff(root, base)
    if found is None:
        return set()
    revision, previous, names = found
    installed = {name for name in names if maybe_installed(name)}
    try:
        proven = verified_revision(revision) and release_installed(
            root, base, installed, revision, previous
        )
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return set()
    return installed if proven else set()


def preserved_instructions(root: Path, base: str, names: set[str]) -> bool:
    from agent_hooks import instruction_suffix

    for name in names & {"AGENTS.md", "CLAUDE.md", "AGENTS.override.md"}:
        blob = f"{base}:{name}"
        original = subprocess.run(
            ["git", "show", blob],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        ).stdout
        if not (root / name).is_file() or instruction_suffix(
            original
        ) != instruction_suffix((root / name).read_text()):
            return False
    return True
