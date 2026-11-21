"""A gate that runs a judged tool runs it directly: a launcher, the tool, then arguments; every other form is refused."""

import os
import re
import shlex
from pathlib import Path, PurePosixPath

ASSIGNING_SUFFIXES = (".yml", ".yaml", ".sh", ".bash", ".toml", ".json", ".mk")
ASSIGNING_NAMES = {
    "Makefile",
    "makefile",
    "GNUmakefile",
    "Dockerfile",
    "justfile",
    ".envrc",
    ".env",
}


def assigns_variables(name: str) -> bool:
    """A workflow, script or config file; prose and notes can name a variable without setting it."""
    return (
        name.endswith(ASSIGNING_SUFFIXES) or PurePosixPath(name).name in ASSIGNING_NAMES
    )


JUDGED_TOOLS = {"ruff", "fallow", "gitleaks", "clippy", "cargo-clippy"}
OPERATORS = {"&&", "||", ";", "|", "&", "!", ">", ">>", "<", "2>", "(", ")"}
MANAGERS = {"npm", "pnpm", "yarn", "bun"}
PACKAGE_COMMANDS = frozenset(
    {
        "run",
        "run-script",
        "test",
        "x",
        "install",
        "i",
        "add",
        "a",
        "remove",
        "rm",
        "update",
        "outdated",
        "pm",
        "init",
        "create",
        "build",
        "upgrade",
        "link",
        "unlink",
        "publish",
        "pack",
        "audit",
        "why",
        "repl",
        "exec",
        "patch",
        "info",
        "dlx",
        "list",
        "ls",
        "cache",
        "config",
        "dedupe",
        "prune",
        "rebuild",
        "store",
        "up",
        "workspace",
        "workspaces",
        "version",
        "set",
        "node",
        "bun",
        "help",
    }
)
SHELL_CHARACTER = re.compile(r"[\s;&|$`]")
TOOL_PART = re.compile(r"[\w@./+-]+")
BREAK_OR_TAB = re.compile(r"[^\S ]")
METAS = re.compile(r"[;&|<>$`]")
TOOL_WORD = re.compile(r"(ruff|fallow|gitleaks)(@[\w.=<>~+-]+)?")
UV_FLAGS = {"--no-sync", "--frozen", "--locked"}
ALLOWED_FORMS = (
    "ruff check <paths>",
    "uvx ruff@<pin> check <paths>",
    *(f"uv run {flag} ruff check <paths>" for flag in sorted(UV_FLAGS)),
    "bun x fallow@<pin> <arguments>",
    "bunx fallow@<pin> <arguments>",
    "cargo clippy <arguments>",
    "gitleaks <arguments>",
)
DIRECT_FORMS = (
    f"write {', '.join(f'`{form}`' for form in ALLOWED_FORMS)}, "
    "or `bun run <script>` where the script is exactly one such command"
)


def flagged_built_in(arguments: list[str]) -> bool:
    """Flags then a package-manager command that runs no script (`bun --env-file=x test`): no script name is hidden."""
    rest = [word for word in arguments[1:] if not word.startswith("-")]
    return bool(rest) and rest[0] in PACKAGE_COMMANDS - {"run", "run-script", "x"}


def refusal(reason: str) -> ValueError:
    return ValueError(
        "HE-NO-SWITCH-OFF: A gate that runs ruff, cargo, clippy, fallow or gitleaks must run it directly, "
        f"so the checks can read its arguments: {DIRECT_FORMS}; {reason}"
    )


def tool_name(word: str) -> str:
    return PurePosixPath(word).name.split("@", 1)[0]


def mentions(words: list[str]) -> bool:
    """A word that is a judged tool, or a string that holds one, as in `sh -c 'ruff check'`; `cargo` alone is not judged, only its `clippy`."""
    for word in words:
        if tool_name(word) in JUDGED_TOOLS:
            return True
        if SHELL_CHARACTER.search(word) and any(
            tool_name(part) in JUDGED_TOOLS for part in TOOL_PART.findall(word)
        ):
            return True
    return False


def expanded(command: list[str], directory: Path) -> list[str]:
    """A package script run as its words; a script with a `pre` or `post` script runs two commands, so it is refused."""
    if tool_name(command[0]) not in MANAGERS:
        return command
    from project_setup import package_script_invocation, read_project_file

    try:
        words, where = package_script_invocation(command, directory)
    except (ValueError, TypeError, OSError):
        return command
    if words == command:
        return command
    if tool_name(command[0]) != "bun" and mentions(words):
        raise refusal(
            f"{command[0]} runs the script through a shell that a project file can change; write `bun run <script>`"
        )
    named = [word for word in command[1:] if not word.startswith("-")]
    name = (
        named[1] if named[0] in {"run", "run-script"} and len(named) > 1 else named[0]
    )
    scripts = read_project_file(where / "package.json").get("scripts", {})
    if mentions(words):
        if BREAK_OR_TAB.search(str(scripts.get(name, ""))):
            raise refusal(
                f"the script {name} holds a line break or tab, which ends a shell command like `;` does"
            )
        if {f"pre{name}", f"post{name}"} & set(scripts):
            raise refusal(
                f"the script {name} has a pre or post script, so two commands run"
            )
        if tool_name((shlex.split(str(scripts.get(name, ""))) or [""])[0]) in MANAGERS:
            raise refusal(
                f"the script {name} runs another script, so write the tool command in it"
            )
    return words


def after_launcher(words: list[str]) -> list[str]:
    """The words after a template launcher, or none when the words start with another one."""
    if words[0] == "uvx":
        return words[1:]
    if words[0] == "bunx":
        return words[1:]
    if words[:2] == ["bun", "x"]:
        return words[2:]
    if words[:2] == ["uv", "run"]:
        rest = words[2:]
        while rest and rest[0] in UV_FLAGS:
            rest = rest[1:]
        return rest
    return []


def launched(words: list[str]) -> tuple[list[str], list[str]] | None:
    """The launcher words up to and including the tool as written, and the words from the tool on, when a template launcher starts them."""
    if not words:
        return None
    if words[0] in {"ruff", "fallow", "gitleaks"}:
        return words[:1], words
    if words[0] == "cargo":
        return (words[:1], words) if "clippy" in words[:3] else None
    rest = after_launcher(words)
    found = TOOL_WORD.fullmatch(rest[0]) if rest else None
    if found is None:
        return None
    bun = words[0] == "bunx" or words[:2] == ["bun", "x"]
    if bun and not (found[1] == "fallow" and found[2]):
        return None
    return [*words[: len(words) - len(rest)], rest[0]], [found[1], *rest[1:]]


def shadowed(tool: str, directory: Path) -> bool:
    """A project script or entry point named like the tool: `uv run <tool>` would run it instead."""
    import tomllib

    for folder in [directory.resolve(), *directory.resolve().parents]:
        try:
            project = tomllib.loads((folder / "pyproject.toml").read_text())
        except (OSError, tomllib.TOMLDecodeError):
            continue
        scripts = [
            project.get("project", {}).get("scripts", {}),
            project.get("tool", {}).get("poetry", {}).get("scripts", {}),
        ]
        if any(tool in table for table in scripts if isinstance(table, dict)):
            return True
        if (folder / ".git").exists():
            break
    return False


def bin_shadow(tool: str, directory: Path) -> str | None:
    """A file in node_modules/.bin named like the tool that is not the tool's own package: bun puts that folder first on the path."""
    owners = (f"/node_modules/{tool}/",)
    for folder in [directory.resolve(), *directory.resolve().parents]:
        path = folder / "node_modules/.bin" / tool
        if os.path.lexists(path) and not any(
            owner in os.path.realpath(path) for owner in owners
        ):
            return os.path.relpath(path, directory)
        if (folder / ".git").exists():
            break
    return None


def launch(command: list[str], directory: Path) -> tuple[list[str], list[str]] | None:
    """The launcher and the words from the judged tool on, or none when no judged tool runs; any other form of a judged tool is refused."""
    words = expanded(command, directory)
    if not mentions(words) and not mentions(command):
        return None
    found = launched(words)
    if found is None:
        raise refusal(f"the gate holds {' '.join(command)}")
    launcher, argv = found
    if argv[0] == "ruff" and words != command:
        raise refusal(
            "ruff in a package script runs whatever package manager file is named `ruff`: run it as `ruff check <paths>` or `uvx ruff@<pin> check <paths>`"
        )
    if launcher[:2] == ["uv", "run"] and shadowed(argv[0], directory):
        raise refusal(
            f"a project script named {argv[0]} shadows the tool under `uv run`: rename the script or use `uvx {argv[0]}@<pin>`"
        )
    local = (
        bin_shadow(argv[0], directory)
        if argv[0] != "fallow"
        and (words != command or launcher[0] == "bunx" or launcher[:2] == ["bun", "x"])
        else None
    )
    if local:
        raise refusal(
            f"{local} is a file named {argv[0]} that bun puts first on the path, so it runs in place of the tool: remove it, or install the tool's own package"
        )
    bad = [
        word
        for word in argv
        if word in OPERATORS or "$(" in word or "`" in word or METAS.search(word)
    ]
    if bad:
        raise refusal(f"the gate holds {', '.join(bad)}")
    return launcher, argv


def direct(command: list[str], directory: Path) -> list[str] | None:
    """The words from the judged tool on, or none when no judged tool runs."""
    found = launch(command, directory)
    return found[1] if found else None
