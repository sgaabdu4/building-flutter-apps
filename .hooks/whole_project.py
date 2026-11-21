"""The full check judges every tracked file and every new file that Git does not ignore, with the patterns of the changed-file checks, old code included."""

import re
import subprocess
import tomllib
from itertools import pairwise
from pathlib import Path, PurePosixPath

from command_words import assigns_variables
from comments import (
    COMMENT_HEADER,
    HASH,
    RETRY_WORDS,
    SCAN_IGNORES,
    SECURITY_OFF,
    SLASH,
    SWITCH_OFF_HEADER,
    UNOWNED,
    block_hits,
    comment_map,
    entry_file,
    pattern_switch_offs,
    security_hits,
)
from fallow_settings import SETTINGS_FILES, settings_switch_offs
from generated_marks import copy_findings, generated_sources
from gitleaks_rules import DEFAULT_RULE_IDS
from gitleaks_scan import config_variable_hits
from project_files import GIT_LISTING
from ruff_settings import SETTINGS_FILES as RUFF_FILES
from ruff_settings import settings_switch_offs as ruff_switch_offs
from rust_settings import CLIPPY_FILES, rust_file_hits
from shellcheck_rc import rc_hits
from workflow_blocking import hard_eng_workflow, workflow_hits

LINE_IGNORES = {".gitleaksignore", ".semgrepignore"}
TEXT_SUFFIXES = {
    *HASH,
    *SLASH,
    ".md",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".xcscheme",
    ".xctestplan",
}
LINKED_NAMES = {
    *LINE_IGNORES,
    ".gitleaks.toml",
    *SETTINGS_FILES,
    *RUFF_FILES,
    "Cargo.toml",
    *CLIPPY_FILES,
}
MARKER = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")
ALLOWLIST_LINE = re.compile(r"\s*(\[\[?[\w.-]*allowlists?\]\]?|[\w.-]*allowlists?\s*=)")
PATHS_LINE = re.compile(r"\s*paths\s*=")
DISABLED_LINE = re.compile(r"\s*disabledRules\s*=")
MARKER_HEADER = (
    "HE-COMMENT-LINES: A TODO, FIXME, HACK or XXX marker excuses unfinished work: "
    "fix the cause now and delete the comment; never suppress it."
)
MARKDOWN_HEADER = (
    "HE-NAMED-MARKDOWN: A markdown file that no other tracked file names has no reader: "
    "fix it at the cause, so name it where a reader opens it or delete it; never suppress it."
)
MARKDOWN_NAME = re.compile(r"[\w.+-]+\.md\b")
NEEDS_NO_LINK = {
    "README",
    "AGENTS",
    "AGENTS.OVERRIDE",
    "PRODUCT",
    "DESIGN",
    "SECURITY",
    "CHANGELOG",
    "PLAN",
    "DECISION",
    "SKILL",
    "CONTRIBUTING",
    "CODE_OF_CONDUCT",
    "SUPPORT",
    "GOVERNANCE",
    "MAINTAINERS",
    "CODEOWNERS",
    "LICENSE",
    "NOTICE",
}
NEEDS_NO_LINK_FOLDERS = ("docs/adr/", "docs/requirements.md", ".github/", *UNOWNED)


def listed_names(root: Path) -> list[str]:
    listed = subprocess.check_output(
        [*GIT_LISTING, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        text=True,
    )
    return sorted({name for name in listed.split("\0") if name})


def tracked_files(root: Path, names: list[str] | None = None) -> list[str]:
    return [
        name
        for name in (listed_names(root) if names is None else names)
        if (root / name).is_file() and not (root / name).is_symlink()
    ]


def is_settings_name(name: str) -> bool:
    return PurePosixPath(name).name in LINKED_NAMES or name.endswith(
        (".cargo/config", ".cargo/config.toml")
    )


def linked_folder_hits(root: Path, name: str, names: list[str]) -> list[str]:
    """A link to a folder that holds a settings file, or a `.cargo` folder link, since the checks read those files by their path."""
    try:
        target = (root / name).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return []
    if not (root / name).is_dir():
        return []
    held = [
        other
        for other in names
        if other.startswith(target.rstrip("/") + "/") and is_settings_name(other)
    ]
    if held or PurePosixPath(name).name == ".cargo":
        inside = f" that holds {held[0]}" if held else ""
        return [
            f"{name}:1 is a link to a folder{inside}, which hides settings lines from every check; make it a real folder"
        ]
    return []


def linked_settings(root: Path, names: list[str]) -> list[str]:
    """Ignore and settings files that no check reads through a link, so a link hides their lines."""
    found = [
        f"{name}:1 is a link, which hides the lines of this file from every check; make it a regular file"
        for name in names
        if is_settings_name(name)
        and not name.startswith(UNOWNED)
        and (root / name).is_symlink()
    ]
    for name in names:
        if (root / name).is_symlink() and not name.startswith(UNOWNED):
            found += linked_folder_hits(root, name, names)
    return found


def gitleaks_switch_offs(name: str, text: str) -> list[str]:
    """Allowlist entries and disabled rules of a Gitleaks config; its detection rules stay."""
    try:
        config = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    lines = text.splitlines()

    def at(pattern: re.Pattern[str]) -> list[int]:
        return [n for n, line in enumerate(lines, 1) if pattern.match(line)] or [1]

    allowlisted = "allowlist" in config or "allowlists" in config
    allowlisted = allowlisted or any(
        "allowlist" in rule or "allowlists" in rule for rule in config.get("rules", [])
    )
    found = [f"{name}:{n} holds an allowlist" for n in at(ALLOWLIST_LINE)]
    found = found if allowlisted else []
    if "paths" in config:
        found += [f"{name}:{n} holds a list of paths" for n in at(PATHS_LINE)]
    for rule in config.get("rules", []):
        rule_id = rule.get("id") if isinstance(rule, dict) else None
        if rule_id in DEFAULT_RULE_IDS:
            number = next(
                (
                    n
                    for n, line in enumerate(lines, 1)
                    if re.match(rf"\s*id\s*=\s*['\"]{re.escape(rule_id)}['\"]", line)
                ),
                1,
            )
            found.append(
                f"{name}:{number} overrides the default rule {rule_id}; give a new rule its own id"
            )
    extend = config.get("extend")
    if not isinstance(extend, dict) or extend.get("useDefault") is not True:
        found.append(
            f"{name}:1 drops the default rules without [extend] useDefault = true"
        )
    if isinstance(extend, dict) and (off := extend.get("disabledRules")):
        found += [f"{name}:{n} disables the rules {off!r}" for n in at(DISABLED_LINE)]
    return found


def cargo_switch_offs(name: str, text: str) -> list[str]:
    """Lint levels of allow in a Cargo manifest: `[lints]` and `[workspace.lints]` tables, by string or by `level`."""
    try:
        config = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    tables = [config.get("lints"), config.get("workspace", {}).get("lints")]
    off: list[str] = []

    def walk(table: object, path: str) -> None:
        if not isinstance(table, dict):
            return
        for key, value in table.items():
            if value == "allow" or (key == "level" and value == "allow"):
                off.append(path if key == "level" else f"{path}.{key}")
            else:
                walk(value, f"{path}.{key}")

    for table in tables:
        walk(table, "lints")
    lines = text.splitlines()
    return [
        f"{name}:{_line(lines, hit.rsplit('.', 1)[-1])} sets the lint {hit.removeprefix('lints.')} to 'allow'"
        for hit in off
    ]


def _line(lines: list[str], key: str) -> int:
    pattern = re.compile(
        rf"^\s*(?:\[.*\b{re.escape(key)}\b.*\]|\"?{re.escape(key)}\"?\s*=)"
    )
    return next((n for n, line in enumerate(lines, 1) if pattern.match(line)), 1)


def switch_offs(root: Path, texts: dict[str, str]) -> list[str]:
    owned = [name for name in texts if not name.startswith(UNOWNED)]
    skipped = generated_sources(root, owned)
    found: list[str] = []
    for name in (name for name in owned if name not in skipped):
        text = texts[name]
        lines = list(enumerate(text.splitlines(), 1))
        base = PurePosixPath(name).name
        entries = entry_file(root, name, LINE_IGNORES)
        if hard_eng_workflow(name):
            found += workflow_hits(name, text)
        if (
            entries
            or hard_eng_workflow(name)
            or SECURITY_OFF.search(text)
            or any(w in text for w in RETRY_WORDS)
        ):
            found += security_hits(root, name, lines, "holds", entries)
        found += pattern_switch_offs(root, name, lines, "holds")
        if base in {".shellcheckrc", "shellcheckrc"}:
            found += rc_hits(name, text)
        if base == ".gitleaks.toml":
            found += gitleaks_switch_offs(name, texts[name])
        if assigns_variables(name):
            found += config_variable_hits(name, text)
        if base == "Cargo.toml":
            found += cargo_switch_offs(name, text)
        if base in SETTINGS_FILES:
            found += settings_switch_offs(root, name, text)
        found += rust_file_hits(name, text)
        if base in RUFF_FILES:
            found += ruff_switch_offs(root, name, text)
    return found


def source_names(root: Path, texts: dict[str, str]) -> list[str]:
    names = [
        name
        for name in texts
        if Path(name).suffix in HASH | SLASH and not name.startswith(".agents/")
    ]
    skipped = generated_sources(root, names)
    return [name for name in names if name not in skipped]


def excuse_markers(root: Path, texts: dict[str, str], names: list[str]) -> list[str]:
    return [
        f"{name}:{number} holds a {hit[0]} marker"
        for name in names
        if MARKER.search(texts[name])
        for number, comment in comment_map(root / name, texts[name], True).items()
        if (hit := MARKER.search(comment))
    ]


def may_hold_block(name: str, text: str) -> bool:
    slash = Path(name).suffix in SLASH
    if slash and "/*" in text:
        return True
    token = "//" if slash else "#"
    marks = [token in line for line in text.splitlines()]
    return any(a and b for a, b in pairwise(marks))


def unnamed_markdown(texts: dict[str, str]) -> list[str]:
    named: dict[str, set[str]] = {}
    for name, text in texts.items():
        for hit in MARKDOWN_NAME.findall(text) if ".md" in text else ():
            named.setdefault(hit, set()).add(name)
    return [
        f"{name}:1 is named by no other tracked file"
        for name in texts
        if name.endswith(".md")
        and not name.startswith(NEEDS_NO_LINK_FOLDERS)
        and PurePosixPath(name).stem.upper() not in NEEDS_NO_LINK
        and not named.get(PurePosixPath(name).name, set()) - {name}
    ]


def binary(name: str, data: bytes) -> bool:
    """Git's NUL test, kept only for bytes that are not UTF-8 and a name no check reads as code or settings."""
    if b"\0" not in data[:8000] or PurePosixPath(name).suffix in TEXT_SUFFIXES:
        return False
    if PurePosixPath(name).name in SCAN_IGNORES:
        return False
    try:
        data.decode()
    except UnicodeDecodeError:
        return True
    return False


def text_files(root: Path, names: list[str] | None = None) -> dict[str, str]:
    """Tracked and new text files; a NUL byte cannot hide code or settings from the pass."""
    texts: dict[str, str] = {}
    for name in tracked_files(root, names):
        data = (root / name).read_bytes()
        if not binary(name, data):
            text = data.decode(errors="replace")
            texts[name] = text.replace("\r\n", "\n").replace("\r", "\n")
    return texts


def validate_whole_project(root: Path) -> None:
    names = listed_names(root)
    texts = text_files(root, names)
    sources = source_names(root, texts)
    kinds = [
        (
            SWITCH_OFF_HEADER,
            [
                *switch_offs(root, texts),
                *linked_settings(root, names),
                *copy_findings(root),
            ],
        ),
        (MARKER_HEADER, excuse_markers(root, texts, sources)),
        (
            COMMENT_HEADER,
            [
                hit
                for name in sources
                if may_hold_block(name, texts[name])
                for hit in block_hits(name, root / name, texts[name])
            ],
        ),
        (MARKDOWN_HEADER, unnamed_markdown(texts)),
    ]
    blocks = [
        "\n".join([header, *(f"  {hit}" for hit in found)])
        for header, found in kinds
        if found
    ]
    if blocks:
        raise ValueError("\n".join(blocks))
