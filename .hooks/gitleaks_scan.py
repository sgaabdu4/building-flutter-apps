"""Run current-files scans without ignored build output."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import IO


def scan_paths(repository: Path) -> list[Path]:
    """Return tracked files plus nonignored working-tree files."""
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    deleted = subprocess.run(
        ["git", "ls-files", "-z", "--deleted"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    paths = {Path(value) for value in result.stdout.split("\0") if value}
    paths -= {Path(value) for value in deleted.stdout.split("\0") if value}
    if any(path.is_absolute() or ".." in path.parts for path in paths):
        raise ValueError("Scan inventory contains an unsafe repository path")
    return sorted(paths)


def is_gitlink(repository: Path, relative_path: Path) -> bool:
    """Identify a tracked submodule without following an arbitrary directory."""
    result = subprocess.run(
        ["git", "ls-files", "--stage", "-z", "--", str(relative_path)],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return any(
        entry.startswith("160000 ") for entry in result.stdout.split("\0") if entry
    )


def is_tracked(path: Path) -> bool:
    """Ask the repository owning the file, which may be a submodule."""
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", path.name],
        cwd=path.parent,
        check=True,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout)


def validate_current_files_command(command: list[str]) -> None:
    """Limit snapshot wrapping to Gitleaks' native current-directory scan."""
    if (
        command[:3] != ["gitleaks", "dir", "."]
        or command.count("--report-path") != 1
        or command.index("--report-path") == len(command) - 1
    ):
        raise ValueError(
            "secrets-files requires native `gitleaks dir .` with one report path"
        )


def validate_current_files_gate(role: object, command: list[str]) -> None:
    """Apply the native scan constraint only to the current-files gate role."""
    if role == "secrets-files":
        validate_current_files_command(command)


def copy_link_target(source: Path, target: Path, ancestors: frozenset[Path]) -> None:
    """Copy a safe tracked alias without preserving an executable link."""
    if source.is_dir():
        copy_scan_tree(source, target, ancestors)
        return
    if not source.is_file():
        raise ValueError(f"Scan source is not a regular file: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def copy_scan_entry(
    root: Path, destination: Path, relative_path: Path, ancestors: frozenset[Path]
) -> None:
    """Copy one inventory entry, recursing only into known source directories."""
    entry = root / relative_path
    try:
        source = entry.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"Scan source is missing: {relative_path}") from error
    if not source.is_relative_to(root):
        raise ValueError(f"Scan source escapes the repository: {relative_path}")
    target = destination / relative_path
    if entry.is_symlink():
        if source.is_file() and not is_tracked(source):
            return
        copy_link_target(source, target, ancestors)
        return
    if source.is_dir():
        if not is_gitlink(root, relative_path):
            raise ValueError(f"Scan source is not a tracked submodule: {relative_path}")
        if not (source / ".git").exists():
            raise ValueError(
                f"Scan submodule is uninitialized: {relative_path}; run git submodule update --init --recursive"
            )
        copy_scan_tree(source, target, ancestors)
        return
    copy_link_target(source, target, ancestors)


def copy_scan_tree(
    repository: Path, destination: Path, ancestors: frozenset[Path] = frozenset()
) -> None:
    """Copy scan inputs, recursively scanning tracked submodules."""
    root = repository.resolve()
    if root in ancestors:
        raise ValueError("Scan source contains a directory symlink cycle")
    next_ancestors = ancestors | {root}
    for relative_path in scan_paths(root):
        copy_scan_entry(root, destination, relative_path, next_ancestors)


def snapshot_command(command: list[str], repository: Path) -> list[str]:
    """Keep the Gitleaks SARIF report outside the disposable scan tree."""
    try:
        report_index = command.index("--report-path") + 1
    except ValueError as error:
        raise ValueError("Gitleaks requires an explicit SARIF report path") from error
    if report_index == len(command):
        raise ValueError("Gitleaks report path is missing")
    report = Path(command[report_index])
    report = (repository / report) if not report.is_absolute() else report
    report = report.resolve()
    if not report.is_relative_to(repository):
        raise ValueError("Gitleaks report path escapes the repository")
    rewritten = list(command)
    rewritten[report_index] = str(report)
    return rewritten


def run_current_files(
    command: list[str],
    repository: Path,
    timeout: float,
    stdout: IO[str] | None,
    stderr: IO[str],
) -> subprocess.CompletedProcess[bytes]:
    """Scan current source inputs and return the native Gitleaks result."""
    rewritten = snapshot_command(command, repository.resolve())
    with tempfile.TemporaryDirectory(prefix="hard-eng-gitleaks-") as temporary:
        snapshot = Path(temporary)
        copy_scan_tree(repository, snapshot)
        return subprocess.run(
            rewritten,
            cwd=snapshot,
            check=False,
            timeout=timeout,
            stdout=stdout,
            stderr=stderr,
        )


def new_commits_command(
    command: list[str], repository: Path, base: str | None
) -> list[str]:
    """Scan only the commits a known base lacks; earlier ones were scanned on entry."""
    if base is None or "--log-opts=--all" not in command:
        return command
    resolved = subprocess.run(
        [
            "git",
            "rev-parse",
            "--verify",
            "--quiet",
            "--end-of-options",
            base + "^{commit}",
        ],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    revision = resolved.stdout.strip()
    if resolved.returncode or set(revision) == {"0"}:
        return command  # Unknown base: keep the full-history scan.
    print(f"Secret history scan covers commits since {revision[:7]}.")
    return [
        f"--log-opts={revision}..HEAD" if argument == "--log-opts=--all" else argument
        for argument in command
    ]


def run_gate_command(
    role: object,
    command: list[str],
    directory: Path,
    timeout: float,
    stdout: IO[str] | None,
    stderr: IO[str],
) -> subprocess.CompletedProcess[bytes]:
    """Run ordinary gates directly and point current-file scans at a snapshot."""
    if role == "secrets-files":
        return run_current_files(command, directory, timeout, stdout, stderr)
    environment = {**os.environ, "PNPM_CONFIG_DLX_CACHE_MAX_AGE": "0"}
    with tempfile.TemporaryDirectory(prefix="hard-eng-gate-") as temporary:
        if role == "ci-security":
            from update import github_token

            if token := github_token():
                environment["GH_TOKEN"] = token
            environment["ZIZMOR_CONFIG"] = zizmor_config(directory, Path(temporary))
        if role == "deployment":
            copy_scan_tree(directory, Path(temporary))
            command = [temporary if value == "." else value for value in command]
        result = subprocess.run(
            command,
            cwd=directory,
            check=False,
            timeout=timeout,
            env=environment,
            stdout=stdout,
            stderr=stderr,
        )
    if role == "ci-security" and result.returncode == 3:
        from gate_config import has_workflows, repository_files

        zizmor = any(
            Path(part).name.partition("@")[0] == "zizmor" for part in command[:2]
        )
        if zizmor and not has_workflows(directory, repository_files(directory)):
            stderr.write("No GitHub workflows to audit: zizmor collected no inputs.\n")
            result.returncode = 0
    return result


def zizmor_config(directory: Path, temporary: Path) -> str:
    """actionlint rejects `$/`, zizmor's only fix for self-repository, so that audit is off."""
    import yaml

    empty: dict[str, object] = {}
    config: object = empty
    for name in ("zizmor.yml", ".github/zizmor.yml"):
        if (directory / name).is_file():
            config = yaml.safe_load((directory / name).read_text()) or empty
            break
    rules = config.setdefault("rules", {}) if isinstance(config, dict) else None
    if not isinstance(rules, dict):
        raise TypeError("zizmor configuration must map rules to settings")
    rules["self-repository"] = {"disable": True}
    path = temporary / "zizmor.yml"
    path.write_text(yaml.safe_dump(config))
    return str(path)
