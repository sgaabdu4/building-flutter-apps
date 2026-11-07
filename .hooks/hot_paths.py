"""HE-HOT-PATH: Hard Eng's Semgrep rules join every security gate; `hot-paths` lists findings."""

import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath

from gate_config import Gate, Group, generated_sources, repository_files
from tool_setup import managed_command

RULES = (
    Path(__file__).resolve().parents[1] / ".agents/skills/he/semgrep/performance.yaml"
)
PYTHON_RULES = RULES.with_name("python.yaml")
GLOB_SPECIAL = re.compile(r"[][*?]")
EXCLUDED_LIST = "&excluded [\n"
EXCLUDED_ITEMS = re.compile(r"^( +)exclude:\n( +)(?=- )", re.MULTILINE)


def findings(root: Path, targets: list[str], timeout: float) -> list[dict[str, object]]:
    command = managed_command(
        ["semgrep", "scan", "--config", str(RULES), "--metrics=off"]
    )
    try:
        result = subprocess.run(
            [*command, "--quiet", "--json", "--timeout", "60", *targets],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError(f"HE-HOT-PATH scan ran over {timeout:.0f}s") from error
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ValueError(f"HE-HOT-PATH scan failed: {result.stderr[-500:]}") from error
    require_parsed(report.get("errors", []))
    return report["results"]


def require_parsed(errors: list[dict[str, object]]) -> None:
    """Fail on scan errors except files Semgrep parsed only in part; print those gaps."""
    spans = [
        kind[1]
        for kind in (error.get("type") for error in errors)
        if isinstance(kind, list) and kind[0] == "PartialParsing"
    ]
    if len(spans) != len(errors):
        raise ValueError(f"Semgrep reports scan errors: {str(errors)[:1000]}")
    for span in (span for gaps in spans for span in gaps):
        print(f"Semgrep partly scanned {span['path']}:{span['start']['line']}")


def describe(result: dict[str, object]) -> str:
    start, extra = result["start"], result["extra"]
    assert isinstance(start, dict) and isinstance(extra, dict)
    return f"{result['path']}:{start['line']} {extra['message']}"


def scan_all(root: Path, timeout: float = 600) -> int:
    """List every finding in the repository, for a requested hot-path scan."""
    results = findings(root, ["."], timeout)
    for result in results:
        print(describe(result))
    print(f"HE-HOT-PATH: {len(results)} findings")
    return 1 if results else 0


def unowned_paths(names: list[str], generated: set[str]) -> list[str]:
    """Generated files, as their highest folder that holds nothing else."""
    files: Counter[PurePosixPath] = Counter()
    made: Counter[PurePosixPath] = Counter()
    for name in names:
        for folder in PurePosixPath(name).parents[:-1]:
            files[folder] += 1
            made[folder] += name in generated
    paths = set()
    for name in generated:
        folders = [
            folder
            for folder in PurePosixPath(name).parents[:-1]
            if made[folder] == files[folder]
        ]
        paths.add(f"{folders[-1]}/" if folders else name)
    return sorted(paths)


def git_prefix(directory: Path) -> str:
    """The folder's path from the Git root, which Semgrep anchors excludes to."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-prefix"],
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def rules_skipping(skipped: list[str], directory: Path) -> str:
    """Hard Eng's rules with generated paths excluded, so registry packs still scan them."""
    if not skipped:
        return os.path.relpath(RULES, directory)
    entries = [json.dumps(name) for name in skipped]
    text = RULES.read_text().replace(
        EXCLUDED_LIST,
        EXCLUDED_LIST + "".join(f"          {entry},\n" for entry in entries),
        1,
    )
    text = EXCLUDED_ITEMS.sub(
        lambda found: (
            found[1]
            + "exclude:\n"
            + "".join(f"{found[2]}- {entry}\n" for entry in entries)
            + found[2]
        ),
        text,
    )
    target = Path(tempfile.gettempdir()) / "hard-eng-rules"
    target.mkdir(exist_ok=True)
    target /= hashlib.sha256(text.encode()).hexdigest()[:16] + ".yaml"
    if not target.exists():
        partial = target.with_suffix(f".{os.getpid()}")
        partial.write_text(text)
        os.replace(partial, target)
    return str(target)


def installed_paths(root: Path) -> list[str]:
    """Folders Hard Eng installed at the repository root, as its install record lists them; an older record lists no skills."""
    marker = root / ".hooks/hard-eng-source.json"
    if not marker.is_file():
        return []
    try:
        record: object = json.loads(marker.read_text())
    except (OSError, ValueError):
        record = None
    skills = record.get("skills") if isinstance(record, dict) else None
    names: list[object] = skills if isinstance(skills, list) else []
    return [
        ".hooks/",
        *(
            f".agents/skills/{name}/"
            for name in names
            if isinstance(name, str) and "/" not in name
        ),
    ]


def semgrep_options(
    root: Path, group: Group, gate: Gate, command: list[str]
) -> list[str]:
    """Add Hard Eng's rules to security scans, skip generated files, limit each rule to 60 s."""
    directory = root / group["path"]
    if gate.get("role") == "security" and "p/python" in command:
        index = command.index("p/python") + 1
        command = [
            *command[:index],
            "--config",
            os.path.relpath(PYTHON_RULES, directory),
            "--exclude-rule",
            "python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1",
            *command[index:],
        ]
    index = command.index("scan") if "scan" in command else 0
    if not index or Path(command[index - 1]).name.split("@")[0] != "semgrep":
        return command
    if gate.get("role") == "security":
        names = [
            path.relative_to(directory).as_posix()
            for path in repository_files(directory)
        ]
        unowned = unowned_paths(names, generated_sources(directory, names))
        prefix = git_prefix(directory)
        skipped = [
            "/" + GLOB_SPECIAL.sub(r"\\\g<0>", prefix + name) for name in unowned
        ]
        installed = [f"--exclude=/{name}" for name in installed_paths(root)]
        rules = ["--config", rules_skipping(skipped, directory), *installed]
        # --strict fails valid code Semgrep parses only in part; the report check prints those gaps.
        rest = [part for part in command[index + 1 :] if part != "--strict"]
        command = [*command[: index + 1], *rules, *rest]
    if "--timeout" not in command:
        # Semgrep's 5 s per-rule limit times out under parallel load, and the report check then fails the gate.
        command = [*command[: index + 1], "--timeout", "60", *command[index + 1 :]]
    return command
