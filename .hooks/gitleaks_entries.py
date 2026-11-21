"""Judge the root .gitleaksignore: an entry passes only when a scan run now finds it and its finding is in the past or in generated output."""

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from challenge import known
from generated_marks import generated_sources
from gitleaks_scan import scan_environment

COMMIT_ENTRY = re.compile(r"([0-9a-f]{40}|[0-9a-f]{64}):(.+):([\w.-]+):\d+")
CURRENT_ENTRY = re.compile(r"(.+):([\w.-]+):\d+")


def entry_lines(root: Path) -> list[tuple[int, str]]:
    path = root / ".gitleaksignore"
    if not path.is_file() or path.is_symlink():
        return []
    return [
        (number, line.strip())
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1)
        if line.strip() and not line.strip().startswith("#")
    ]


def scan(
    command: list[str], cwd: Path, report: Path, config: list[str], timeout: float
) -> list[dict[str, str]]:
    """Run Gitleaks where no .gitleaksignore reaches it; the report keeps no secret value."""
    done = subprocess.run(
        [
            "gitleaks",
            *command,
            *config,
            "--redact=100",
            "--no-banner",
            "--ignore-gitleaks-allow",
            "--report-format",
            "json",
            "--report-path",
            str(report),
        ],
        cwd=cwd,
        env=scan_environment(),
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if done.returncode not in (0, 1):
        raise RuntimeError(
            f"gitleaks failed while judging .gitleaksignore: {done.stderr.decode(errors='replace')}"
        )
    return json.loads(report.read_text() or "[]") if report.is_file() else []


def past_findings(
    root: Path, work: Path, commits: list[str], config: list[str], timeout: float
) -> set[str]:
    """Fingerprints of the named commits, scanned in a bare shared clone that holds no ignore file."""
    clone = work / "clone"
    subprocess.run(
        ["git", "clone", "-q", "--bare", "--shared", str(root), str(clone)],
        check=True,
        capture_output=True,
    )
    found = scan(
        ["git", str(clone), f"--log-opts=--no-walk {' '.join(commits)}"],
        work,
        work / "history.json",
        config,
        timeout,
    )
    return {item["Fingerprint"] for item in found}


def named_path(entry: str) -> str:
    """The path that an entry names, with `/` as the separator as Gitleaks reads it, or an empty string."""
    if commit := COMMIT_ENTRY.fullmatch(entry):
        return commit[2].replace("\\", "/")
    if current := CURRENT_ENTRY.fullmatch(entry):
        return current[1].replace("\\", "/")
    return ""


def outside(entry: str) -> bool:
    path = Path(named_path(entry))
    return path.is_absolute() or ".." in path.parts


def entry_paths(entries: list[tuple[int, str]]) -> list[str]:
    """The files that the entries name; a finding of one file does not depend on another file."""
    return sorted({named_path(entry) for _, entry in entries} - {""})


def current_findings(
    root: Path, work: Path, config: list[str], timeout: float, paths: list[str]
) -> list[dict[str, str]]:
    snapshot = work / "snapshot"
    snapshot.mkdir()
    for path in paths:
        source = root / path
        if (
            source.is_file()
            and not source.is_symlink()
            and ".." not in Path(path).parts
        ):
            (snapshot / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, snapshot / path)
    return scan(["dir", "."], snapshot, work / "current.json", config, timeout)


def ensure_gitleaks(timeout: float) -> None:
    if shutil.which("gitleaks") is None:
        from tool_setup import PACKAGES, provision_batch

        provision_batch([PACKAGES["gitleaks"] + "@latest"], timeout)


def validate_entries(root: Path, timeout: float = 900.0) -> None:
    """Refuse each root entry that hides a finding a scan run now would not hide; the full check runs it after the tools are installed."""
    if (root / ".gitleaksignore").is_symlink():
        from comments import SWITCH_OFF_HEADER

        raise ValueError(
            f"{SWITCH_OFF_HEADER}\n  .gitleaksignore:1 is a link, which Gitleaks reads and no check can judge; make it a regular file"
        )
    all_entries = entry_lines(root)
    refused = [
        f".gitleaksignore:{number} holds {entry!r}: the path is outside the repository; remove the entry"
        for number, entry in all_entries
        if outside(entry)
    ]
    entries = [item for item in all_entries if not outside(item[1])]
    if entries:
        refused += judged_entries(root, entries, timeout)
    if refused:
        from comments import SWITCH_OFF_HEADER

        raise ValueError(
            "\n".join([SWITCH_OFF_HEADER, *(f"  {line}" for line in refused)])
        )


def judged_entries(
    root: Path, entries: list[tuple[int, str]], timeout: float
) -> list[str]:
    shown = dict(entries)
    entries = [(number, entry.replace("\\", "/")) for number, entry in entries]
    ensure_gitleaks(timeout)
    config = [".gitleaks.toml"] if (root / ".gitleaks.toml").is_file() else []
    config = ["--config", str((root / config[0]).resolve())] if config else []
    commits = sorted({m[1] for _, e in entries if (m := COMMIT_ENTRY.fullmatch(e))})
    present = [commit for commit in commits if known(root, commit)]
    with tempfile.TemporaryDirectory(prefix="hard-eng-entries-") as temporary:
        work = Path(temporary)
        past = past_findings(root, work, present, config, timeout) if present else set()
        current = current_findings(root, work, config, timeout, entry_paths(entries))
        paths = {item["File"] for item in current} | {
            m[2] for _, e in entries if (m := COMMIT_ENTRY.fullmatch(e))
        }
        names = sorted({m[1] for _, e in entries if (m := CURRENT_ENTRY.fullmatch(e))})
        generated = generated_sources(
            root, sorted(paths | set(names)), generated_only=True
        )
    now = {item["Fingerprint"] for item in current}
    in_tree = {(item["File"], item["RuleID"]) for item in current}
    return [
        f".gitleaksignore:{number} holds {shown[number]!r}: {reason}"
        for number, entry in entries
        if (reason := entry_reason(entry, present, past, now, in_tree, generated))
    ]


def entry_reason(
    entry: str,
    present: list[str],
    past: set[str],
    now: set[str],
    in_tree: set[tuple[str, str]],
    generated: set[str],
) -> str:
    """Why an entry is refused, or an empty string when it passes."""
    if commit := COMMIT_ENTRY.fullmatch(entry):
        if commit[1] not in present:
            return "the commit is not in this clone: fetch it, or remove the entry"
        if entry not in past:
            return "stale: a scan finds no such finding; remove the entry"
        if commit[2] in generated or (commit[2], commit[3]) not in in_tree:
            return ""
        return "the finding is still in the current tree: fix it there, then keep the entry only for the history"
    if (path := CURRENT_ENTRY.fullmatch(entry)) is None or entry not in now:
        return "stale: a scan finds no such finding; remove the entry"
    if path[1] in generated:
        return ""
    return "the finding is not in a linguist-generated file: fix it at its cause"
