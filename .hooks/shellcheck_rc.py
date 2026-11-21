"""A `.shellcheckrc` that turns a ShellCheck rule off hides findings from every shell gate."""

DISABLING = ("disable",)


def rc_hits(name: str, text: str) -> list[str]:
    return [
        f"{name}:{number} sets {word!r}, which turns ShellCheck rules off for every script near it; fix the scripts instead"
        for number, line in enumerate(text.splitlines(), 1)
        if not line.lstrip().startswith("#")
        for word in line.split()
        if word.partition("=")[0] in DISABLING
    ]


def ignoring_settings(command: list[str]) -> list[str]:
    """A settings file with `disable=` makes the gate pass over findings, so the gate reads none."""
    if "shellcheck" not in command or "--norc" in command:
        return command
    tool = command.index("shellcheck")
    return [*command[: tool + 1], "--norc", *command[tool + 1 :]]
