"""Provision current native tools before concurrent gate execution."""

import fcntl
import hashlib
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
from pathlib import Path
from typing import IO

from fallow_report import native_scanner_command
from gate_config import Group
from project_setup import package_script_invocation

NATIVE_SCANNERS = {
    "dart-decimate": "dart-decimate",
    "react-doctor": "React Doctor",
}
MANAGED_PYTHON_SCANNERS = {"ruff", "pyrefly", "vulture", "semgrep", "zizmor", "poetry"}
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
VISIBLE_TEMP = Path("/tmp")
HELD: list[IO[str]] = []
NOT_INSTALLED = (
    "Tools are not installed yet and cannot be fetched now: {error}. "
    "Connect once or run the full check (python3 .hooks/hard-eng.py check) to install them."
)


def quick_mode() -> bool:
    return "--quick" in sys.argv


def ensure_python_runtime() -> None:
    """Run the installed CLI with its YAML dependency without changing host Python."""
    if importlib.util.find_spec("yaml") is None:
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


def uvx_scanner(command: list[str]) -> list[str]:
    """A configured `uvx ruff@latest …` gate runs like `ruff …`, so it is pinned too."""
    tool = command[1] if len(command) > 1 and command[0] == "uvx" else ""
    name = tool.removesuffix("@latest")
    if tool.endswith("@latest") and name in MANAGED_PYTHON_SCANNERS:
        return [name, *command[2:]]
    return command


def managed_command(command: list[str], directory: Path | None = None) -> list[str]:
    command = uvx_scanner(command)
    if directory is not None:
        command = with_entry_points(
            managed_scanner_command(command, directory), directory
        )
    if command[0] in MANAGED_PYTHON_SCANNERS:
        offline = ["--offline"] if quick_mode() else []
        version = SCANNER_VERSIONS.get(command[0])
        tool = f"{command[0]}@{version or 'latest'}"
        return ["uvx", *offline, tool, *command[1:]]
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
    packages = {
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
        if argument in packages
    )
    selected = sorted(
        packages[name] + "@latest" for name in executables & packages.keys()
    )
    if selected:
        provision_batch(selected, timeout)
    pin_python_scanners(sorted(executables & MANAGED_PYTHON_SCANNERS), timeout)


def scanner_version(name: str, offline: bool, timeout: float) -> str | None:
    """The scanner's latest version, or None when it cannot run."""
    try:
        done = subprocess.run(
            ["uvx", *(["--offline"] if offline else []), name + "@latest", "--version"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    found = re.search(r"\d+(?:\.\d+)+", done.stdout)
    return found[0] if found else ""


def pin_python_scanners(names: list[str], timeout: float) -> None:
    """Resolve each scanner's latest version once, serially, so parallel gates run it
    pinned instead of each refreshing uv's shared interpreter cache at once."""
    for name in names:
        version = scanner_version(name, quick_mode(), timeout)
        if version is None and quick_mode():
            version = scanner_version(name, False, timeout)
            if version is None:
                raise ValueError(NOT_INSTALLED.format(error=f"{name} could not be run"))
        if version:
            SCANNER_VERSIONS[name] = version


def provision_batch(batch: list[str], timeout: float) -> None:
    # Bun reads a user bunfig release-age limit and ignores MISE_MINIMUM_RELEASE_AGE.
    batch = [
        re.sub(
            r"^(npm:[^\[]+?)(@latest)$",
            r'\1[bun_args="--minimum-release-age=0"]\2',
            tool,
        )
        for tool in batch
    ]
    shared = Path(os.environ.get("RUNNER_TEMP") or temporary_root()) / "hard-eng-tools"
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
        key=lambda path: [int(part) for part in re.findall(r"\d+", path.name)],
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
    return True


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
            "MISE_MINIMUM_RELEASE_AGE=0s",
            "mise",
            "--no-config",
        ]
        for arguments in (["install", *batch], ["env", "--json", *batch]):
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
            print(result.stderr, file=sys.stderr, end="")
            result.check_returncode()
            if "Failed to resolve tool version" in result.stderr:
                raise ValueError(
                    "Latest tool versions could not be resolved; retry provisioning"
                )
    export_tool_paths(result.stdout, Path(environment["MISE_DATA_DIR"]))


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
    # Node runs a piped script when no script or -e/-p is named; Bun prints help and exits 0.
    script += (
        "piped=1\n"
        'for argument in "$@"; do\n  case "$argument" in\n'
        "    -e*|-p*|-c|-i|-h|-v|-|--eval*|--print*|--check|--interactive|--help"
        "|--version|--test*) piped=0;;\n    -*) ;;\n    *) piped=0;;\n  esac\ndone\n"
        'if [ "$piped" = 1 ]; then\n  source=$(cat)\n  [ -z "$source" ] && exit 0\n'
        f'  printf "%s\\n" "$source" | {shlex.quote(bun)} "$@" -\n  exit $?\nfi\n'
    )
    script += f'exec {shlex.quote(bun)} "$@"\n'
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
    if not isinstance(version, str) or not re.fullmatch(r"\d[\w.+-]*", version):
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
