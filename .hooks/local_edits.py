import subprocess
import tempfile
from pathlib import Path

MERGED_SKILL = ".agents/skills/trello-coordinator/"


def merge_local_edits(name: str, target: Path, old: Path, content: str) -> str:
    with tempfile.TemporaryDirectory(prefix="hard-eng-merge-") as folder:
        new = Path(folder) / "new"
        new.write_text(content)
        merged = subprocess.run(
            ["git", "merge-file", "-p", str(target), str(old), str(new)],
            capture_output=True,
            text=True,
            check=False,
        )
    if merged.returncode != 0:
        raise ValueError(
            f"{name} has local edits on the same lines as this update; "
            "merge them by hand, commit, then update again"
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
