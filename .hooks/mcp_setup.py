"""Configure repository MCP servers without guessing service targets."""

import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from urllib.parse import urlparse

from gate_config import JsonObject, json_file, repository_files

APPWRITE_CLOUD_MCP_URL = "https://mcp.appwrite.io/"
RETIRED_INTEGRATIONS = re.compile(
    r"(?<![a-z0-9-])(?:context-mode|codebase-memory(?:-mcp)?)(?![a-z0-9-])",
    re.IGNORECASE,
)
APPWRITE_CLI_FILES = (
    ".agents/skills/appwrite-backend/references/appwrite-cli.md",
    ".agents/skills/appwrite-backend/scripts/appwrite-schema-guard.mjs",
    ".agents/skills/appwrite-backend/scripts/appwrite-schema-guard.test.mjs",
)


def retire_appwrite_cli(root: Path, source: Path, previous: Path | None) -> list[str]:
    from update import contained, scaffold_files

    retired = [
        name
        for name in APPWRITE_CLI_FILES
        if not (source / name).is_file()
        and ((root / name).exists() or (root / name).is_symlink())
    ]
    if not retired:
        return []
    owned = scaffold_files(source) | set(retired)
    owned |= scaffold_files(previous) if previous is not None else set()
    separator = r"""(?:[/\\]+|['"]\s*/\s*['"])"""
    reference = re.compile(
        r"\.(?:agents|claude)"
        + separator
        + separator.join(
            re.escape(part)
            for part in (
                "skills",
                "appwrite-backend",
                "scripts",
                "appwrite-schema-guard.mjs",
            )
        )
    )
    for path in repository_files(root) if APPWRITE_CLI_FILES[1] in retired else []:
        name = path.relative_to(root).as_posix()
        if (
            name in owned
            or not contained(root, path)
            or path.suffix
            not in {
                ".py",
                ".sh",
                ".bash",
                ".zsh",
                ".ps1",
                ".js",
                ".mjs",
                ".cjs",
                ".jsx",
                ".ts",
                ".tsx",
                ".dart",
                ".json",
                ".jsonc",
                ".yaml",
                ".yml",
                ".toml",
                ".ini",
                ".cfg",
            }
        ):
            continue
        if reference.search(path.read_text(errors="replace").replace(r"\.", ".")):
            raise ValueError(
                f"Appwrite CLI migration required: {name} references the retiring installed schema guard; "
                "move the required guard and its callers to project-owned scripts before setup."
            )
    deleted = []
    for name in retired:
        target = root / name
        if not target.exists() and not target.is_symlink():
            continue
        old = previous / name if previous is not None else None
        if (
            not contained(root, target)
            or target.is_symlink()
            or old is None
            or not old.is_file()
            or target.read_bytes() != old.read_bytes()
        ):
            raise ValueError(
                f"Preserve local Appwrite CLI file before setup: {name}; "
                "retirement requires unchanged bytes from the previous source."
            )
        deleted.append(name)
    return deleted


def repository_launcher(root: Path, command: object) -> str | None:
    """Return a direct, executable repository-local launcher command."""
    if not isinstance(command, str) or not command.startswith("./"):
        return None
    launcher = (root / command).resolve()
    if (
        not launcher.is_relative_to(root.resolve())
        or not launcher.is_file()
        or not os.access(launcher, os.X_OK)
    ):
        return None
    return command


def appwrite_cloud_url(value: object) -> bool:
    return value in (APPWRITE_CLOUD_MCP_URL, APPWRITE_CLOUD_MCP_URL.rstrip("/"))


def appwrite_cloud_endpoint(endpoint_value: str) -> bool:
    endpoint = urlparse(endpoint_value)
    if endpoint.scheme not in {"http", "https"} or not endpoint.hostname:
        raise ValueError("APPWRITE_ENDPOINT must be the deployed HTTP(S) endpoint")
    return endpoint.hostname == "cloud.appwrite.io" or endpoint.hostname.endswith(
        ".cloud.appwrite.io"
    )


def existing_servers(root: Path, service: str) -> list[JsonObject]:
    existing: list[JsonObject] = []
    for name in (
        ".mcp.json",
        ".github/mcp.json",
        ".codex/config.toml",
    ):
        path = root / name
        if not path.exists():
            continue
        content = path.read_text()
        parsed = (
            tomllib.loads(content) if name.endswith(".toml") else json.loads(content)
        )
        servers = parsed.get(
            "mcp_servers" if name.endswith(".toml") else "mcpServers", {}
        )
        if isinstance(servers, dict) and isinstance(servers.get(service), dict):
            existing.append(servers[service])
    return existing


def service_value(existing: list[JsonObject], variable: str) -> str | None:
    values = {os.environ[variable]} if os.environ.get(variable) else set()
    for server in existing:
        environment = server.get("env", {})
        if isinstance(environment, dict) and environment.get(variable):
            values.add(str(environment[variable]))
    if len(values) > 1:
        raise ValueError(
            f"Conflicting {variable} targets; resolve the intended service before setup"
        )
    return values.pop() if values else None


def appwrite_server(root: Path) -> JsonObject | None:
    """Reuse a known target; never default Cloud projects to API-key auth."""
    existing = existing_servers(root, "appwrite")
    endpoint_value = service_value(existing, "APPWRITE_ENDPOINT")
    launchers = {
        launcher
        for server in existing
        if (launcher := repository_launcher(root, server.get("command"))) is not None
    }
    if len(launchers) > 1:
        raise ValueError(
            "Conflicting Appwrite launcher definitions; resolve the intended service before setup"
        )
    configured_launcher = next(iter(launchers), None)
    configured_cloud = any(appwrite_cloud_url(server.get("url")) for server in existing)
    cloud = (
        appwrite_cloud_endpoint(endpoint_value)
        if endpoint_value is not None
        else configured_cloud
    )
    legacy = any(
        server.get("command") == "uvx" and server.get("args") == ["mcp-server-appwrite"]
        for server in existing
    )
    if cloud:
        if configured_launcher or legacy:
            raise ValueError(
                "Existing Appwrite local MCP conflicts with Cloud OAuth; preserve it and resolve the migration before setup"
            )
        return {"url": APPWRITE_CLOUD_MCP_URL}
    if configured_cloud:
        raise ValueError(
            "Existing Appwrite Cloud MCP conflicts with the self-hosted endpoint; resolve the migration before setup"
        )
    if legacy:
        raise ValueError(
            "Legacy Appwrite stdio entry needs the repository secret-loading launcher; preserve settings and migrate before setup"
        )
    if configured_launcher:
        if any(
            server.get("command") == configured_launcher
            and (server.get("args") or server.get("env"))
            for server in existing
        ):
            raise ValueError(
                "Reuse the Appwrite launcher with its existing secret owner; migrate arguments/env before sharing it across hosts"
            )
        return {"command": configured_launcher}
    launcher = repository_launcher(root, "./scripts/appwrite-mcp")
    if launcher:
        return {"command": launcher}
    if endpoint_value is None:
        print(
            "MCP setup pending: Appwrite needs the deployed endpoint. Reuse the project's existing configuration; "
            "ask only if unresolved, then supply APPWRITE_ENDPOINT. Follow "
            ".agents/skills/appwrite-backend/references/mcp-servers.md for Cloud OAuth or the self-hosted launcher.",
            file=sys.stderr,
        )
        return None
    print(
        "MCP setup pending: self-hosted Appwrite requires executable scripts/appwrite-mcp loading the existing gitignored env file; "
        "follow the canonical Appwrite MCP guidance before setup. Never put the API key in tracked MCP configuration.",
        file=sys.stderr,
    )
    return None


def sentry_server(root: Path) -> JsonObject | None:
    existing = existing_servers(root, "sentry")
    host = service_value(existing, "SENTRY_HOST")
    cloud = host is not None and (host == "sentry.io" or host.endswith(".sentry.io"))
    targets = {str(server.get("url") or server.get("command")) for server in existing}
    if os.environ.get("SENTRY_MCP_URL"):
        targets.add(os.environ["SENTRY_MCP_URL"])
    if len(targets) > 1:
        raise ValueError(
            "Conflicting Sentry MCP targets; resolve the intended service before setup"
        )
    if targets:
        target = targets.pop()
        parsed = urlparse(target)
        if (
            parsed.scheme == "https"
            and parsed.netloc == "mcp.sentry.dev"
            and (parsed.path == "/mcp" or parsed.path.startswith("/mcp/"))
        ):
            if host and not cloud:
                raise ValueError(
                    "Existing Sentry Cloud MCP conflicts with self-hosting; resolve the migration before setup"
                )
            return {"url": target}
        launcher = repository_launcher(root, target)
        if launcher:
            if any(server.get("args") or server.get("env") for server in existing):
                raise ValueError(
                    "Reuse the Sentry launcher with its existing secret owner; migrate arguments/env before sharing it across hosts"
                )
            return {"command": launcher}
        print(
            "MCP setup pending: existing Sentry MCP target is not a supported hosted URL or direct repository-local launcher; "
            "preserve it and configure missing hosts manually.",
            file=sys.stderr,
        )
        return None
    launcher = repository_launcher(root, "./scripts/sentry-mcp")
    if not cloud and launcher:
        return {"command": launcher}
    print(
        "MCP setup pending: Sentry needs the existing service target: SENTRY_MCP_URL for SaaS (prefer the intended organization/project scope), "
        "or a repository scripts/sentry-mcp launcher loading self-hosted credentials from the existing gitignored env file. "
        "Reuse existing project choices; ask only if unresolved.",
        file=sys.stderr,
    )
    return None


def marionette_server(root: Path) -> JsonObject | None:
    """Register for any Flutter app; pin to the locked package when present."""
    import yaml

    from gate_config import nonproduction_source, repository_files

    for path in repository_files(root):
        relative = path.relative_to(root)
        if path.name != "pubspec.yaml" or nonproduction_source(relative):
            continue
        if {".agents", ".claude", ".hooks"} & set(relative.parts):
            continue
        manifest = yaml.safe_load(path.read_text())
        dependencies = {
            **(manifest.get("dependencies") or {}),
            **(manifest.get("dev_dependencies") or {}),
        }
        if not any(
            isinstance(value, dict) and value.get("sdk") == "flutter"
            for value in dependencies.values()
        ):
            continue
        lock = path.parent / "pubspec.lock"
        locked = (
            yaml.safe_load(lock.read_text())
            .get("packages", {})
            .get("marionette_flutter", {})
            if lock.is_file()
            else {}
        )
        return {
            "command": "dart",
            "args": ["run", f"marionette_mcp@{locked.get('version', '')}"],
        }
    return None


def detected_servers(root: Path) -> dict[str, JsonObject]:
    from agent_hooks import integrated_services

    optional: dict[str, JsonObject | None] = {
        "Dart": {"command": "dart", "args": ["mcp-server"]},
        "Marionette": marionette_server(root),
    }
    services = [*integrated_services(root), "Marionette"]
    if any(
        server.get("command") == "dart"
        and server.get("args") == ["run", "dart_mcp_server@"]
        for server in existing_servers(root, "dart")
    ):
        raise ValueError(
            "Legacy Dart MCP entry: replace only its package command with dart mcp-server, preserving custom settings, then rerun setup"
        )
    if "Appwrite" in services:
        optional["Appwrite"] = appwrite_server(root)
    if "Sentry" in services:
        optional["Sentry"] = sentry_server(root)
    return {
        service.lower(): settings
        for service in services
        if (settings := optional[service]) is not None
    }


def retired_integration(value: object) -> bool:
    return isinstance(value, str) and RETIRED_INTEGRATIONS.search(value) is not None


def retired_server(name: str, settings: object) -> bool:
    if not isinstance(settings, dict):
        return retired_integration(name)
    command = str(settings.get("command", ""))
    args = settings.get("args")
    arguments: list[object] = args if isinstance(args, list) else []
    if Path(command).name in {"sh", "bash"} and arguments[:1] == ["-c"]:
        launcher = arguments[1] if len(arguments) == 2 else ""
        expected = 'exec python3 "$(git rev-parse --show-toplevel)/.hooks/codebase-memory-mcp.py"'
        if launcher == expected:
            return True
        if retired_integration(launcher):
            raise ValueError(
                "Retired MCP launcher contains custom shell commands; preserve unrelated commands before removing the retired integration."
            )
    if retired_integration(name) or retired_integration(command):
        return True
    if Path(command).name in {"pnpm", "npm"} and arguments[:1] in (["dlx"], ["exec"]):
        arguments = arguments[1:]
    elif Path(command).name in {"node", "python", "python3"}:
        return bool(arguments) and retired_integration(arguments[0])
    elif Path(command).name not in {"npx", "bunx", "uvx"}:
        return False
    first = next(
        (
            argument
            for argument in arguments
            if isinstance(argument, str) and not argument.startswith("-")
        ),
        "",
    )
    return retired_integration(first)


def retire_claude_integrations(
    settings: JsonObject, aliases: set[str] | None = None
) -> None:
    for key in ("enabledPlugins", "extraKnownMarketplaces"):
        entries = settings.get(key)
        if isinstance(entries, dict):
            kept = {
                name: value
                for name, value in entries.items()
                if not retired_integration(name)
                and not retired_integration(json.dumps(value))
            }
            settings[key] = kept
            if not kept:
                del settings[key]
    for key in ("enabledMcpjsonServers", "disabledMcpjsonServers"):
        entries = settings.get(key)
        if isinstance(entries, list):
            kept = [
                name
                for name in entries
                if not retired_integration(name) and name not in (aliases or set())
            ]
            settings[key] = kept
            if not kept:
                del settings[key]

    permissions = settings.get("permissions")
    if isinstance(permissions, dict):
        for key in ("allow", "deny", "ask"):
            entries = permissions.get(key)
            if isinstance(entries, list):
                permissions[key] = [
                    item for item in entries if not retired_integration(item)
                ]


def retired_settings(settings: Path) -> str | None:
    from agent_hooks import remove_old_generation

    if not settings.is_file() or settings.is_symlink() or settings.parent.is_symlink():
        return None
    current = json.loads(settings.read_text())
    before = json.dumps(current)
    retire_claude_integrations(current)
    if isinstance(hooks := current.get("hooks"), dict):
        remove_old_generation(hooks)
        if not hooks:
            del current["hooks"]
    if current.get("outputStyle") == "Plain English":
        del current["outputStyle"]
    return (
        None if json.dumps(current) == before else json.dumps(current, indent=2) + "\n"
    )


def codex_table(server: str, settings: JsonObject) -> str:
    return f'\n[mcp_servers."{server}"]\n' + "".join(
        f"{key} = {json.dumps(value)}\n" for key, value in settings.items()
    )


def retire_codex_servers(config: str, removed: set[str]) -> str:
    expected = tomllib.loads(config)
    for name in removed:
        del expected["mcp_servers"][name]
    headers = list(re.finditer(r"(?m)^\[[^\n]+\][ \t]*(?:#.*)?$", config))
    for index in reversed(range(len(headers))):
        header = headers[index]
        if any(
            re.fullmatch(
                rf"\[mcp_servers\.(?:{re.escape(name)}|\"{re.escape(name)}\"|'{re.escape(name)}')(?:\.[^\]]+)?\][ \t]*(?:#.*)?",
                header.group(),
            )
            for name in removed
        ):
            end = (
                headers[index + 1].start() if index + 1 < len(headers) else len(config)
            )
            config = config[: header.start()] + config[end:]
    actual = tomllib.loads(config)
    for parsed in (expected, actual):
        if parsed.get("mcp_servers") == {}:
            del parsed["mcp_servers"]
    if actual != expected:
        raise ValueError(
            "Retired MCP definitions use unsupported TOML formatting; remove only their tables before setup."
        )
    return config


def approve_claude_servers(
    root: Path, changes: dict[str, str], servers: list[str]
) -> None:
    name = ".claude/settings.json"
    text = changes.get(name) or (
        (root / name).read_text() if (root / name).is_file() else "{}"
    )
    settings: JsonObject = json.loads(text)
    approved = settings.setdefault("enabledMcpjsonServers", [])
    if not isinstance(approved, list):
        raise TypeError(
            f"Conflicting setting enabledMcpjsonServers in {name}; expected a list"
        )
    missing = [server for server in servers if server not in approved]
    if missing:
        approved.extend(missing)
        changes[name] = json_file(root, settings)


def retired_integration_files(root: Path) -> list[str]:
    from update import contained

    retired: list[str] = []
    retired += subprocess.check_output(
        ["git", "ls-files", "--", ".context-mode", ".codebase-memory"],
        cwd=root,
        text=True,
    ).splitlines()
    wrapper = root / ".hooks/codebase-memory-mcp.py"
    if wrapper.exists() or wrapper.is_symlink():
        if wrapper.is_symlink() or not contained(root, wrapper):
            raise ValueError(
                "Preserve the linked retired Codebase Memory launcher before setup"
            )
        retired.append(wrapper.relative_to(root).as_posix())
    return retired


def configure_mcp(root: Path, changes: dict[str, str]) -> list[str]:
    from update import contained

    detected = detected_servers(root)
    target = root / ".mcp.json"
    current: JsonObject = json.loads(target.read_text()) if target.exists() else {}
    before = json.dumps(current)
    existing = current.setdefault("mcpServers", {})
    if not isinstance(existing, dict):
        raise TypeError("Conflicting MCP servers in .mcp.json; expected an object")
    removed = {
        name for name, settings in existing.items() if retired_server(name, settings)
    }
    for name in removed:
        del existing[name]
    for plugin in sorted(detected.keys() - existing.keys()):
        settings = detected[plugin]
        existing[plugin] = (
            {"type": "http", **settings} if "url" in settings else settings
        )
    retired = retired_integration_files(root)
    if json.dumps(current) != before:
        if current == {"mcpServers": {}}:
            if target.exists():
                retired.append(".mcp.json")
        else:
            changes[".mcp.json"] = json_file(root, current)
    settings_name = ".claude/settings.json"
    text = changes.get(settings_name) or (
        (root / settings_name).read_text() if (root / settings_name).is_file() else "{}"
    )
    settings = json.loads(text)
    retire_claude_integrations(settings, removed)
    if settings != json.loads(text):
        changes[settings_name] = json_file(root, settings)
    approve_claude_servers(root, changes, sorted(detected.keys() & existing.keys()))
    codex_retired, codex_config = configure_codex_mcp(root, changes, detected)
    retired += codex_retired + retire_copilot_mcp(root, existing, codex_config)
    if any(not contained(root, root / name) for name in retired):
        raise ValueError(
            "Retired files are reached through a linked directory; preserve the shared targets before setup"
        )
    return retired


def configure_codex_mcp(
    root: Path, changes: dict[str, str], detected: dict[str, JsonObject]
) -> tuple[list[str], str]:
    retired: list[str] = []
    target = root / ".codex/config.toml"
    original = target.read_text() if target.exists() else ""
    configured = tomllib.loads(original).get("mcp_servers", {})
    removed = {
        name for name, settings in configured.items() if retired_server(name, settings)
    }
    codex_config = retire_codex_servers(original, removed)
    for plugin, settings in detected.items():
        if plugin not in configured:
            codex_config += codex_table(plugin, settings)
    if codex_config != original:
        if not codex_config.strip():
            retired.append(".codex/config.toml")
        else:
            changes[".codex/config.toml"] = codex_config
    return retired, codex_config


def retire_copilot_mcp(
    root: Path, claude_servers: JsonObject, codex_config: str
) -> list[str]:
    from update import contained

    name = ".github/mcp.json"
    target = root / name
    if not target.exists():
        return []
    current: JsonObject = json.loads(target.read_text())
    servers = current.get("mcpServers")
    if not isinstance(servers, dict):
        raise TypeError(f"Conflicting MCP servers in {name}; expected an object")
    supported = tomllib.loads(codex_config).get("mcp_servers", {})
    for server, settings in servers.items():
        if not isinstance(settings, dict):
            raise TypeError(
                f"Conflicting MCP server {server} in {name}; expected an object"
            )
        standard = retired_server(server, settings)
        native = (
            {key: value for key, value in settings.items() if key != "type"}
            if settings.get("type") == "http"
            else settings
        )
        if (
            not standard
            and settings != claude_servers.get(server)
            and native != supported.get(server)
        ):
            raise ValueError(
                f"Harness migration required: preserve the {server} MCP definition from {name} in Claude or Codex, then remove the retired configuration before setup."
            )
    if (
        current.keys() > {"mcpServers"}
        or target.is_symlink()
        or not contained(root, target)
    ):
        raise ValueError(
            f"Preserve custom or linked retired harness config before setup: {name}"
        )
    return [name]
