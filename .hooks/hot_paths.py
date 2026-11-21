"""HE-HOT-PATH: Hard Eng's Semgrep rules join every security gate; `hot-paths` lists findings."""

import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import TypedDict

from gate_config import (
    SOURCE_FILE,
    Gate,
    Group,
    nonproduction_source,
    repository_files,
)
from generated_marks import generated_sources
from source_scan import code_step, code_without_comments
from tool_setup import managed_command

Place = TypedDict("Place", {"line": int, "col": int})
Span = TypedDict("Span", {"path": str, "start": Place, "end": Place})

RULES = (
    Path(__file__).resolve().parents[1] / ".agents/skills/he/semgrep/performance.yaml"
)
PYTHON_RULES = RULES.with_name("python.yaml")
GLOB_SPECIAL = re.compile(r"[][*?]")
EXCLUDED_LIST = "&excluded [\n"
EXCLUDED_ITEMS = re.compile(r"^( +)exclude:\n( +)(?=- )", re.MULTILINE)
BREAK = r"\s*"
NEEDED_BREAK = r"\s+"
FRAME = r"(?:setImmediate|requestAnimationFrame|requestIdleCallback|queueMicrotask)"
JS_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}
JS_FORMS = re.compile(
    "|".join(
        [
            rf"(?<![\w$.]){FRAME}{BREAK}\(",
            rf"(?<![\w$])(?:window|globalThis|self|global){BREAK}\.{BREAK}{FRAME}{BREAK}\(",
            rf"(?<![\w$.])process{BREAK}\.{BREAK}nextTick(?![\w$])",
            rf"(?<![\w$.])Promise{BREAK}\.{BREAK}resolve{BREAK}\({BREAK}\){BREAK}\.{BREAK}then(?![\w$])",
            rf"(?<![\w$.])await{NEEDED_BREAK}Promise{BREAK}\.{BREAK}resolve{BREAK}\({BREAK}\)",
            rf"(?<![\w$.])await{NEEDED_BREAK}null(?![\w$])",
        ]
    ),
    re.DOTALL,
)
JS_TIMEOUT = re.compile(
    rf"(?<![\w$.])(?:(?:window|globalThis|self|global){BREAK}\.{BREAK})?setTimeout{BREAK}\(",
    re.DOTALL,
)
SHORT_NUMBER = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)")
GENERIC = r"(?:<[^()]*>)?"
DART_FORMS = re.compile(
    "|".join(
        [
            rf"(?<![\w$.])scheduleMicrotask{BREAK}\(",
            rf"(?<![\w$.])Timer{BREAK}\.{BREAK}run(?![\w$])",
            rf"(?<![\w$.])Future{BREAK}{GENERIC}{BREAK}\(",
            rf"(?<![\w$.])Future{BREAK}{GENERIC}{BREAK}\.{BREAK}microtask(?![\w$])",
            rf"(?<![\w$.])await{NEEDED_BREAK}null(?![\w$])",
        ]
    ),
    re.DOTALL,
)
DART_DELAY = re.compile(
    rf"(?<![\w$.])(?:Future{BREAK}{GENERIC}{BREAK}\.{BREAK}delayed|Timer){BREAK}\(",
    re.DOTALL,
)
SHORT_DURATION = re.compile(
    r"(?:const\s+)?Duration\s*(?:\.\s*zero|\(\s*\)|\(\s*(?:milliseconds|microseconds)\s*:\s*(?:\d|1[0-6])\s*\))"
)
CLOSERS = {"(": ")", "[": "]", "{": "}"}
CONTEXT_LINES = 3


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
        raise ValueError(
            "HE-HOT-PATH scan failed: Semgrep gave no report. If the text below says uv "
            "cannot write its cache or reach the package index, run the same "
            "`python3 .hooks/hard-eng.py hot-paths` command where it can; in an agent "
            f"sandbox, ask approval to run it outside the sandbox. Output: {result.stderr[-500:]}"
        ) from error
    require_parsed(report.get("errors", []), root)
    return report["results"]


def call_arguments(text: str, start: int, suffix: str) -> list[str] | None:
    """The top-level arguments of the call whose text begins after its open bracket, or None when the text ends first."""
    arguments: list[str] = []
    depth, begin, index = 0, start, start
    templates: list[int] = []
    while index < len(text):
        char = text[index]
        if (end := code_step(text, index, suffix, templates)) is not None:
            index = end
            continue
        if char in CLOSERS:
            depth += 1
        elif char in CLOSERS.values():
            if depth == 0 and not templates:
                arguments.append(text[begin:index])
                return arguments
            depth -= 1
        elif char == "," and depth == 0 and not templates:
            arguments.append(text[begin:index])
            begin = index + 1
        index += 1
    return None


def short_javascript_delay(arguments: list[str] | None) -> bool:
    if arguments is None or len(arguments) < 2:
        return True
    delay = arguments[1].strip()
    return bool(SHORT_NUMBER.fullmatch(delay)) and float(delay) < 17


def short_dart_delay(arguments: list[str] | None) -> bool:
    return arguments is None or bool(SHORT_DURATION.fullmatch(arguments[0].strip()))


def hidden_deferral(text: str, suffix: str) -> str | None:
    """The first zero-delay or next-frame call that the text holds, as the text spells it."""
    dart = suffix == ".dart"
    forms, calls = (DART_FORMS, DART_DELAY) if dart else (JS_FORMS, JS_TIMEOUT)
    short = short_dart_delay if dart else short_javascript_delay
    text = code_without_comments(text, suffix)
    if found := forms.search(text):
        return " ".join(found[0].split())
    for call in calls.finditer(text):
        if short(call_arguments(text, call.end(), suffix)):
            return " ".join(call[0].split())
    return None


def span_text(lines: list[str], span: Span) -> str:
    """The unread lines with 3 lines around them: a call can start before the gap and end after it."""
    first = max(span["start"]["line"] - 1 - CONTEXT_LINES, 0)
    return "\n".join(lines[first : span["end"]["line"] + CONTEXT_LINES])


def refuse_hidden_deferrals(spans: list[Span], root: Path) -> None:
    """HE-HOT-PATH: a zero-delay or next-frame call in a part Semgrep could not read fails like one it read."""
    judged = [
        span
        for span in spans
        if Path(span["path"]).suffix in {*JS_SUFFIXES, ".dart"}
        and not span["path"].startswith(".agents/")
        and not nonproduction_source(Path(span["path"]))
    ]
    names = sorted({span["path"] for span in judged})
    generated = generated_sources(root, names) if names else set()
    found = []
    for span in judged:
        name = span["path"]
        if name in generated:
            continue
        lines = (root / name).read_text(errors="replace").splitlines()
        if form := hidden_deferral(span_text(lines, span), Path(name).suffix):
            found.append(f"{name}:{span['start']['line']} ({form})")
    if found:
        raise ValueError(
            "HE-HOT-PATH: Semgrep could not read this code, and it holds a zero-delay or next-frame call: "
            + "; ".join(found)
            + ". Change that code until Semgrep reads it, then fix the call at its cause: run the work from the event, listener or animation that owns it."
        )


def require_parsed(errors: list[dict[str, object]], root: Path | None = None) -> None:
    """Fail on scan errors except files Semgrep parsed only in part; print those gaps, and fail on a timer call inside one."""
    spans = [
        kind[1]
        for kind in (error.get("type") for error in errors)
        if isinstance(kind, list) and kind[0] == "PartialParsing"
    ]
    if len(spans) != len(errors):
        raise ValueError(f"Semgrep reports scan errors: {str(errors)[:1000]}")
    for span in (span for gaps in spans for span in gaps):
        print(f"Semgrep partly scanned {span['path']}:{span['start']['line']}")
    if root is not None:
        refuse_hidden_deferrals([span for gaps in spans for span in gaps], root)


def describe(result: dict[str, object]) -> str:
    start, extra = result["start"], result["extra"]
    assert isinstance(start, dict) and isinstance(extra, dict)
    return f"{result['path']}:{start['line']} {extra['message']}"


def scan_all(root: Path, timeout: float = 600, paths: list[str] | None = None) -> int:
    """List every finding in the named files, else the whole repository."""
    results = findings(root, paths or ["."], timeout)
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
    marker = root / SOURCE_FILE
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
