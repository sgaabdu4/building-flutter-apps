"""Run current-files scans without ignored build output."""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import IO

from gate_config import Group
from process_group import run_in_group
from project_files import GIT_LISTING

TOOL_VARIABLES = re.compile(
    r"GITLEAKS_CONFIG(?:_TOML)?|FALLOW_\w+|CARGO_ALIAS_\w+|CLIPPY_CONF_DIR|SHELLCHECK_OPTS"
    r"|CARGO_HOME|RUFF_(?!CACHE_DIR\b|NO_CACHE\b)\w+"
)
CONFIG_ASSIGNMENT = re.compile(rf"\b(?:{TOOL_VARIABLES.pattern})[\"']?\s*[:=]")


def scan_environment(base: dict[str, str] | None = None) -> dict[str, str]:
    """The environment of a gate run, without the variables that change what a judged tool reports: the Gitleaks config, every `FALLOW_` variable (a newer release may read more), a Cargo alias, the Clippy config folder, `SHELLCHECK_OPTS`, `CARGO_HOME` (Cargo reads an alias from its config file), `XDG_CONFIG_HOME` (ShellCheck reads a `shellcheckrc` there) and the Ruff variables other than its two cache ones."""
    return {
        key: value
        for key, value in (os.environ if base is None else base).items()
        if not TOOL_VARIABLES.fullmatch(key) and key != "XDG_CONFIG_HOME"
    }


def config_variable_hits(name: str, text: str) -> list[str]:
    return [
        f"{name}:{number} sets {match[0].rstrip(':= "\'')}, which swaps a scanner config or changes what Fallow reports"
        for number, line in enumerate(text.splitlines(), 1)
        if not line.lstrip().startswith("#")
        and (match := CONFIG_ASSIGNMENT.search(line))
    ]


def validate_config_variables(command: list[str]) -> None:
    found = [
        piece
        for word in command
        for piece in word.split()
        if CONFIG_ASSIGNMENT.match(piece)
    ]
    if found:
        raise ValueError(
            "HE-NO-SWITCH-OFF: A gate must not set the variables that swap the Gitleaks config or change what Fallow reports: "
            + ", ".join(found)
        )


def scan_paths(repository: Path) -> list[Path]:
    """Return tracked files plus nonignored working-tree files that still exist."""
    result = subprocess.run(
        [*GIT_LISTING, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    paths = {
        Path(value)
        for value in result.stdout.split("\0")
        if value and os.path.lexists(repository / value)
    }
    if any(path.is_absolute() or ".." in path.parts for path in paths):
        raise ValueError("Scan inventory contains an unsafe repository path")
    return sorted(paths)


def git_owner(folder: Path) -> Path | None:
    """Return the nearest folder at or above this one that holds a .git entry."""
    return next(
        (parent for parent in (folder, *folder.parents) if (parent / ".git").exists()),
        None,
    )


class ScanCache:
    """One Git listing per repository, shared by every link that reaches it."""

    def __init__(self) -> None:
        self.listings: dict[Path, list[Path]] = {}
        self.tracked: dict[Path, set[str]] = {}

    def paths(self, root: Path) -> list[Path]:
        if root not in self.listings:
            owner = git_owner(root)
            if owner is None or owner == root or owner not in self.listings:
                self.listings[root] = scan_paths(root)
            else:
                prefix = root.relative_to(owner).parts
                self.listings[root] = [
                    Path(*path.parts[len(prefix) :])
                    for path in self.listings[owner]
                    if path.parts[: len(prefix)] == prefix
                    and len(path.parts) > len(prefix)
                ]
        return self.listings[root]

    def is_tracked(self, path: Path) -> bool:
        """Ask the repository owning the file, which may be a submodule."""
        if path.parent not in self.tracked:
            result = subprocess.run(
                ["git", "ls-files", "-z"],
                cwd=path.parent,
                check=True,
                capture_output=True,
                text=True,
            )
            self.tracked[path.parent] = set(result.stdout.split("\0"))
        return path.name in self.tracked[path.parent]


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


NARROWING_FLAGS = {
    "-b",
    "--baseline-path",
    "-i",
    "--gitleaks-ignore-path",
    "--enable-rule",
    "--max-target-megabytes",
    "--max-decode-depth",
    "--exit-code",
    "--pre-commit",
    "--staged",
}
SCAN_REFUSAL = (
    "HE-NO-SWITCH-OFF: A secret scan must not narrow, baseline or mute itself: "
    "fix the finding at its cause instead; "
)


def narrowing_flags(command: list[str]) -> list[str]:
    """Flags that hide findings, and a config path other than `.gitleaks.toml`."""
    found = []
    for index, argument in enumerate(command):
        if not argument.startswith("-") or argument == "-":
            continue
        name, equals, value = argument.partition("=")
        if not argument.startswith("--") and len(argument) > 2:
            name, value = argument[:2], argument[2:]
        elif not equals and index + 1 < len(command):
            value = command[index + 1]
        if name in NARROWING_FLAGS or (
            name in {"-c", "--config"} and os.path.normpath(value) != ".gitleaks.toml"
        ):
            found.append(argument)
    return found


def validate_history_command(command: list[str]) -> None:
    """Keep the history gate on every commit, never a range."""
    if (
        command[:3] != ["gitleaks", "git", "."]
        or command.count("--log-opts=--all") != 1
        or any(a.startswith("--log-opts") and a != "--log-opts=--all" for a in command)
    ):
        raise ValueError(
            "secrets-history requires native `gitleaks git .` over `--log-opts=--all`"
        )


def validate_current_files_gate(role: object, command: list[str]) -> None:
    """Apply the native scan constraints to the two secret gate roles."""
    if role not in {"secrets-files", "secrets-history"}:
        return
    if found := narrowing_flags(command):
        raise ValueError(
            f"{SCAN_REFUSAL}the {role} gate holds {', '.join(found)}; keep the config `.gitleaks.toml`"
        )
    if role == "secrets-files":
        validate_current_files_command(command)
    else:
        validate_history_command(command)


def copy_link_target(
    source: Path, target: Path, ancestors: frozenset[Path], cache: ScanCache
) -> None:
    """Copy a safe tracked alias without preserving an executable link."""
    if source.is_dir():
        copy_scan_tree(source, target, ancestors, cache)
        return
    if not source.is_file():
        raise ValueError(f"Scan source is not a regular file: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def copy_scan_entry(
    root: Path,
    destination: Path,
    relative_path: Path,
    ancestors: frozenset[Path],
    cache: ScanCache,
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
        if source.is_file() and not cache.is_tracked(source):
            return
        copy_link_target(source, target, ancestors, cache)
        return
    if source.is_dir():
        if not is_gitlink(root, relative_path):
            raise ValueError(f"Scan source is not a tracked submodule: {relative_path}")
        if not (source / ".git").exists():
            raise ValueError(
                f"Scan submodule is uninitialized: {relative_path}; run git submodule update --init --recursive"
            )
        copy_scan_tree(source, target, ancestors, cache)
        return
    copy_link_target(source, target, ancestors, cache)


def copy_scan_tree(
    repository: Path,
    destination: Path,
    ancestors: frozenset[Path] = frozenset(),
    cache: ScanCache | None = None,
) -> None:
    """Copy scan inputs, recursively scanning tracked submodules."""
    cache = cache or ScanCache()
    root = repository.resolve()
    if root in ancestors:
        raise ValueError("Scan source contains a directory symlink cycle")
    next_ancestors = ancestors | {root}
    for relative_path in cache.paths(root):
        copy_scan_entry(root, destination, relative_path, next_ancestors, cache)


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
            env=scan_environment(),
            check=False,
            timeout=timeout,
            stdout=stdout,
            stderr=stderr,
        )


def new_commits_command(
    command: list[str], repository: Path, base: str | None
) -> list[str]:
    """Scan only the commits a known base lacks; earlier ones were scanned on entry."""
    if "--log-opts=--all" not in command:
        return command
    pushable = [
        "--log-opts=--remotes --tags HEAD"
        if argument == "--log-opts=--all"
        else argument
        for argument in command
    ]
    if base is None:
        return pushable
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
        return pushable  # Unknown base: scan every commit a push can carry.
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
    environment = {**scan_environment(), "PNPM_CONFIG_DLX_CACHE_MAX_AGE": "0"}
    if role == "freshness":
        environment["POETRY_SOLVER_MIN_RELEASE_AGE"] = "2"
    with tempfile.TemporaryDirectory(prefix="hard-eng-gate-") as temporary:
        if role == "ci-security":
            from update import github_token

            if os.environ.get("CCR_AGENT_PROXY_ENABLED"):
                # The cloud agent proxy serves anonymous GitHub git reads but rejects its token there.
                environment.pop("GH_TOKEN", None)
                environment.pop("GITHUB_TOKEN", None)
            elif token := github_token():
                environment["GH_TOKEN"] = token
            environment["ZIZMOR_CONFIG"] = zizmor_config(directory, Path(temporary))
        if role == "deployment":
            copy_scan_tree(directory, Path(temporary))
            command = [temporary if value == "." else value for value in command]
        result = subprocess.CompletedProcess(
            command,
            run_in_group(
                command,
                cwd=directory,
                timeout=timeout,
                env=environment,
                stdout=stdout,
                stderr=stderr,
            ).returncode,
        )
    if role == "ci-security" and result.returncode == 3:
        from gate_config import has_workflows, repository_files

        zizmor = any(
            Path(part).name.partition("@")[0] == "zizmor" for part in command[:5]
        )
        if zizmor and not has_workflows(directory, repository_files(directory)):
            stderr.write("No GitHub workflows to audit: zizmor collected no inputs.\n")
            result.returncode = 0
    return result


def private_repository(directory: Path) -> bool:
    """Outside forks cannot run jobs on a private repository's self-hosted runners."""
    try:
        found = subprocess.run(
            ["gh", "repo", "view", "--json", "visibility", "-q", ".visibility"],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0 and found.stdout.strip() == "PRIVATE"


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
    if "self-hosted-runner" not in rules and private_repository(directory):
        rules["self-hosted-runner"] = {"disable": True}
    path = temporary / "zizmor.yml"
    path.write_text(yaml.safe_dump(config))
    return str(path)


def commit_secret_scan(root: Path, base: str | None, timeout: float) -> int:
    """Only the secret scan of the commits since base: the part of a push that CI cannot do, as it starts after the push."""
    from ci_setup import push_base, require_ci_base
    from gate_config import load_groups
    from gate_runner import run_gates
    from tool_setup import provision_tools

    require_ci_base(base, root)
    base = push_base(root, base)
    groups: list[Group] = [
        {
            **group,
            "checks": [
                g for g in group["checks"] if g.get("role") == "secrets-history"
            ],
        }
        for group in load_groups(root, base)
    ]
    if not any(group["checks"] for group in groups):
        print("Hard Eng: the commit secret scan did not run; no secrets-history gate.")
        return 1
    provision_tools(root, groups, timeout)
    return int(run_gates(groups, timeout, None) is not False)
