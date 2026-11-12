"""Why a retired family command cannot run."""

from __future__ import annotations

import shutil
from pathlib import Path

INTERPRETERS = {"python", "python3", "node", "bash", "sh", "ruby", "perl"}
# Options whose operand is inline code or a module, then options that take a value.
INLINE = {"-c", "-m", "-e", "-p", "--eval", "--print"}
VALUED = {"-W", "-X", "-r", "--require", "--import", "--loader", "-o"}


def script_operand(arguments: list[str]) -> str | None:
    """Return the script an interpreter runs, or None for inline code or modules."""
    options = iter(arguments[1:])
    for argument in options:
        if argument in INLINE:
            return None
        if argument == "--" or not argument.startswith("-"):
            return next(options, None) if argument == "--" else argument
        if argument in VALUED:
            next(options, None)
    return None


def legacy_command_problem(root: Path, arguments: list[str]) -> str | None:
    """Name why a retired family command cannot run, or None when it can."""
    if not (shutil.which(arguments[0]) or (root / arguments[0]).is_file()):
        return "program not found"
    interpreter = Path(arguments[0]).name.rstrip("0123456789.") in INTERPRETERS
    script = script_operand(arguments) if interpreter else None
    if script is not None and not (root / script).is_file():
        return "script not found"
    return None
