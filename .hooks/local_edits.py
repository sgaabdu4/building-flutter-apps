import subprocess
import tempfile
from pathlib import Path

MERGED_SKILL = ".agents/skills/trello-coordinator/"
SHOWN_LINES = 40
CONFLICT_HEADING = "has local edits on the same lines as this update."


def conflict_blocks(merged: str) -> str:
    """The conflict blocks of a merge, local lines first, cut after a fixed number of lines."""
    shown: list[str] = []
    inside = False
    for line in merged.splitlines():
        inside = inside or line.startswith("<<<<<<< ")
        if inside:
            shown.append(line)
        inside = inside and not line.startswith(">>>>>>> ")
    if len(shown) > SHOWN_LINES:
        shown = [*shown[:SHOWN_LINES], "..."]
    return "\n".join(shown)


def refusal_reason(stderr: str) -> str:
    """The last lines of a refusal; a conflict message keeps its blocks, one per line."""
    lines = stderr.strip().splitlines()
    heading = next(
        (n for n, line in enumerate(lines) if CONFLICT_HEADING in line), None
    )
    if heading is None:
        return " | ".join(lines[-5:])
    return "\n".join(lines[heading:])


def merge_local_edits(name: str, target: Path, old: Path, content: str) -> str:
    with tempfile.TemporaryDirectory(prefix="hard-eng-merge-") as folder:
        new = Path(folder) / "new"
        new.write_text(content)
        merged = subprocess.run(
            [
                "git",
                *("-c", "merge.conflictStyle=merge"),
                "merge-file",
                "-p",
                *("-L", "local lines", "-L", "installed lines", "-L", "update lines"),
                str(target),
                str(old),
                str(new),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    if merged.returncode != 0:
        raise ValueError(
            f"{name} {CONFLICT_HEADING}\n"
            "Each block below shows the local lines, then the update's lines:\n"
            f"{conflict_blocks(merged.stdout)}\n"
            f"In {name}, put the update's lines in place of those local lines. "
            "To keep your own change, add it again after this update is in, on "
            "lines that it does not change"
        )
    if name.endswith(".py"):
        try:
            compile(merged.stdout, name, "exec")
        except SyntaxError as error:
            raise ValueError(
                f"{name} does not compile after adding the update to local edits: "
                f"{error.msg}"
            ) from error
    return merged.stdout
