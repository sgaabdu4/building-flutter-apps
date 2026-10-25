"""Adapt existing CI and generate only explicitly configured new workflows."""

import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from gate_config import GateConfig, Group, JsonValue
from project_setup import dependency_command

MAINTENANCE_EVENTS = {"schedule", "workflow_dispatch"}
OLD_TRIGGERS = (
    "on:\n  push:\n    branches-ignore:\n      - 'feature/**'\n  pull_request:\n"
)
OLD_BASE = "${{ github.event.pull_request.base.sha || github.event.before }}"
NEW_BASE = "${{ inputs.base_sha || github.event.pull_request.base.sha || github.event.before }}"
BOOTSTRAP_TOOLS = ["uv@latest", "python@3.12"]


def bun_specification(root: Path, package: Group, groups: list[Group]) -> str:
    """Reuse the pin of an established workspace dependency-install owner."""
    directory = root / package["path"]
    manifest = json.loads((directory / "package.json").read_text())
    if (
        "packageManager" not in manifest
        and not (directory / "bun.lock").exists()
        and not any(gate.get("role") == "lockfiles" for gate in package["checks"])
    ):
        owners = sorted(
            (
                root / group["path"]
                for group in groups
                if root / group["path"] in directory.parents
                and any(
                    gate.get("role") == "lockfiles"
                    and gate["command"] == ["bun", "install", "--frozen-lockfile"]
                    for gate in group["checks"]
                )
            ),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        if owners and (owners[0] / "package.json").is_file():
            manifest = json.loads((owners[0] / "package.json").read_text())
    declared = manifest.get("packageManager", "bun@latest")
    if isinstance(declared, str) and not declared.startswith("bun@"):
        declared = "bun@latest"
    if (
        not isinstance(declared, str)
        or re.fullmatch(
            r"bun@(?:latest|\d+(?:\.\d+){0,2}(?:-[\w.-]+)?)(?:\+[\w.-]+)?", declared
        )
        is None
    ):
        raise ValueError("CI requires a valid bun packageManager version")
    return declared.split("+", 1)[0]


def impact_tools(root: Path, groups: list[Group]) -> list[str]:
    """Read selected SDK requirements before third-party Python packages exist."""
    tools = list(BOOTSTRAP_TOOLS)
    for group in groups:
        directory = root / group["path"]
        language = group.get("language")
        commands = " ".join(" ".join(gate["command"]) for gate in group["checks"])
        executables = {Path(gate["command"][0]).name for gate in group["checks"]}
        flutter = "flutter" in executables or re.search(
            r"\bflutter\s+(?:pub|test|analyze|build)\b", commands
        )
        dart = "dart" in executables or re.search(
            r"\bdart\s+(?:pub|test|analyze|compile|run|format)\b", commands
        )
        if language == "dart" or flutter or dart:
            tools.append("flutter@latest" if flutter else "dart@latest")
        if language == "python" and (directory / "poetry.lock").exists():
            tools.append("poetry@latest")
        if language == "javascript":
            tools.append(bun_specification(root, group, groups))
    if "flutter@latest" in tools:
        tools = [tool for tool in tools if tool != "dart@latest"]
    return list(dict.fromkeys(tools))


def impact_runner(groups: list[Group]) -> str:
    """Xcode runs on macOS; every other selection stays on Linux."""
    swift = any(group.get("language") == "swift" for group in groups)
    return "macos-latest" if swift else "ubuntu-latest"


def workflow_triggers(source: Path, base: str) -> tuple[str, str]:
    """The template trigger block and its copy for the project's base branch."""
    template = (source / ".github/workflows/hard-eng.yml").read_text()
    block = template[template.index("on:\n") : template.index("\n\npermissions:") + 1]
    # Only this source repository releases from develop.
    project = block.replace("      - develop\n", "", 1)
    return block, project.replace("      - main\n", f"      - {base}\n", 1)


def migrate_workflow_triggers(root: Path, source: Path, content: str) -> str:
    """Move generated push/PR triggers to default-branch pushes plus workflow_call."""
    from shipping import load_policy

    policy = load_policy(root, required=False)
    if policy is None or OLD_TRIGGERS not in content:
        return content
    _, triggers = workflow_triggers(source, policy["base"])
    return content.replace(OLD_TRIGGERS, triggers, 1).replace(OLD_BASE, NEW_BASE, 1)


def workflow_budget(root: Path, content: str) -> str:
    from shipping import load_policy

    policy = load_policy(root, required=False)
    if policy is None:
        return content
    return re.sub(
        r"(?ms)(^  hard-eng:\n.*?^    timeout-minutes: )\d+$",
        lambda match: match[1] + str(math.ceil(policy["ci_seconds"] / 60)),
        content,
    )


def migrate_workflow_pins(content: str) -> str:
    for action, old, new, before, after in (
        (
            "actions/checkout",
            "fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09",
            "3d3c42e5aac5ba805825da76410c181273ba90b1",
            "v5",
            "v7.0.1",
        ),
    ):
        content = re.sub(
            rf"(?m)^([ \t]*(?:-[ \t]+)?uses:[ \t]+){re.escape(action)}@{old}([ \t]*(?:#.*)?)$",
            lambda match, action=action, new=new, before=before, after=after: (
                match[1]
                + action
                + "@"
                + new
                + match[2].replace(f"# {before}", f"# {after}", 1)
            ),
            content,
        )
    return content


def migrate_bun(source: Path, content: str) -> str:
    """Replace the generated pnpm bootstrap with the template's Bun steps."""
    template = (source / ".github/workflows/hard-eng.yml").read_text()
    start = template.index("      - uses: oven-sh/setup-bun@")
    setup = template[start : template.index("      - name: ", start)]
    launcher = re.search(r"bun x \S+ mise", template)
    if launcher is None:
        raise ValueError("Hard Eng workflow template has no Bun mise launcher")
    content = re.sub(
        r"(?m)^      - [^\n]*\n(?:        [^\n]*\n)*",
        lambda step: setup if re.search(r"\buses: pnpm/setup@", step[0]) else step[0],
        content,
    )
    content = re.sub(
        r"pnpm dlx (?:--config\.ignore-scripts=false )?--allow-build=@jdxcode/mise "
        r"--package=@jdxcode/mise@latest mise",
        lambda _: launcher[0],
        content,
    )
    content = re.sub(
        r'(?m)^( +)echo "PNPM_CONFIG_STORE_DIR=[^\n]*\n +echo "PNPM_CONFIG_CACHE_DIR=[^\n]*\n',
        r'\1echo "BUN_INSTALL_CACHE_DIR=$RUNNER_TEMP/hard-eng-tools/bun/cache"\n',
        content,
    )
    tool = r"(?:node@latest|pnpm@[\w.+-]+)"
    return "".join(
        re.sub(rf"(?<=['\"]){tool} ?| {tool}(?=[ '\"\n])", "", line)
        if "mise --no-config" in line or "SDK_TOOLS" in line
        else line
        for line in content.splitlines(keepends=True)
    )


LEGACY_PACKAGE = '--package="@jdxcode/mise-linux-${RUNNER_ARCH,,}@latest"'
MISE_PACKAGE = '--package="$MISE_PACKAGE"'
RUNNER_JOB = """  impact:
    name: impact
    runs-on: ubuntu-latest
    timeout-minutes: 5
    outputs:
      runner: ${{ steps.impact.outputs.runner }}
    steps:
%s      - name: Choose the runner
        id: impact
        env:
          BASE_SHA: ${{ inputs.base_sha || github.event.pull_request.base.sha || github.event.before }}
          GH_TOKEN: ${{ github.token }}
        run: python3 .hooks/hard-eng.py impact --base "$BASE_SHA" >> "$GITHUB_OUTPUT" || echo runner=macos-latest >> "$GITHUB_OUTPUT"

"""
CHECK_JOB = "  hard-eng:\n    name: hard-eng\n    runs-on: ubuntu-latest\n"
RUNNER_HEADER = (
    "    needs: impact\n    if: ${{ !cancelled() }}\n"
    "    runs-on: ${{ needs.impact.outputs.runner || 'macos-latest' }}\n"
)


def migrate_launcher(source: Path, content: str) -> str:
    """Bash 3.2 on macOS runners cannot lowercase with ${var,,}; compute the package once per job."""
    if LEGACY_PACKAGE not in content and MISE_PACKAGE not in content:
        return content
    template = (source / ".github/workflows/hard-eng.yml").read_text()
    echo = next(line for line in template.splitlines() if "MISE_PACKAGE=" in line)
    # Each job runs on its own runner, so every job that launches mise sets the package.
    jobs = re.split(r"(?m)^(?=  [A-Za-z0-9_-]+:\n)", content)
    for index, job in enumerate(jobs):
        if (
            LEGACY_PACKAGE in job or MISE_PACKAGE in job
        ) and 'echo "MISE_PACKAGE=' not in job:
            anchor = re.search(r'(?m)^( *)echo "BUN_INSTALL_CACHE_DIR=[^\n]*\n', job)
            if anchor is None:
                name = job.split(":", 1)[0].strip()
                print(
                    f"CI launcher not updated in job {name}: add the MISE_PACKAGE line "
                    "from the Hard Eng template to its first step so mise installs on "
                    "every runner.",
                    file=sys.stderr,
                )
                continue
            line = anchor[1] + echo.strip() + "\n"
            jobs[index] = job[: anchor.end()] + line + job[anchor.end() :]
    return "".join(jobs).replace(LEGACY_PACKAGE, MISE_PACKAGE)


def migrate_swift_runner(config: GateConfig, content: str) -> str:
    """A project with a Swift group runs its check on macOS only when impact selects one."""
    if impact_runner(config["packages"]) != "macos-latest" or "  impact:\n" in content:
        return content
    checkout = re.search(
        r"(?m)^      - uses: actions/checkout@[^\n]*\n(?:        [^\n]*\n)*", content
    )
    if content.count(CHECK_JOB) != 1 or checkout is None:
        print(
            "CI runner not added: .github/workflows/hard-eng.yml is customised. "
            "Add the impact job from the Hard Eng generator and make the hard-eng "
            "job use its runner output so Swift checks run on macOS.",
            file=sys.stderr,
        )
        return content
    job = RUNNER_JOB % checkout[0] + CHECK_JOB.replace(
        "    runs-on: ubuntu-latest\n", RUNNER_HEADER
    )
    return content.replace(CHECK_JOB, job, 1)


OLD_PERMISSIONS = (
    "  checks: read # Verify the upstream release for scaffold-only updates.\n"
)
PERMISSIONS = "  pull-requests: read # Find the merged PR whose passed checks cover a base-branch push.\n"
OLD_LAUNCHER = "pnpm dlx --allow-build=@jdxcode/mise"
LAUNCHER = "pnpm dlx --config.ignore-scripts=false --allow-build=@jdxcode/mise"


def migrate_workflow_tools(content: str) -> str:
    launcher = f"{LAUNCHER} --package=@jdxcode/mise@latest mise --no-config"
    return re.sub(
        r"(?m)^        run: >-\n"
        r"          pnpm dlx --allow-build=@jdxcode/mise\n"
        r"          --package=@jdxcode/mise@latest mise --no-config exec\n"
        r"          (?P<tools>[^\n]+)\n"
        r"          -- (?P<check>uv run --no-project --with pyyaml python "
        r'\.hooks/hard-eng\.py check --base "\$BASE_SHA")\n',
        lambda match: (
            "        run: |\n"
            f"          {launcher} install {match['tools']} &&\n"
            f"          MISE_FETCH_REMOTE_VERSIONS_CACHE=1h {launcher} exec {match['tools']} -- {match['check']}\n"
        ),
        content,
    ).replace(f"{OLD_LAUNCHER} ", f"{LAUNCHER} ")


def migrate_docs_path(source: Path, content: str) -> str:
    """Add the template's docs-only steps to a generated workflow without them."""
    template = (source / ".github/workflows/hard-eng.yml").read_text()
    setup = "      - uses: oven-sh/setup-bun@"
    checks = "      - name: Run required checks\n"
    if "id: impact" in content:
        return content
    if any(content.count(step) != 1 for step in (setup, checks)) or (
        checks + "        if:" in content
    ):
        print(
            "Docs-only CI steps not added: .github/workflows/hard-eng.yml is customised. "
            "Copy the `impact` and docs-only secret scan steps from the Hard Eng template "
            "to skip tool setup when only docs change.",
            file=sys.stderr,
        )
        return content
    impact = template[
        template.index("      - name: Find whether") : template.index(setup)
    ]
    scan = template[
        template.index("      - name: Run the secret") : template.index(checks)
    ]
    condition = "        if: steps.impact.outputs.docs_only != 'true'\n"
    content = content.replace(setup, impact + setup)
    return content.replace(checks, scan + checks + condition)


def workflow_tools(root: Path, config: GateConfig) -> list[str]:
    tools = list(BOOTSTRAP_TOOLS)
    groups: list[Group] = [
        *config["packages"],
        {"path": ".", "checks": config["shared"]},
    ]
    for package in config["packages"]:
        directory = root / package["path"]
        language = package.get("language")
        if language not in {"python", "javascript", "dart"}:
            continue
        try:
            manager = dependency_command(directory, language)[0]
        except ValueError:
            if language != "javascript":
                raise
            manager = "bun"
        if manager in {"dart", "flutter", "bun", "poetry"}:
            specification = (
                bun_specification(root, package, groups)
                if language == "javascript"
                else manager + "@latest"
            )
            if re.fullmatch(r"[a-z]+@[\w.+-]+", specification) is None:
                raise ValueError(
                    "CI SDK specifications must contain a tool and version"
                )
            if specification not in tools:
                tools.append(specification)
    if "flutter@latest" in tools and "dart@latest" in tools:
        tools.remove("dart@latest")
    return tools


def workflow_extra_tools(root: Path, config: GateConfig) -> list[str]:
    """Keep manifest SDKs hidden behind custom command wrappers available."""
    extras: list[str] = []
    for package in config["packages"]:
        inferred = impact_tools(root, [package])
        required = workflow_tools(root, {"packages": [package], "shared": []})
        extras.extend(tool for tool in required if tool not in inferred)
    return list(dict.fromkeys(extras))


def migrate_workflow_sdks(root: Path, config: GateConfig, content: str) -> str:
    """Add SDKs that packages added after CI generation need; keep project tools."""
    required = workflow_tools(root, config)[len(BOOTSTRAP_TOOLS) :]
    if "SDK_TOOLS: ${{ steps.impact.outputs.tools" in content:
        import yaml

        extras = workflow_extra_tools(root, config)
        extra_pattern = r"(?m)^      EXTRA_SDK_TOOLS: (?P<tools>[^\n]+)$"
        match = re.search(extra_pattern, content)
        if extras and match:
            old = yaml.safe_load(match["tools"])
            if isinstance(old, str) and not old.startswith("${{"):
                names = {tool.split("@", 1)[0] for tool in old.split()}
                missing = [
                    tool for tool in extras if tool.split("@", 1)[0] not in names
                ]
                if missing:
                    content = re.sub(
                        extra_pattern,
                        "      EXTRA_SDK_TOOLS: "
                        + json.dumps(" ".join([*old.split(), *missing])),
                        content,
                    )
        fallback = " ".join([*BOOTSTRAP_TOOLS, *required])
        return re.sub(
            r"SDK_TOOLS: \$\{\{ steps\.impact\.outputs\.tools \|\| '[^']*' \}\}",
            "SDK_TOOLS: ${{ steps.impact.outputs.tools || '" + fallback + "' }}",
            content,
        )
    pattern = re.compile(
        r"(?m)^(?P<indent> +)(?P<launcher>bun x (?:\S+ )+?mise --no-config) "
        r"install (?P<tools>[^&\n]+) &&\n"
        r"(?P=indent)MISE_FETCH_REMOTE_VERSIONS_CACHE=1h (?P=launcher) exec (?P=tools) -- "
    )
    match = pattern.search(content)
    if match is None:
        names = set(re.findall(r"\b([a-z]+)@", content))
        missing = [tool for tool in required if tool.split("@")[0] not in names]
        if missing:
            print(
                "CI tools not added: .github/workflows/hard-eng.yml is customised. "
                f"Add {' '.join(missing)} to its mise install and exec tool lists.",
                file=sys.stderr,
            )
        return content
    tools = match["tools"].split()
    names = {tool.split("@")[0] for tool in tools}
    tools += [tool for tool in required if tool.split("@")[0] not in names]
    if any(tool.startswith("flutter@") for tool in tools):
        tools = [tool for tool in tools if not tool.startswith("dart@")]
    if tools == match["tools"].split():
        return content
    updated = match.group(0).replace(match["tools"], " ".join(tools))
    return content.replace(match.group(0), updated, 1)


def migrate_affected_tools(
    root: Path, source: Path, config: GateConfig, content: str
) -> str:
    """Replace only the generated SDK/cache blocks; retain declared extra tools."""
    import yaml

    if "SDK_TOOLS: ${{ steps.impact.outputs.tools" in content:
        return content
    try:
        jobs = yaml.safe_load(content).get("jobs", {})
    except (yaml.YAMLError, AttributeError):
        return content
    if (
        not isinstance(jobs, dict)
        or list(jobs) != ["hard-eng"]
        or not isinstance(jobs["hard-eng"], dict)
        or "env" in jobs["hard-eng"]
    ):
        return content
    pattern = re.compile(
        r"(?m)^          (?P<launcher>bun x (?:\S+ )+?mise --no-config) "
        r"install (?P<tools>[\w@.+ -]+) &&\n"
        r"          MISE_FETCH_REMOTE_VERSIONS_CACHE=1h (?P=launcher) exec (?P=tools) -- "
        r'uv run --no-project --with pyyaml python \.hooks/hard-eng\.py check --base "\$BASE_SHA"\n'
    )
    match = pattern.search(content)
    marker = "      - name: Run required checks\n"
    if match is None or "id: impact" not in content or content.count(marker) != 1:
        return content
    if "        env:\n" not in content.split(marker, 1)[1].split("\n      - ", 1)[0]:
        return content
    template = (source / ".github/workflows/hard-eng.yml").read_text()
    required = workflow_tools(root, config)
    known = {tool.split("@", 1)[0] for tool in required}
    redundant_latest = "bun@latest" not in required and any(
        tool.startswith("bun@") and tool in required for tool in match["tools"].split()
    )
    if any(
        tool.split("@", 1)[0] in known
        and tool not in required
        and not (tool == "bun@latest" and redundant_latest)
        for tool in match["tools"].split()
    ):
        print(
            "Affected SDK setup pending: preserve and review the workflow's custom SDK versions before using dynamic provisioning.",
            file=sys.stderr,
        )
        return content
    extras = [
        tool for tool in match["tools"].split() if tool.split("@", 1)[0] not in known
    ]
    extras = list(dict.fromkeys([*extras, *workflow_extra_tools(root, config)]))
    environment = template[
        template.index("    env:\n") : template.index("    steps:\n")
    ]
    environment = environment.replace(
        "EXTRA_SDK_TOOLS: dart@latest",
        "EXTRA_SDK_TOOLS: " + json.dumps(" ".join(extras)),
    )
    content = content.replace("    steps:\n", environment + "    steps:\n", 1)
    run = template[template.index("          read -r -a tools") :]
    content = content.replace(match.group(0), run, 1)
    before, checks = content.split(marker, 1)
    sdk = (
        "          SDK_TOOLS: ${{ steps.impact.outputs.tools || '"
        + " ".join(required)
        + "' }}\n"
    )
    checks = checks.replace("        env:\n", "        env:\n" + sdk, 1)
    return migrate_tool_cache(source, before + marker + checks)


def migrate_tool_cache(source: Path, content: str) -> str:
    """Keep installed tools and store data in the template's runner storage."""
    template = (source / ".github/workflows/hard-eng.yml").read_text()
    old = '        run: python3 .hooks/hard-eng.py impact --base "$BASE_SHA" >> "$GITHUB_OUTPUT" || echo docs_only=false >> "$GITHUB_OUTPUT"\n'
    start = template.index("        run: |\n", template.index("id: impact"))
    end = template.index("      - uses: oven-sh/setup-bun@", start)
    return content.replace(old, template[start:end], 1)


IMPACT_BASE = "          BASE_SHA: ${{ inputs.base_sha || github.event.pull_request.base.sha || github.event.before }}\n"
IMPACT_TOKEN = "          GH_TOKEN: ${{ github.token }}\n"


def migrate_impact_token(content: str) -> str:
    """Give the impact step the token it needs to find an already-proven change."""
    start = content.find("        id: impact\n")
    if start < 0:
        return content
    end = content.find("      - ", start)
    end = len(content) if end < 0 else end
    step = content[start:end]
    if IMPACT_TOKEN in step or IMPACT_BASE not in step:
        return content
    step = step.replace(IMPACT_BASE, IMPACT_BASE + IMPACT_TOKEN, 1)
    return content[:start] + step + content[end:]


DOCS_SCAN = "      - name: Run the secret scan for docs-only changes\n"
MISE_TOKEN = "          GITHUB_TOKEN: ${{ github.token }}\n"


def migrate_docs_token(content: str) -> str:
    """mise reads GITHUB_TOKEN, not GH_TOKEN; without it runners hit the anonymous limit."""
    start = content.find(DOCS_SCAN)
    end = content.find("      - ", start + 1)
    step = content[start:end]
    if start < 0 or end < 0 or "GITHUB_TOKEN:" in step or IMPACT_TOKEN not in step:
        return content
    step = step.replace(IMPACT_TOKEN, IMPACT_TOKEN + MISE_TOKEN, 1)
    return content[:start] + step + content[end:]


def drop_tool_cache(content: str) -> str:
    """Remove the generated tool cache; measured restores were no faster than installs."""
    start = content.find("      - name: Cache native tool downloads\n")
    if start < 0:
        return content
    end = content.find("\n      - ", start + 1) + 1 or len(content)
    step = content[start:end]
    if "uses: actions/cache@" not in step or "hard-eng-tools" not in step:
        return content
    return content[:start] + content[end:]


def maintenance_workflows_only(workflows: list[Path]) -> bool:
    """Allow a generated quality owner beside scheduled/manual maintenance jobs."""
    import yaml

    if not workflows:
        return False
    for path in workflows:
        try:
            workflow = yaml.safe_load(path.read_text())
        except yaml.YAMLError:
            return False
        if not isinstance(workflow, dict):
            return False
        triggers = workflow.get("on", workflow.get(True))
        events = (
            {triggers}
            if isinstance(triggers, str)
            else set(triggers)
            if isinstance(triggers, (list, dict))
            and all(isinstance(event, str) for event in triggers)
            else set()
        )
        if not events or not events <= MAINTENANCE_EVENTS:
            return False
        if runs_hard_eng_check(workflow):
            return False
    return True


def runs_hard_eng_check(workflow: object, *, require_base: bool = False) -> bool:
    jobs = workflow.get("jobs") if isinstance(workflow, dict) else None
    if not isinstance(jobs, dict):
        return False
    commands = [
        match[0]
        for job in jobs.values()
        if isinstance(job, dict) and isinstance(job.get("steps"), list)
        for step in job["steps"]
        if isinstance(step, dict) and isinstance(step.get("run"), str)
        for match in re.finditer(
            r"\.hooks/hard-eng\.py\s+check(?=\s|$)[^\n;|&]*",
            step["run"].replace("\\\n", " "),
        )
    ]
    return bool(commands) and (
        not require_base
        or all(re.search(r"--base(?:\s|=)\S+", command) for command in commands)
    )


def report_missing_bun(path: Path) -> None:
    if not re.search(r"setup-bun|\bbunx\b|\bbun (?:x|install|run)\b", path.read_text()):
        print(
            f"CI adaptation pending: {path.name} runs Hard Eng without setting up Bun; "
            "add an oven-sh/setup-bun step before the check.",
            file=sys.stderr,
        )


def integrated(workflows: list[Path]) -> bool:
    """Existing CI that already runs the check needs no integration reminder."""
    import yaml

    found, complete = False, True
    for path in workflows:
        try:
            workflow = yaml.safe_load(path.read_text())
            if runs_hard_eng_check(workflow):
                found = True
                report_missing_bun(path)
                triggers = workflow.get("on", workflow.get(True))
                if (isinstance(triggers, str) and triggers in MAINTENANCE_EVENTS) or (
                    isinstance(triggers, (list, dict))
                    and triggers
                    and set(triggers) <= MAINTENANCE_EVENTS
                ):
                    continue
                if runs_hard_eng_check(workflow, require_base=True):
                    continue
                complete = False
                print(
                    f"CI adaptation pending: {path.name} runs Hard Eng without --base; "
                    "pass the PR/push comparison commit to enable affected checks.",
                    file=sys.stderr,
                )
        except yaml.YAMLError:
            continue
    return found and complete


def setup_installed(
    root: Path, base: str, names: set[str], sources: tuple[Path, Path]
) -> bool:
    """Whether changed setup-owned files are what the release's setup writes from the base."""
    from agent_hooks import HOOK_FILES

    owned = names & {".github/workflows/hard-eng.yml", *HOOK_FILES.values()}
    return not owned or setup_written(root, base, owned, sources) == owned


def setup_written(
    root: Path, base: str, names: set[str], sources: tuple[Path, Path]
) -> set[str]:
    """The changed paths the release's setup writes exactly when it updates the base tree."""
    from hook_chain import own_hooks_env
    from update import update_plan

    with tempfile.TemporaryDirectory(prefix="hard-eng-workflow-check-") as temporary:
        tree = Path(temporary) / "base"
        git = ["git", "-c", "core.hooksPath=/dev/null", "worktree"]
        subprocess.run(
            [*git, "add", "--quiet", "--detach", str(tree), base],
            cwd=root,
            stdout=sys.stderr,
            check=True,
            timeout=120,
        )
        try:
            planned = update_plan(tree, *sources, own_hooks_env(tree))[0]
        finally:
            subprocess.run(
                [*git, "remove", "--force", str(tree)],
                cwd=root,
                check=False,
                timeout=60,
            )
    return {
        name
        for name in names
        if name in planned
        and (
            not (root / name).exists()
            if planned[name] is None
            else (root / name).is_file() and planned[name] == (root / name).read_text()
        )
    }


def configure_ci(
    root: Path, source: Path, config: GateConfig, changes: dict[str, str]
) -> None:
    name = ".github/workflows/hard-eng.yml"
    workflows = [
        path
        for path in (root / ".github/workflows").glob("*")
        if path.is_file() and path.suffix in {".yml", ".yaml"}
    ]
    if (root / name).exists():
        original = (root / name).read_text()
        migrated = migrate_bun(
            source,
            migrate_workflow_tools(migrate_workflow_pins(drop_tool_cache(original))),
        )
        migrated = migrate_workflow_sdks(root, config, migrated)
        migrated = migrate_workflow_triggers(
            root, source, migrate_docs_path(source, migrated)
        )
        migrated = migrate_affected_tools(root, source, config, migrated)
        migrated = migrate_docs_token(migrate_impact_token(migrated))
        migrated = migrate_swift_runner(config, migrate_launcher(source, migrated))
        if "\n  pull-requests:" not in migrated:
            migrated = migrated.replace(
                OLD_PERMISSIONS, OLD_PERMISSIONS + PERMISSIONS, 1
            )
        migrated = migrated.replace(
            "MISE_MINIMUM_RELEASE_AGE: 0s\n", "MISE_MINIMUM_RELEASE_AGE: 2d\n"
        )
        if migrated != original:
            changes[name] = migrated
        integrated(workflows)
        return
    if workflows and not maintenance_workflows_only(workflows):
        if integrated(workflows):
            return
        print(
            "Existing CI retained: integrate missing Hard Eng checks into their current jobs and require those results in shipping.checks; do not add a duplicate full pipeline.",
            file=sys.stderr,
        )
        return
    from shipping import load_policy

    policy = load_policy(root, required=False)
    if policy is None:
        print(
            "CI setup pending: configure project shipping checks and a measured ci_seconds budget, then rerun setup. The source repository's timeout is not a project budget.",
            file=sys.stderr,
        )
        return
    shipping = config.get("shipping")
    checks = shipping.get("checks") if isinstance(shipping, dict) else None
    if not isinstance(checks, list) or not all(
        isinstance(check, str) for check in checks
    ):
        raise ValueError("Generated CI requires shipping checks in gate configuration")
    if "hard-eng" not in checks:
        checks.append("hard-eng")
    tools = workflow_tools(root, config)
    block, triggers = workflow_triggers(source, policy["base"])
    changes[name] = (
        (source / name)
        .read_text()
        .replace(
            "      EXTRA_SDK_TOOLS: dart@latest\n",
            "      EXTRA_SDK_TOOLS: "
            + json.dumps(" ".join(workflow_extra_tools(root, config)))
            + "\n",
            1,
        )
        .replace(
            " || '" + " ".join(BOOTSTRAP_TOOLS) + "'",
            " || '" + " ".join(tools) + "'",
            1,
        )
        .replace(block, triggers, 1)
    )
    changes[name] = workflow_budget(root, migrate_swift_runner(config, changes[name]))


def add_workflow_checks(config: GateConfig) -> None:
    for role, command in (
        ("workflows", ["actionlint", "-no-color"]),
        (
            "ci-security",
            [
                "zizmor",
                "--strict-collection",
                "--persona=auditor",
                "--format=plain",
                ".",
            ],
        ),
    ):
        if any(
            gate.get("role") == role
            or (gate.get("command") and Path(gate["command"][0]).name == command[0])
            for gate in config["shared"]
        ):
            continue
        config["shared"].append(
            {
                "name": command[0],
                "role": role,
                "parallel": True,
                "command": command,
            }
        )


RUNNER_MULTIPLIERS = {"windows": 2, "macos": 10}


def billed_job(job: dict[str, JsonValue]) -> tuple[int, float, int] | None:
    """Billed whole minutes, actual minutes and runner multiplier; None when never started."""
    from shipping import _timestamp

    if not job.get("runner_name") or not job.get("steps"):
        return None
    minutes = (
        _timestamp(job.get("completed_at"), "job")
        - _timestamp(job.get("started_at"), "job")
    ) / 60
    labels = job.get("labels")
    names = " ".join(map(str, labels if isinstance(labels, list) else [])).lower()
    multiplier = next(
        (value for name, value in RUNNER_MULTIPLIERS.items() if name in names), 1
    )
    return math.ceil(minutes) * multiplier, minutes, multiplier


def workflow_jobs(
    root: Path, repository: str, days: int
) -> tuple[int, list[tuple[str, str, dict[str, JsonValue]]]]:
    from concurrent.futures import ThreadPoolExecutor
    from datetime import UTC, datetime, timedelta

    from shipping import _api_items

    since = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
    runs = _api_items(
        root,
        f"repos/{repository}/actions/runs?per_page=100&created=>={since}",
        "workflow_runs",
        "workflow runs",
    )

    def jobs(run: dict[str, JsonValue]) -> list[tuple[str, str, dict[str, JsonValue]]]:
        endpoint = f"repos/{repository}/actions/runs/{run.get('id')}/jobs?per_page=100&filter=all"
        event = str(run.get("event"))
        name = run.get("path") if event == "dynamic" else run.get("name")
        return [
            (str(name), event, job)
            for job in _api_items(root, endpoint, "jobs", "workflow jobs")
        ]

    with ThreadPoolExecutor(max_workers=8) as pool:
        return len(runs), [row for rows in pool.map(jobs, runs) for row in rows]


def ci_usage(root: Path, repository: str | None, days: int) -> int:
    """Print billed Actions minutes by workflow, event and job, and jobs run on both push and PR."""
    from shipping import git, origin_repository

    repository = repository or origin_repository(
        git(root, "remote", "get-url", "origin").strip()
    )
    count, rows = workflow_jobs(root, repository, days)
    billed: dict[tuple[str, str, str], list[tuple[int, float, int]]] = {}
    totals = {"billed": 0, "cancelled": 0, "failure": 0, "unstarted": 0, "running": 0}
    actual = 0.0
    for workflow, event, job in rows:
        if job.get("status") != "completed":
            totals["running"] += 1
            continue
        usage = billed_job(job)
        if usage is None:
            totals["unstarted"] += 1
            continue
        billed.setdefault((workflow, event, str(job.get("name"))), []).append(usage)
        totals["billed"] += usage[0]
        actual += usage[1] * usage[2]
        if job.get("conclusion") in {"cancelled", "failure"}:
            totals[str(job.get("conclusion"))] += usage[0]
    print(
        f"{repository}, last {days} days: {count} runs, {len(rows)} jobs. "
        f"Billed {totals['billed']} min ({totals['billed'] - actual:.0f} rounding up to whole minutes); "
        f"cancelled {totals['cancelled']}, failed {totals['failure']}; "
        f"{totals['unstarted']} jobs never got a runner and are not billed; "
        f"{totals['running']} jobs still running are not counted. "
        "Standard runners on public repositories are free."
    )
    print("billed  runs  median s  p90 s  workflow / event / job")
    for (workflow, event, name), usages in sorted(
        billed.items(), key=lambda item: -sum(usage[0] for usage in item[1])
    )[:25]:
        seconds = sorted(usage[1] * 60 for usage in usages)
        print(
            f"{sum(usage[0] for usage in usages):6}  {len(usages):4}  "
            f"{seconds[len(seconds) // 2]:8.0f}  {seconds[int(0.9 * (len(seconds) - 1))]:5.0f}  "
            f"{workflow} / {event} / {name}"
        )
    repeated = {
        (workflow, name)
        for workflow, event, name in billed
        if event == "push" and (workflow, "pull_request", name) in billed
    }
    for workflow, name in sorted(repeated):
        minutes = [
            sum(usage[0] for usage in billed[workflow, event, name])
            for event in ("push", "pull_request")
        ]
        print(
            f"Runs on push and pull_request: {workflow} / {name} "
            f"(push {minutes[0]} min, pull_request {minutes[1]} min)"
        )
    return 0


def require_ci_base(base: str | None) -> None:
    if (
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("GITHUB_EVENT_NAME")
        in {"push", "pull_request", "pull_request_target"}
        and (base is None or not base.strip())
    ):
        raise ValueError(
            "GitHub push/PR checks require --base with the comparison commit; "
            "pass github.event.pull_request.base.sha || github.event.before. "
            "Manual full checks may omit --base."
        )


def push_base(root: Path, base: str | None) -> str | None:
    """A force push names a base outside the new history; compare with HEAD's parent."""
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_EVENT_NAME") != "push"
        or not base
        or subprocess.run(
            ["git", "cat-file", "-e", base + "^{commit}"],
            cwd=root,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    ):
        return base
    parent = subprocess.run(
        ["git", "rev-parse", "--verify", "-q", "HEAD^"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if parent.returncode:
        return base
    print(
        f"Push base {base[:12]} is not in this history (force push); "
        "checking changes since HEAD's parent.",
        file=sys.stderr,
    )
    return parent.stdout.strip()


PR_TEXT = ".github/workflows/pr-text.yml"


def configure_github_ci(
    root: Path, source: Path, config: GateConfig, changes: dict[str, str]
) -> None:
    workflow = ".github/workflows/hard-eng.yml"
    configure_ci(root, source, config, changes)
    if workflow in changes:
        add_workflow_checks(config)
    if workflow not in changes and not (root / workflow).is_file():
        return
    # The cloud GitHub proxy adds a Claude footer to PR bodies; this workflow removes it.
    content = (source / PR_TEXT).read_text()
    if not (root / PR_TEXT).is_file() or (root / PR_TEXT).read_text() != content:
        changes[PR_TEXT] = content
