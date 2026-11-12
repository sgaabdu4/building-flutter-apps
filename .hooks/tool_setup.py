"""Provision current native tools before concurrent gate execution."""

import fcntl
import importlib.util
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO

from fallow_report import native_scanner_command
from gate_config import Gate, GateConfig, Group, has_workflows, require_roles
from project_setup import (
    is_deployment_file,
    package_script_invocation,
    project_shell_scripts,
    require_listed_shell_scripts,
)

RELEASE_AGE_SECONDS = 2 * 24 * 60 * 60
DIGIT_RUN = re.compile(r"\d+")
TOOL_VERSION = re.compile(r"\d[\w.+-]*")
VERSION_NUMBER = re.compile(r"\d+(?:\.\d+)+")
UV_LOST_SCANNER = " was not found in the cache and you require "
TOOL_BRACKETS_OR_LATEST = re.compile(r"\[[^\]]*\]|@latest$")
MISSING_MODULE_NAME = re.compile(r"Cannot find module '([^']+)'")
NPM_LATEST_PACKAGE = re.compile(r"^(npm:[^\[]+?)(@latest)$")
# mise names each tool that no config file lists; Hard Eng runs it with no config on purpose.
ACTIVATION_NOTE = re.compile(
    r"(?m)^mise WARN .* installed but not activated .*\n"
    r"(?:To install and activate, run:\n(?: +mise use .*\n)*)?"
)

NATIVE_SCANNERS = {
    "dart-decimate": "dart-decimate",
    "react-doctor": "React Doctor",
}
PACKAGES = {
    "uv": "uv",
    "gitleaks": "aqua:gitleaks/gitleaks",
    "osv-scanner": "aqua:google/osv-scanner",
    "actionlint": "aqua:rhysd/actionlint",
    "shellcheck": "aqua:koalaman/shellcheck",
    "trivy": "aqua:aquasecurity/trivy",
    "biome": "npm:@biomejs/biome",
    "tsc": "npm:typescript",
    "fallow": "npm:fallow",
    "dart-decimate": "npm:dart-decimate",
    "react-doctor": "npm:react-doctor",
    "jscpd": "npm:jscpd",
    "lhci": "npm:@lhci/cli",
    "k6": "aqua:grafana/k6",
}
MANAGED_PYTHON_SCANNERS = {"ruff", "pyrefly", "vulture", "semgrep", "zizmor", "poetry"}
ROLE_TOOLS: dict[str, dict[str, tuple[str, ...]]] = {
    "python": {
        "format": ("ruff", "format"),
        "lint": ("ruff", "check"),
        "complexity": ("ruff", "check"),
        "annotations": ("ruff", "check"),
        "types": ("pyrefly", "check"),
        "dead-code": ("vulture",),
    },
    "javascript": {
        "format-lint": ("biome", "ci"),
        "focused-tests": ("biome", "lint"),
        "typing-style": ("biome", "lint"),
        "types": ("tsc",),
    },
    "dart": {"format": ("dart", "format"), "types": ("dart", "analyze")},
    "swift": {"format-lint": ("swift", "format", "lint")},
    "shared": {
        "workflows": ("actionlint",),
        "ci-security": ("zizmor",),
        "shell": ("shellcheck",),
    },
}
# Vulture cannot see a route or a model field that a framework calls; uvx installs this scanner, which fails on a finding only with its flag.
OTHER_ROLE_TOOLS: dict[tuple[str, str], tuple[tuple[str, ...], str]] = {
    ("python", "dead-code"): (("uvx", "skylos"), "--strict")
}
SCANNER_VERSIONS: dict[str, str] = {}
# The platform package installs without the npm-only preinstall of @jdxcode/mise.
MISE_PACKAGE = "@jdxcode/mise-{}-{}".format(
    {"darwin": "darwin", "linux": "linux"}[sys.platform],
    {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "amd64": "x64"}[
        platform.machine().lower()
    ],
)
MISE_LATEST = MISE_PACKAGE + "@latest"
MISE_BINARY = Path("node_modules", MISE_PACKAGE, "bin/mise")
CHECKOUT = Path(__file__).resolve().parents[1]
TOOL_OWNER = "HARD_ENG_TOOL_OWNER"
RESTARTED = "HARD_ENG_RESTARTED"
VISIBLE_TEMP = Path("/tmp")
HELD: list[IO[str]] = []
NOT_INSTALLED = (
    "Tools are not installed yet and cannot be fetched now: {error}. "
    "Connect once or run the full check (`python3 .hooks/hard-eng.py check`; during a build, `python3 .hooks/hard-eng.py check --plan-stage Ready`) to install them."
)


def quick_mode() -> bool:
    return "--quick" in sys.argv


def ensure_python_runtime() -> None:
    """Run the installed CLI with its YAML dependency without changing host Python."""
    if os.environ.pop(RESTARTED, None):
        # uv run set VIRTUAL_ENV to its throwaway; Poetry would sync and run gates there.
        os.environ.pop("VIRTUAL_ENV", None)
    if importlib.util.find_spec("yaml") is None:
        os.environ[RESTARTED] = "1"
        try:
            os.execvp(
                "uv",
                [
                    "uv",
                    "run",
                    "--no-project",
                    "--with",
                    "pyyaml",
                    "--python",
                    sys.executable,
                    "python",
                    *sys.argv,
                ],
            )
        except FileNotFoundError as error:
            raise FileNotFoundError(
                "uv is not on PATH; Hard Eng needs it. Install uv, then run again."
            ) from error


def require_shared_roles(
    root: Path, config: GateConfig, files: list[Path], secrets: bool
) -> set[str]:
    """Files decide the mandatory shared roles; a gate that names a role's tool fills it."""
    required = {"secrets-files"} if secrets else set()
    if secrets and config.get("scan_git_history", True):
        required.add("secrets-history")
    if has_workflows(root, files):
        required.update({"workflows", "ci-security"})
    if next(project_shell_scripts(root, files), None) is not None:
        required.add("shell")
    if any(is_deployment_file(path) for path in files):
        required.add("deployment")
    roles = {gate.get("role", "") for gate in config["shared"]}
    for gate in config["shared"]:
        command = gate["command"]
        require_role_tool("shared", gate, command)
        roles.update(
            role
            for role, tool in ROLE_TOOLS["shared"].items()
            if Path(command[0]).name == tool[0]
        )
        if Path(command[0]).name == "trivy" and "config" in command[1:]:
            roles.add("deployment")
    require_roles("shared", required, roles)
    require_listed_shell_scripts(root, files, config["shared"])
    return roles


def entry_point_names(directory: Path) -> list[str]:
    """Functions the project's console scripts call, which vulture cannot see being used."""
    try:
        project = tomllib.loads((directory / "pyproject.toml").read_text())["project"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return []
    targets = [
        target
        for table in ("scripts", "gui-scripts")
        for target in project.get(table, {}).values()
        if isinstance(target, str)
    ]
    return sorted(
        {
            target.split(":")[-1].split("[")[0].split(".")[-1].strip()
            for target in targets
        }
        - {""}
    )


def with_entry_points(command: list[str], directory: Path) -> list[str]:
    names = entry_point_names(directory)
    if command[0] != "vulture" or not names:
        return command
    return [*command, "--ignore-names", ",".join(names)]


def require_role_tool(language: str, gate: Gate, command: list[str]) -> None:
    """A required check that writes no report proves itself only by the tool it names."""
    role = str(gate.get("role"))
    tool = ROLE_TOOLS.get(language, {}).get(role)
    if tool is None or gate.get("report"):
        return
    words = [
        Path(word.strip("'\"();")).name.split("@", 1)[0]
        for word in " ".join(command).split()
    ]
    other, flag = OTHER_ROLE_TOOLS.get((language, role), (tool, ""))
    if not any(
        tuple(words[at : at + len(accepted)]) == accepted
        for accepted in (tool, *([other] if flag in words else []))
        for at in range(len(words))
    ):
        raise ValueError(
            f"{gate['name']}: the {gate['role']} check must run `{' '.join(tool)}`; "
            f"this command does not name it: {' '.join(gate['command'])}"
        )


def uvx_scanner(command: list[str]) -> list[str]:
    """A configured `uvx ruff@latest …` gate runs like `ruff …`, so it is pinned too."""
    tool = command[1] if len(command) > 1 and command[0] == "uvx" else ""
    name = tool.removesuffix("@latest")
    if tool.endswith("@latest") and name in MANAGED_PYTHON_SCANNERS:
        return [name, *command[2:]]
    return command


def release_cutoff(now: datetime | None = None) -> str:
    """Newest release time uvx may use, floored to the hour so uv's cache stays warm."""
    moment = (now or datetime.now(UTC)) - timedelta(seconds=RELEASE_AGE_SECONDS)
    return moment.replace(minute=0, second=0, microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def managed_command(
    command: list[str], directory: Path | None = None, now: datetime | None = None
) -> list[str]:
    command = uvx_scanner(command)
    if directory is not None:
        command = with_entry_points(
            managed_scanner_command(command, directory), directory
        )
    if command[0] in MANAGED_PYTHON_SCANNERS:
        offline = ["--offline"] if quick_mode() else []
        version = SCANNER_VERSIONS.get(command[0])
        tool = f"{command[0]}@{version or 'latest'}"
        wait = ["--exclude-newer", release_cutoff(now)]
        return ["uvx", *offline, *wait, tool, *command[1:]]
    return command


def managed_scanner_command(command: list[str], directory: Path) -> list[str]:
    """Keep supported scanner arguments without a stale package-local binary."""
    arguments, resolved = package_script_invocation(command, directory)
    invocation = native_scanner_command(arguments)
    if invocation is not None:
        scanner = (
            "Fallow" if invocation[0] == "fallow" else NATIVE_SCANNERS[invocation[0]]
        )
        if resolved.resolve() != directory.resolve():
            raise ValueError(
                f"Configure the {scanner} gate in its explicit package directory"
            )
        if any(value in arguments for value in ("&&", "||", ";", "|", ">", "2>")):
            if scanner == "Fallow":
                raise ValueError(
                    "Fallow audit must be one native invocation with its arguments"
                )
            raise ValueError(
                f"{scanner} must be one native invocation with its arguments"
            )
        return invocation
    return command


def provision_tools(root: Path, groups: list[Group], timeout: float) -> None:
    commands = [
        uvx_scanner(
            package_script_invocation(
                managed_scanner_command(gate["command"], root / group["path"]),
                root / group["path"],
            )[0]
        )
        for group in groups
        for gate in group["checks"]
    ]
    executables = {command[0] for command in commands}
    if executables & MANAGED_PYTHON_SCANNERS:
        executables.add("uv")
    executables.update(
        argument
        for command in commands
        for argument in command[1:]
        if argument in PACKAGES
    )
    selected = sorted(
        PACKAGES[name] + "@latest" for name in executables & PACKAGES.keys()
    )
    if selected:
        provision_batch(selected, timeout)
    pin_python_scanners(sorted(executables & MANAGED_PYTHON_SCANNERS), timeout)


def scanner_version(
    name: str, offline: bool, timeout: float, now: datetime | None = None
) -> str | None:
    """The scanner's latest version, or None when it cannot run."""
    wait = ["--exclude-newer", release_cutoff(now)]
    try:
        done = subprocess.run(
            [
                "uvx",
                *(["--offline"] if offline else []),
                *wait,
                name + "@latest",
                "--version",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    found = VERSION_NUMBER.search(done.stdout)
    return found[0] if found else ""


def shared_tool_folder() -> Path:
    """The tool folder that every checkout on this machine shares."""
    return Path(os.environ.get("RUNNER_TEMP") or temporary_root()) / "hard-eng-tools"


def scanner_store() -> Path:
    """The file, shared by every checkout, that holds the versions of one cutoff hour."""
    shared = shared_tool_folder()
    return shared / "scanner-versions.json"


def stored_scanner_versions(cutoff: str) -> dict[str, str]:
    """The versions stored for this cutoff hour; none when the file is missing or old."""
    try:
        stored = json.loads(scanner_store().read_text())
        versions = stored["versions"] if stored["cutoff"] == cutoff else {}
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    if not isinstance(versions, dict):
        return {}
    return {
        name: version
        for name, version in versions.items()
        if isinstance(name, str)
        and isinstance(version, str)
        and VERSION_NUMBER.fullmatch(version)
    }


def lost_scanner_note(output: str) -> str:
    """The step for a failed quick gate whose stored scanner version left uv's cache."""
    before, lost, _ = output.partition(UV_LOST_SCANNER)
    if not (lost and before.split() and quick_mode()):
        return ""
    return NOT_INSTALLED.format(error=f"{before.split()[-1]} is not in uv's cache")


def pin_python_scanners(names: list[str], timeout: float) -> None:
    """Resolve each scanner's latest version once, serially, so parallel gates run it
    pinned instead of each refreshing uv's shared interpreter cache at once.
    A quick check reuses the versions that a lookup of the same cutoff hour stored."""
    cutoff = release_cutoff()
    stored = stored_scanner_versions(cutoff)
    found = False
    for name in names:
        if quick_mode() and name in stored:
            SCANNER_VERSIONS[name] = stored[name]
            continue
        version = scanner_version(name, quick_mode(), timeout)
        if version is None and quick_mode():
            version = scanner_version(name, False, timeout)
            if version is None:
                raise ValueError(NOT_INSTALLED.format(error=f"{name} could not be run"))
        if version:
            SCANNER_VERSIONS[name] = stored[name] = version
            found = True
    if found:
        try:
            path = scanner_store()
            path.parent.mkdir(parents=True, exist_ok=True)
            replace_file(path, json.dumps({"cutoff": cutoff, "versions": stored}))
        except OSError:
            pass


def bun_age(tool: str, seconds: int) -> str:
    """Bun ignores MISE_MINIMUM_RELEASE_AGE, so an npm tool also passes its own."""
    return NPM_LATEST_PACKAGE.sub(
        rf'\1[bun_args="--minimum-release-age={seconds}"]\2', tool
    )


def tool_name(tool: str) -> str:
    """The tool without its install options or version, as mise names it."""
    return TOOL_BRACKETS_OR_LATEST.sub("", tool)


def provision_batch(batch: list[str], timeout: float) -> None:
    # Two days avoids newly broken releases.
    batch = [bun_age(tool, RELEASE_AGE_SECONDS) for tool in batch]
    shared = shared_tool_folder()
    # Checkouts on other Hard Eng revisions rewrite these files while this one runs.
    storage = shared if "RUNNER_TEMP" in os.environ else checkout_storage(shared)
    environment = os.environ.copy()
    for name, directory in {
        "MISE_DATA_DIR": storage / "mise/data",
        "MISE_CACHE_DIR": storage / "mise/cache",
        "MISE_STATE_DIR": storage / "mise/state",
        "BUN_INSTALL_CACHE_DIR": shared / "bun/cache",
    }.items():
        environment.setdefault(name, str(directory))
    bun_node(storage, environment)
    if shutil.which("gh"):
        environment.setdefault(
            "MISE_GITHUB_CREDENTIAL_COMMAND",
            'gh auth token --hostname "$MISE_CREDENTIAL_HOST"',
        )
    if quick_mode():
        try:
            if use_installed_tools(batch, storage, environment, timeout):
                return
            print("Install missing native tools: " + ", ".join(batch), flush=True)
            provision_latest(batch, storage, environment, timeout)
        except (subprocess.SubprocessError, OSError, ValueError) as error:
            raise ValueError(NOT_INSTALLED.format(error=error)) from error
        return
    print("Prepare latest native tools: " + ", ".join(batch), flush=True)
    provision_latest(batch, storage, environment, timeout)


def temporary_root() -> Path:
    """Biome skips its React rules for files below a hidden folder, so avoid one."""
    root = Path(tempfile.gettempdir())
    hidden = any(part.startswith(".") for part in root.resolve().parts)
    return VISIBLE_TEMP if hidden else root


def checkout_storage(shared: Path) -> Path:
    """This checkout's tool folder, held until exit; a push snapshot uses its owner's."""
    snapshot, _, owner = os.environ.get(TOOL_OWNER, "").partition(os.pathsep)
    checkout = Path(owner) if snapshot == str(CHECKOUT) else CHECKOUT
    import hashlib

    checkouts = shared / "checkouts"
    storage = checkouts / hashlib.sha256(str(checkout).encode()).hexdigest()[:16]
    if not HELD:
        storage.mkdir(parents=True, exist_ok=True)
        lock = (storage / "lock").open("a")
        fcntl.flock(lock, fcntl.LOCK_SH)
        HELD.append(lock)
        storage.mkdir(parents=True, exist_ok=True)
        replace_file(storage / "checkout", str(checkout))
        prune_checkouts(checkouts)
    return storage


def prune_checkouts(checkouts: Path) -> None:
    """Drop tool folders of deleted checkouts that no running check holds."""
    for path in checkouts.iterdir():
        try:
            owner = Path((path / "checkout").read_text())
        except OSError:
            continue
        if owner.exists():
            continue
        try:
            lock = (path / "lock").open("a")
        except FileNotFoundError:
            continue
        with lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                continue
            shutil.rmtree(path, ignore_errors=True)


def newest_launcher(launchers: Path) -> Path | None:
    found = [
        path for path in launchers.glob("[0-9]*/") if (path / MISE_BINARY).is_file()
    ]
    return max(
        found,
        key=lambda path: [int(part) for part in DIGIT_RUN.findall(path.name)],
        default=None,
    )


def use_installed_tools(
    batch: list[str], storage: Path, environment: dict[str, str], timeout: float
) -> bool:
    """Resolve already-installed tool versions without any network request."""
    launcher = newest_launcher(storage / "mise-launcher")
    if launcher is None:
        return False
    result = subprocess.run(
        [str(launcher / MISE_BINARY), "--no-config", "env", "--json", *batch],
        cwd=storage,
        text=True,
        timeout=timeout,
        capture_output=True,
        check=False,
        env={**environment, "MISE_OFFLINE": "1", "MISE_NPM_PACKAGE_MANAGER": "bun"},
    )
    if result.returncode != 0 or "Failed to resolve tool version" in result.stderr:
        return False
    export_tool_paths(result.stdout, Path(environment["MISE_DATA_DIR"]))
    return not broken_tools(batch, Path(environment["MISE_DATA_DIR"]), timeout)


def broken_tools(
    batch: list[str], data_directory: Path, timeout: float
) -> dict[str, str]:
    """Each installed npm tool that fails `--version`, such as a release published
    without its platform binary, mapped to the reason."""
    names = {spec: name for name, spec in PACKAGES.items() if spec.startswith("npm:")}
    probes = {}
    for tool in batch:
        name = names.get(tool_name(tool))
        executable = shutil.which(name) if name else None
        if executable and Path(executable).resolve().is_relative_to(
            data_directory.resolve()
        ):
            probes[tool] = (
                name,
                executable,
                subprocess.Popen(
                    [executable, "--version"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                ),
            )
    broken = {}
    for tool, (name, executable, probe) in probes.items():
        try:
            _, error = probe.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            probe.kill()
            error = probe.communicate()[1] + "\nno answer to --version"
        if probe.returncode == 0:
            continue
        missing = MISSING_MODULE_NAME.search(error)
        reason = (
            "missing " + missing[1]
            if missing
            else (error.strip().splitlines() or [f"exit code {probe.returncode}"])[-1]
        )
        # The executable sits in <installs>/<tool>/<version link>/bin.
        version = Path(executable).parents[1].resolve().name
        broken[tool] = f"tool install broken: {name} {version} {reason}"
    return broken


GITHUB_DENIED = "403 Forbidden) for url (https://api.github.com/repos/"


def run_mise(
    command: list[str],
    arguments: list[str],
    storage: Path,
    environment: dict[str, str],
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [*command, *arguments],
        # The project's packageManager pin would otherwise pick the Bun mise drives.
        cwd=storage,
        text=True,
        timeout=timeout,
        capture_output=True,
        check=False,
        env={
            **environment,
            "MISE_FETCH_REMOTE_VERSIONS_CACHE": "0s"
            if arguments[0] == "install"
            else "1h",
        },
    )
    result.stderr = ACTIVATION_NOTE.sub("", result.stderr)
    return result


def provision_latest(
    batch: list[str], storage: Path, environment: dict[str, str], timeout: float
) -> None:
    with mise_launcher(storage / "mise-launcher", environment, timeout) as mise:
        environment["PATH"] = os.pathsep.join(
            [str(mise.parent), environment.get("PATH", os.defpath)]
        )
        command = [
            "env",
            "MISE_NPM_PACKAGE_MANAGER=bun",
            "MISE_PREFER_OFFLINE=false",
            "MISE_USE_VERSIONS_HOST=false",
            f"MISE_MINIMUM_RELEASE_AGE={RELEASE_AGE_SECONDS // 86400}d",
            "mise",
            "--no-config",
        ]
        for arguments in (["install", *batch], ["env", "--json", *batch]):
            result = run_mise(command, arguments, storage, environment, timeout)
            if arguments[0] == "install" and GITHUB_DENIED in result.stderr:
                # A cloud GitHub proxy refuses other repositories' release lists; mise's host mirrors them.
                command[3] = "MISE_USE_VERSIONS_HOST=true"
                result = run_mise(command, arguments, storage, environment, timeout)
            print(result.stderr, file=sys.stderr, end="")
            result.check_returncode()
            if "Failed to resolve tool version" in result.stderr:
                raise ValueError(
                    "Latest tool versions could not be resolved; retry provisioning"
                )
        data_directory = Path(environment["MISE_DATA_DIR"])
        export_tool_paths(result.stdout, data_directory)
        broken = broken_tools(batch, data_directory, timeout)
        if not broken:
            return
        # An age-allowed release can lack its platform binary while a newer one fixes it.
        print(
            "Reinstall at the newest release: " + "; ".join(broken.values()),
            file=sys.stderr,
            flush=True,
        )
        names = [tool_name(tool) for tool in broken]
        retry = [bun_age(name + "@latest", 0) for name in names]
        command[4] = "MISE_MINIMUM_RELEASE_AGE=0"
        for arguments in (
            ["uninstall", "--all", *names],
            ["install", *retry],
            ["env", "--json", *retry],
        ):
            result = run_mise(command, arguments, storage, environment, timeout)
            print(result.stderr, file=sys.stderr, end="")
            result.check_returncode()
        export_tool_paths(result.stdout, data_directory)
        broken = broken_tools(retry, data_directory, timeout)
        if broken:
            raise ValueError("; ".join(broken.values()))


def bun_node(storage: Path, environment: dict[str, str]) -> None:
    """Run `#!/usr/bin/env node` tools on Bun, so checks prove the Bun runtime."""
    bun = shutil.which("bun", path=environment.get("PATH"))
    if bun is None:
        return
    shims = storage / "bun-node"
    search = os.pathsep.join(
        entry
        for entry in environment.get("PATH", "").split(os.pathsep)
        if Path(entry).parent != shims
    )
    node = shutil.which("node", path=search)
    script = "#!/bin/sh\n"
    if node is not None:
        # Under Bun, miniflare's typegen fetch reaches a real parked domain, not workerd.
        script += (
            'case "$*" in *node_modules/.bin/wrangler*|*node_modules/wrangler/*|'
            "*node_modules/.bin/miniflare*|*node_modules/miniflare/*) "
            f'exec {shlex.quote(node)} "$@";; esac\n'
        )
        # Under Bun, React Doctor waits 30 s for an idle worker before it exits.
        script += (
            'case "$*" in *npm-react-doctor/*|*node_modules/.bin/react-doctor*|'
            f'*node_modules/react-doctor/*) exec {shlex.quote(node)} "$@";; esac\n'
        )
    # Node runs a piped script when no script or -e/-p is named; Bun prints help and exits 0.
    script += (
        "piped=1\nvalue=0\n"
        'for argument in "$@"; do\n  [ "$value" = 1 ] && { value=0; continue; }\n'
        '  case "$argument" in\n'
        "    -r|--require|--import|--loader) value=1;;\n"
        "    -e*|-p*|-c|-i|-h|-v|-|--eval*|--print*|--check|--interactive|--help"
        "|--version|--test*) piped=0;;\n    -*) ;;\n    *) piped=0;;\n  esac\ndone\n"
        'if [ "$piped" = 1 ]; then\n  source=$(cat)\n  [ -z "$source" ] && exit 0\n'
        f'  printf "%s\\n" "$source" | {shlex.quote(bun)} "$@" -\n  exit $?\nfi\n'
    )
    script += f'exec {shlex.quote(bun)} "$@"\n'
    import hashlib

    # Another Hard Eng revision in this checkout, such as a pushed update, writes its own.
    directory = shims / hashlib.sha256(script.encode()).hexdigest()[:16]
    directory.mkdir(parents=True, exist_ok=True)
    shim = directory / "node"
    if shim.is_symlink() or not shim.is_file() or shim.read_text() != script:
        replace_file(shim, script, 0o755)
    for target in (environment, os.environ):
        target["PATH"] = os.pathsep.join(
            [str(directory), target.get("PATH", os.defpath)]
        )


def replace_file(path: Path, text: str, mode: int = 0o644) -> None:
    """A concurrent reader sees the old or the new file, never a partial one."""
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as file:
            file.write(text)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def export_tool_paths(output: str, data_directory: Path) -> None:
    environment = json.loads(output)
    if not isinstance(environment, dict) or not isinstance(
        environment.get("PATH"), str
    ):
        raise TypeError("Native tool setup did not return an executable PATH")
    tool_paths = [
        path
        for path in environment["PATH"].split(os.pathsep)
        if Path(path).resolve().is_relative_to(data_directory.resolve())
        and Path(path).parts[-2:] != ("node_modules", ".bin")
    ]
    os.environ["PATH"] = os.pathsep.join([*tool_paths, os.environ["PATH"]])


@contextmanager
def mise_launcher(
    launchers: Path, environment: dict[str, str], timeout: float
) -> Generator[Path]:
    """Yield the newest published mise, installed once per version and held while used."""
    if shutil.which("bun", path=environment.get("PATH")) is None:
        raise ValueError(
            "Hard Eng installs its tools with Bun: install Bun, or in CI add an "
            "oven-sh/setup-bun step before the check"
        )
    launchers.mkdir(parents=True, exist_ok=True)
    if not (launchers / "package.json").is_file():
        replace_file(launchers / "package.json", '{"private": true}\n')
    version = json.loads(
        subprocess.run(
            ["bun", "pm", "view", MISE_LATEST, "version", "--json"],
            cwd=launchers,
            env=environment,
            text=True,
            timeout=timeout,
            capture_output=True,
            check=True,
        ).stdout
    )
    if not isinstance(version, str) or not TOOL_VERSION.fullmatch(version):
        raise TypeError("Bun did not return a usable latest mise version")
    installation = launchers / version
    with (launchers / f"{version}.lock").open("a") as use:
        fcntl.flock(use, fcntl.LOCK_SH)
        with (launchers / "install.lock").open("a") as install:
            try:
                fcntl.flock(
                    install,
                    fcntl.LOCK_EX
                    | (fcntl.LOCK_NB if (installation / MISE_BINARY).is_file() else 0),
                )
            except BlockingIOError:
                pass
            else:
                if not (installation / MISE_BINARY).is_file():
                    shutil.rmtree(installation, ignore_errors=True)
                    install_launcher(installation, environment, timeout)
                prune_launchers(launchers, version)
        yield installation / MISE_BINARY


def install_launcher(
    installation: Path, environment: dict[str, str], timeout: float
) -> None:
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=installation.parent))
    try:
        (staging / "package.json").write_text('{"private": true}\n')
        package = f"{MISE_PACKAGE}@{installation.name}"
        result = subprocess.run(
            ["bun", "add", "--minimum-release-age=0", package],
            cwd=staging,
            env=environment,
            text=True,
            timeout=timeout,
            capture_output=True,
            check=False,
        )
        print(result.stderr, file=sys.stderr, end="")
        result.check_returncode()
        reported = subprocess.run(
            [str(staging / MISE_BINARY), "--version"],
            text=True,
            timeout=timeout,
            capture_output=True,
            check=False,
        ).stdout.split()
        if reported[:1] != [installation.name]:
            raise ValueError(f"mise {installation.name} failed its installation check")
        staging.rename(installation)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def prune_launchers(launchers: Path, current: str) -> None:
    """Under the install lock, drop interrupted installs and unheld older versions."""
    for path in launchers.iterdir():
        if path.name.startswith(".staging-"):
            shutil.rmtree(path, ignore_errors=True)
        elif path.is_dir() and path.name != current:
            with (launchers / f"{path.name}.lock").open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                shutil.rmtree(path, ignore_errors=True)
