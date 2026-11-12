"""File a deduplicated Hard Eng issue for a check the project has and Hard Eng lacks."""

import json
import re
from collections.abc import Collection
from pathlib import Path, PurePosixPath

from basic_mode import MANIFEST_LABELS, SUFFIX_LABELS, language_label
from gate_config import repository_files
from shipping import gh, git
from update_runner import installed_revision

REPO = "sgaabdu4/hard-eng"
MAX_LENGTH = 120
LABELS = sorted({*MANIFEST_LABELS.values(), *SUFFIX_LABELS.values()}, key=len)
LOOKS_LIKE_DETAIL = re.compile(r"[/\\@]|://|\bwww\.|[\w-]\.[A-Za-z][A-Za-z0-9]{0,4}\b")
NAME_SEPARATORS = re.compile(r"[\W_]+")
CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
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


def words(value: str) -> str:
    return NAME_SEPARATORS.sub(" ", value.casefold()).strip()


def origin_names(root: Path) -> list[str]:
    try:
        url = git(root, "remote", "get-url", "origin").strip()
    except ValueError:
        return []
    url = url.rstrip("/").removesuffix(".git")
    if url.startswith(("/", ".", "~", "file://")) or ":" not in url:
        return [url.rsplit("/", 1)[-1]]
    if "://" in url:
        path = url.split("://", 1)[1].partition("/")[2]
    else:
        path = url.partition(":")[2]
    return [part for part in path.split("/") if part and part != "_git"]


def package_names(root: Path) -> list[str]:
    try:
        config = json.loads((root / "hard-eng.gates.json").read_text())
        found = [
            value
            for package in config["packages"]
            for value in (package.get("name"), package.get("path"))
            if isinstance(value, str)
        ]
        return [*found, *(PurePosixPath(value).name for value in found)]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return []


def project_names(root: Path) -> set[str]:
    names = [root.resolve().name, *origin_names(root), *package_names(root)]
    names += [CAMEL_BOUNDARY.sub(" ", name) for name in names]
    spoken = {name for name in map(words, names) if name}
    return spoken | {name.replace(" ", "") for name in spoken}


def generic_problem(text: str, names: Collection[str] = ()) -> str | None:
    stripped = COMMON_FILE.sub("", text)
    for label in reversed(LABELS):
        stripped = stripped.replace(label, "")
    if not text.strip() or len(text) > MAX_LENGTH:
        return f"keep it to one generic line under {MAX_LENGTH} characters"
    if LOOKS_LIKE_DETAIL.search(stripped):
        return "it looks like a path, file name, URL or email"
    spoken = [f" {words(form)} " for form in (text, CAMEL_BOUNDARY.sub(" ", text))]
    named = (name for form in spoken for name in sorted(names) if f" {name} " in form)
    if match := next(named, None):
        return f"it names the project, its owner or one of its packages: {match}"
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
    if problem := generic_problem(text, project_names(root)):
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
