"""File a deduplicated Hard Eng issue for a check the project has and Hard Eng lacks."""

import json
import re
from pathlib import Path

from basic_mode import MANIFEST_LABELS, SUFFIX_LABELS, language_label
from gate_config import repository_files
from shipping import gh
from update_runner import installed_revision

REPO = "sgaabdu4/hard-eng"
MAX_LENGTH = 120
LABELS = sorted({*MANIFEST_LABELS.values(), *SUFFIX_LABELS.values()}, key=len)
LOOKS_LIKE_DETAIL = re.compile(r"[/\\@]|://|\bwww\.|[\w-]\.[A-Za-z][A-Za-z0-9]{0,4}\b")
COMMON_FILES = (
    "go.mod",
    "go.sum",
    "Cargo.toml",
    "Cargo.lock",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lock",
    "pyproject.toml",
    "uv.lock",
    "poetry.lock",
    "requirements.txt",
    "pubspec.yaml",
    "pubspec.lock",
    "Gemfile",
    "Gemfile.lock",
    "composer.json",
    "composer.lock",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "Package.swift",
    "CMakeLists.txt",
    "Dockerfile",
    "Makefile",
    "tsconfig.json",
)
COMMON_FILE = re.compile(
    r"(?<![\w./\\@-])(?:"
    + "|".join(re.escape(name) for name in COMMON_FILES)
    + r")(?![\w/\\@-]|\.\w)"
)
BODY = """Missing check: {text}

Language: {language}
Hard Eng revision: {revision}

Filed by `python3 .hooks/hard-eng.py gap-issue`. It names only the missing check."""


def generic_problem(text: str) -> str | None:
    stripped = COMMON_FILE.sub("", text)
    for label in reversed(LABELS):
        stripped = stripped.replace(label, "")
    if not text.strip() or len(text) > MAX_LENGTH:
        return f"keep it to one generic line under {MAX_LENGTH} characters"
    if LOOKS_LIKE_DETAIL.search(stripped):
        return "it looks like a path, file name, URL or email"
    return None


def language(root: Path) -> str:
    config = json.loads((root / "hard-eng.gates.json").read_text())
    named = {
        package["language"]
        for package in config.get("packages", [])
        if package.get("language")
    }
    if named:
        return ", ".join(sorted(named))
    return language_label(root, repository_files(root)) or "not detected"


def file_gap(root: Path, text: str) -> int:
    text = " ".join(text.split())
    if problem := generic_problem(text):
        raise ValueError(
            f"Not filed: {problem}. Describe the missing check generically, without project names, code, paths or data."
        )
    title = f"Missing check: {text}"
    found = json.loads(
        gh(
            root,
            "issue",
            "list",
            "--repo",
            REPO,
            "--state",
            "all",
            "--search",
            f'"{title.replace(chr(34), " ")}" in:title',
            "--json",
            "title,url",
            "--limit",
            "30",
        )
    )
    for issue in found:
        if issue["title"].casefold() == title.casefold():
            print(f"Already filed: {issue['url']}")
            return 0
    body = BODY.format(
        text=text,
        language=language(root),
        revision=installed_revision(root) or "unknown",
    )
    print(
        gh(
            root, "issue", "create", "--repo", REPO, "--title", title, "--body", body
        ).strip()
    )
    return 0
