"""Adapt existing CI and generate only explicitly configured new workflows."""

import json
import math
import re
import sys
from pathlib import Path

from gate_config import GateConfig, Group
from project_setup import dependency_command

MAINTENANCE_EVENTS = {"schedule", "workflow_dispatch"}
OLD_TRIGGERS = (
    "on:\n  push:\n    branches-ignore:\n      - 'feature/**'\n  pull_request:\n"
)
OLD_BASE = "${{ github.event.pull_request.base.sha || github.event.before }}"
NEW_BASE = "${{ inputs.base_sha || github.event.pull_request.base.sha || github.event.before }}"
BOOTSTRAP_TOOLS = ["uv@latest", "python@3.12", "node@latest"]


def pnpm_specification(root: Path, package: Group, groups: list[Group]) -> str:
    """Reuse the pin of an established workspace dependency-install owner."""
    directory = root / package["path"]
    manifest = json.loads((directory / "package.json").read_text())
    if (
        "packageManager" not in manifest
        and not (directory / "pnpm-lock.yaml").exists()
        and not any(gate.get("role") == "lockfiles" for gate in package["checks"])
    ):
        owners = sorted(
            (
                root / group["path"]
                for group in groups
                if root / group["path"] in directory.parents
                and any(
                    gate.get("role") == "lockfiles"
                    and gate["command"] == ["pnpm", "install", "--frozen-lockfile"]
                    for gate in group["checks"]
                )
            ),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        if owners and (owners[0] / "package.json").is_file():
            manifest = json.loads((owners[0] / "package.json").read_text())
    declared = manifest.get("packageManager", "pnpm@latest")
    if (
        not isinstance(declared, str)
        or re.fullmatch(
            r"pnpm@(?:latest|\d+(?:\.\d+){0,2}(?:-[\w.-]+)?)(?:\+[\w.-]+)?", declared
        )
        is None
    ):
        raise ValueError("CI requires a valid pnpm packageManager version")
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
            tools.append(pnpm_specification(root, group, groups))
    if "flutter@latest" in tools:
        tools = [tool for tool in tools if tool != "dart@latest"]
    return list(dict.fromkeys(tools))


def workflow_triggers(source: Path, base: str) -> tuple[str, str]:
    """The template trigger block and its copy for the project's base branch."""
    template = (source / ".github/workflows/hard-eng.yml").read_text()
    block = template[template.index("on:\n") : template.index("\n\npermissions:") + 1]
    return block, block.replace("      - main\n", f"      - {base}\n", 1)


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
        r"(?m)^    timeout-minutes: \d+$",
        f"    timeout-minutes: {math.ceil(policy['ci_seconds'] / 60)}",
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
        (
            "pnpm/setup",
            "c9883cc79df532ad1a7b81bf9ab944ceb090d65c",
            "703c52620218391530e48b9e8870d5c0082e1b9b",
            "v2.0.0",
            "v2.1.0",
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


def migrate_pnpm_bootstrap(root: Path, content: str) -> str:
    manifest = root / "package.json"
    if not manifest.is_file():
        return content
    package = json.loads(manifest.read_text())
    declared = package.get("packageManager", "")
    engines = package.get("devEngines", {})
    manager = engines.get("packageManager") if isinstance(engines, dict) else None
    if not (
        isinstance(declared, str)
        and declared.startswith("pnpm@")
        or isinstance(manager, dict)
        and manager.get("name") == "pnpm"
        and manager.get("version")
    ):
        return content
    return re.sub(
        r"(?m)^(      - uses: pnpm/setup@[^\n]+\n        with:\n)"
        r"          version: latest\n"
        r"(          runtime: [^\n]+\n          install: false\n)(?=      - |\Z)",
        r"\1\2",
        content,
    )


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
    cache = "      - name: Cache native tool downloads\n"
    checks = "      - name: Run required checks\n"
    if "id: impact" in content:
        return content
    if any(
        content.count(step) != 1 or step + "        if:" in content
        for step in (cache, checks)
    ):
        print(
            "Docs-only CI steps not added: .github/workflows/hard-eng.yml is customised. "
            "Copy the `impact` and docs-only secret scan steps from the Hard Eng template "
            "to skip tool setup when only docs change.",
            file=sys.stderr,
        )
        return content
    impact = template[
        template.index("      - name: Find whether") : template.index(cache)
    ]
    scan = template[
        template.index("      - name: Run the secret") : template.index(checks)
    ]
    condition = "        if: steps.impact.outputs.docs_only != 'true'\n"
    content = content.replace(cache, impact + cache + condition)
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
        manager, _, _ = dependency_command(directory, language)
        if manager in {"dart", "flutter", "pnpm", "yarn", "bun", "poetry"}:
            specification = (
                pnpm_specification(root, package, groups)
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
    required = workflow_tools(root, config)[3:]
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
        r"(?m)^(?P<indent> +)(?P<launcher>pnpm dlx (?:\S+ )+?mise --no-config) "
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
        r"(?m)^          (?P<launcher>pnpm dlx (?:\S+ )+?mise --no-config) "
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
    redundant_latest = "pnpm@latest" not in required and any(
        tool.startswith("pnpm@") and tool in required for tool in match["tools"].split()
    )
    if any(
        tool.split("@", 1)[0] in known
        and tool not in required
        and not (tool == "pnpm@latest" and redundant_latest)
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
    """Keep installed tools and store data without their duplicate download caches."""
    template = (source / ".github/workflows/hard-eng.yml").read_text()
    old = '        run: python3 .hooks/hard-eng.py impact --base "$BASE_SHA" >> "$GITHUB_OUTPUT" || echo docs_only=false >> "$GITHUB_OUTPUT"\n'
    start = template.index("        run: |\n", template.index("id: impact"))
    end = template.index("      - name: Cache native", start)
    content = content.replace(old, template[start:end], 1)
    pattern = re.compile(
        r"(?m)^          path: \$\{\{ runner\.temp \}\}/hard-eng-tools\n"
        r"          key: \$\{\{ runner\.os \}\}-\$\{\{ runner\.arch \}\}-hard-eng-tools-[^\n]+\n"
        r"          restore-keys: \$\{\{ runner\.os \}\}-\$\{\{ runner\.arch \}\}-hard-eng-tools-\n"
    )
    start = template.index("          path: |\n")
    end = template.index("      - uses:", start)
    return pattern.sub(lambda _match: template[start:end], content, count=1)


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


def integrated(workflows: list[Path]) -> bool:
    """Existing CI that already runs the check needs no integration reminder."""
    import yaml

    found, complete = False, True
    for path in workflows:
        try:
            workflow = yaml.safe_load(path.read_text())
            if runs_hard_eng_check(workflow):
                found = True
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
        migrated = migrate_workflow_tools(migrate_workflow_pins(original))
        migrated = migrate_workflow_sdks(root, config, migrated)
        migrated = migrate_workflow_triggers(
            root, source, migrate_docs_path(source, migrated)
        )
        migrated = migrate_affected_tools(root, source, config, migrated)
        migrated = migrate_pnpm_bootstrap(root, migrated)
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
            " || 'uv@latest python@3.12 node@latest'",
            " || '" + " ".join(tools) + "'",
            1,
        )
        .replace(block, triggers, 1)
    )
    changes[name] = migrate_pnpm_bootstrap(root, workflow_budget(root, changes[name]))
