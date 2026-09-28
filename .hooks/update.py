"""Install a CI-verified upstream revision with an isolated local Git commit."""

import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from operator import itemgetter
from pathlib import Path

from mcp_setup import retired_settings

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


def github_json(endpoint: str) -> object:
    auth = {"Authorization": f"Bearer {token}"} if (token := github_token()) else {}
    headers = {"Accept": "application/vnd.github+json", **auth}
    url = f"https://api.github.com/{endpoint}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except http.client.HTTPException as error:
        raise OSError(f"GitHub response for {endpoint} was cut short") from error


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
        raise ValueError(
            f"Hard Eng freshness check found newer verified revision {revision}. "
            "Use the supported updater, preserve local edits, then reverify before shipping or claiming completion."
        )


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
                ["git", "submodule", "update", "--init", "--recursive"],
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
            for pattern in ("*.py", "ruff.toml")
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
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)


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


def verify_candidate(
    root: Path,
    source: Path,
    changes: dict[str, str | None],
    links: dict[str, str | None],
    candidate: Path,
) -> None:
    # Both callers already verified upstream CI for this exact source revision.
    subprocess.run(
        ["git", "worktree", "add", "--quiet", "--detach", str(candidate), "HEAD"],
        cwd=root,
        check=True,
    )
    try:
        if (candidate / ".gitmodules").is_file():
            subprocess.run(
                ["git", "submodule", "update", "--init", "--recursive"],
                cwd=candidate,
                check=True,
            )
        write_links(candidate, links)
        write_changes(candidate, changes)
        names = sorted({*changes, *links})
        if names:
            subprocess.run(
                ["git", "add", "--force", "--", *names],
                cwd=candidate,
                check=True,
            )
        subprocess.run(
            ["git", "diff", "--cached", "--check"], cwd=candidate, check=True
        )
        only_scaffold = set(changes) <= scaffold_files(source) | scaffold_files(
            root
        ) | {
            "AGENTS.md",
            "CLAUDE.md",
            "AGENTS.override.md",
            SOURCE_FILE,
            ".husky/pre-push",
        }
        command = (
            [
                sys.executable,
                "-I",
                "-c",
                """import compileall, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from gate_config import parse_config
from gitleaks_scan import validate_current_files_gate
config = parse_config(Path('hard-eng.gates.json').read_text())
gates = config['shared'] + [gate for group in config['packages'] for gate in group['checks']]
for gate in gates:
    validate_current_files_gate(gate.get('role'), gate['command'])
raise SystemExit(not compileall.compile_dir('.hooks', quiet=1))
""",
                str(source / ".hooks"),
            ]
            if only_scaffold
            else [
                "uv",
                "run",
                "--project",
                str(source),
                "--locked",
                "--no-dev",
                "--python",
                sys.executable,
                "python",
                "-I",
                "-c",
                (
                    "import runpy, sys; "
                    "sys.path.insert(0, '.hooks'); "
                    "raise SystemExit(runpy.run_path('.hooks/hard-eng.py')['check']("
                    "base=sys.argv[1], verify_plan=False))"
                ),
            ]
        )
        if not only_scaffold:
            from ship_actions import remote_base
            from shipping import load_policy

            policy = load_policy(candidate, required=False)
            # An update candidate is verification input, not a completed task.
            if (
                "origin"
                in subprocess.check_output(
                    ["git", "remote"], cwd=candidate, text=True
                ).splitlines()
            ):
                base = remote_base(candidate, policy["base"] if policy else None)
                found = subprocess.run(
                    ["git", "merge-base", base or "HEAD", "HEAD"],
                    cwd=candidate,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                command.append(found.stdout.strip() or base or "HEAD")
            else:
                command.append("HEAD")
        subprocess.run(
            command, cwd=candidate, stdout=sys.stderr, check=True, timeout=3500
        )
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(candidate)],
            cwd=root,
            check=True,
        )


def commit_update(
    root: Path,
    changes: dict[str, str | None],
    links: dict[str, str | None],
    revision: str,
) -> None:
    names = sorted({*changes, *links})
    before = {
        name: (root / name).read_bytes() if (root / name).exists() else None
        for name in changes
    }
    before_links = {
        name: str((root / name).readlink()) if (root / name).is_symlink() else None
        for name in links
    }
    try:
        write_links(root, links)
        write_changes(root, changes)
        subprocess.run(
            ["git", "add", "--force", "--", *names],
            cwd=root,
            check=True,
        )
        message = f"Update Hard Eng to {revision}"
        result = subprocess.run(
            [
                "git",
                "commit",
                "--only",
                "-m",
                message,
                "--",
                *(
                    name
                    for name in names
                    if not any(other.startswith(f"{name}/") for other in changes)
                ),
            ],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=3500,
        )
        sys.stderr.write(result.stdout)
        if result.returncode != 0:
            # SessionStart stderr never reaches the agent, so the error carries the reason.
            tail = " | ".join(result.stdout.strip().splitlines()[-5:])
            raise subprocess.SubprocessError(
                f"git commit exited {result.returncode}: {tail}".removesuffix(": ")
            )
    except (OSError, subprocess.SubprocessError):
        for name, content in before.items():
            target = root / name
            if content is None:
                target.unlink(missing_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        for name, target in before_links.items():
            if (root / name).is_dir() and not (root / name).is_symlink():
                shutil.rmtree(root / name)
            else:
                (root / name).unlink(missing_ok=True)
            if target is not None:
                (root / name).symlink_to(target, target_is_directory=True)
        subprocess.run(
            ["git", "reset", "--quiet", "HEAD", "--", *names], cwd=root, check=True
        )
        raise


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
    retire_local_generation(root)
    if not names:
        return status + "."
    write_changes(root, missing)
    write_links(root, added)
    return f"{status}; repaired {install_paths(names)}. " + commit_install(
        root, names, clean
    )


def commit_install(root: Path, names: list[str], clean: bool) -> str:
    reason = "these paths already had local changes"
    if clean:
        subprocess.run(["git", "add", "--force", "--", *names], cwd=root, check=True)
        if not subprocess.run(
            ["git", "diff", "--cached", "--quiet", "--", *names], cwd=root, check=False
        ).returncode:
            return "Installed files already match the current commit."
        result = subprocess.run(
            ["git", "commit", "--only", "-m", "Install Hard Eng", "--", *names],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if result.returncode == 0:
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


def update(root: Path, repair: bool = False) -> str:
    marker = root / SOURCE_FILE
    if not marker.exists():
        return "Automatic update unavailable: this checkout has no installed source revision."
    metadata = json.loads(marker.read_text())
    if not isinstance(metadata, dict):
        raise TypeError("Installed source metadata must be an object")
    previous = metadata.get("revision")
    if not isinstance(previous, str) or not re.fullmatch(r"[0-9a-f]{40}", previous):
        return "Installed from an uncommitted working copy; publish a verified source revision before automatic updates."
    revision = latest_verified(previous)
    if revision is None:
        if repair or local_generation(root):
            return repair_installation(root, previous)
        return repair_current_hook(root, previous)
    with tempfile.TemporaryDirectory(prefix="hard-eng-update-") as temporary:
        source, old = fetch_sources(Path(temporary), revision, previous)
        changes, links, hook, _ = update_plan(root, source, old)
        if not changes and not links:
            install_planned_hook(root, hook)
            return "Hard Eng already matches the verified source."
        names = sorted({*changes, *links})
        refuse_local_state(root, names)
        local_settings(root)
        before = {
            name: (root / name).read_bytes() if (root / name).exists() else None
            for name in changes
        }
        verify_candidate(root, source, changes, links, Path(temporary) / "candidate")
        if any(
            ((root / name).read_bytes() if (root / name).exists() else None) != content
            for name, content in before.items()
        ):
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
        commit_update(root, changes, links, revision)
        retire_local_generation(root)
        if hook[0] not in changes:
            install_planned_hook(root, hook)
    return f"Updated Hard Eng to {revision}; created an isolated local commit without pushing."


def check_scaffold_update(root: Path, base: str) -> bool:
    marker = root / SOURCE_FILE
    if not marker.is_file():
        return False
    # Only a clean, committed installation update may skip the application checks.
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True):
        return False
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
        return False
    if (
        SOURCE_FILE not in names
        or not isinstance(previous, str)
        or not isinstance(revision, str)
        or revision == previous
        or not re.fullmatch(r"[0-9a-f]{40}", previous)
        or not re.fullmatch(r"[0-9a-f]{40}", revision)
    ):
        return False
    if any(
        name
        not in {
            SOURCE_FILE,
            "AGENTS.md",
            "CLAUDE.md",
            "AGENTS.override.md",
            ".husky/pre-push",
            ".agents/biome.json",
        }
        and not name.startswith((".hooks/", ".agents/skills/", ".claude/skills/"))
        for name in names
    ):
        return False
    if not verified_revision(revision):
        raise ValueError(
            "Scaffold update does not identify a successful upstream hard-eng check"
        )
    with tempfile.TemporaryDirectory(prefix="hard-eng-scaffold-check-") as temporary:
        source, old = fetch_sources(Path(temporary), revision, previous)
        allowed = (
            scaffold_files(source)
            | scaffold_files(old)
            | {
                SOURCE_FILE,
                "AGENTS.md",
                "CLAUDE.md",
                "AGENTS.override.md",
                ".husky/pre-push",
            }
        )
        allowed |= {
            ".claude/skills/" + path.name
            for tree in (source, old)
            for path in (tree / ".agents/skills").iterdir()
            if path.is_dir()
        }
        changes, links, _, _ = update_plan(root, source, source)
        if not names <= allowed or changes or links:
            return False
        if any(
            (root / name).exists()
            for name in scaffold_files(old) - scaffold_files(source)
        ):
            return False
        if not preserved_instructions(root, base, names):
            return False
        print(
            "Scaffold-only update: source CI verified; checking installed Python hooks.",
            flush=True,
        )
        verify_candidate(root, source, {}, {}, Path(temporary) / "candidate")
    return True


def preserved_instructions(root: Path, base: str, names: set[str]) -> bool:
    end = "<!-- hard-eng:end -->\n\n"
    for name in names & {"AGENTS.md", "CLAUDE.md", "AGENTS.override.md"}:
        blob = f"{base}:{name}"
        original = subprocess.run(
            ["git", "show", blob],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        ).stdout
        if (
            not (root / name).is_file()
            or original.split(end, 1)[-1] != (root / name).read_text().split(end, 1)[-1]
        ):
            return False
    return True
