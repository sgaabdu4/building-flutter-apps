"""Read per-file line counts from coverage reports; prove omitted TypeScript and Swift files have no runtime content without executing them."""

import json
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import cast

from gate_config import Group, nonproduction_source

IF_DIRECTIVE = re.compile(r"(?m)^\s*#if\b")
COVERAGE_FILES = (
    ".coveragerc",
    ".coveragerc.toml",
    "setup.cfg",
    "tox.ini",
    "pyproject.toml",
)
COV_SECTIONS = ("run", "report", "html", "xml", "json", "lcov", "paths")


def file_sections(path: Path) -> Callable[[str], dict[str, object] | None]:
    """The reader of one section of a TOML or INI settings file; a TOML section is named by its dotted path."""
    import configparser
    import tomllib

    parser = configparser.ConfigParser(interpolation=None)
    data: dict[str, object] = {}
    try:
        if path.suffix == ".toml":
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        else:
            parser.read(path, encoding="utf-8")
    except (ValueError, configparser.Error) as error:
        raise ValueError(f"{path.name} cannot be read: {error}") from error

    def section(name: str) -> dict[str, object] | None:
        if path.suffix != ".toml":
            return dict(parser[name]) if parser.has_section(name) else None
        found: object = data
        for part in name.split("."):
            found = found.get(part) if isinstance(found, dict) else None
        return cast(dict[str, object], found) if isinstance(found, dict) else None

    return section


def settings_reader(path: Path, own: bool) -> Callable[[str], dict[str, object] | None]:
    """The sections of a coverage settings file; a file that is not coverage's own reads fewer."""
    section = file_sections(path)
    marked = "tool.coverage." if path.suffix == ".toml" else "coverage:"

    def coverage_section(name: str) -> dict[str, object] | None:
        found = section(marked + name)
        return section(name) if found is None and own else found

    return coverage_section


def coverage_file(
    directory: Path,
) -> tuple[str, Callable[[str], dict[str, object] | None]] | None:
    """The settings file that coverage.py reads, in its order, with the reader of its sections."""
    for name in COVERAGE_FILES:
        path = directory / name
        if not path.is_file():
            continue
        own = name.startswith(".coveragerc")
        section = settings_reader(path, own)
        if own or any(section(known) for known in COV_SECTIONS):
            return name, section
    return None


def omit_step(directory: Path, missing: list[Path]) -> str:
    """The sentence for a package whose own coverage settings leave one of these files out of the report."""
    from fnmatch import fnmatchcase

    try:
        found = coverage_file(directory)
    except ValueError:
        return ""
    if found is None:
        return ""
    name, section = found
    values = [(section(part) or {}).get("omit", "") for part in ("run", "report")]
    patterns = [
        str(entry).strip()
        for value in values
        for entry in (
            value
            if isinstance(value, list)
            else str(value).replace(",", "\n").split("\n")
        )
    ]
    forms = [
        form
        for file in missing
        for form in (
            file.name,
            file.as_posix(),
            (directory / file).absolute().as_posix(),
        )
    ]
    if any(fnmatchcase(form, pattern) for pattern in patterns for form in forms):
        return f". {name} has a coverage `omit` setting: remove its entries for these files"
    return ""


def erased_typescript(files: set[Path]) -> set[Path]:
    candidates = sorted(
        file for file in files if file.suffix in {".ts", ".tsx", ".mts", ".cts"}
    )
    if not candidates:
        return set()
    script = """
const sources = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
console.log(JSON.stringify(sources.map(([loader, source]) => {
  try { return new Bun.Transpiler({ loader }).transformSync(source); }
  catch { return null; }
})));
"""
    result = subprocess.run(
        ["bun", "-e", script],
        input=json.dumps(
            [
                ["tsx" if file.suffix == ".tsx" else "ts", file.read_text()]
                for file in candidates
            ]
        ),
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    outputs = json.loads(result.stdout)
    if not isinstance(outputs, list) or len(outputs) != len(candidates):
        raise ValueError("Invalid native TypeScript stripping result")
    # Only whitespace, comments, empty statements and an empty export remain.
    empty = (
        r"(?:\s|;|//[^\r\n\u2028\u2029]*|"
        r"/\*(?:[^*]|\*(?!/))*\*/|export\s*\{\s*\})*"
    )
    return {
        file
        for file, output in zip(candidates, outputs, strict=True)
        if isinstance(output, str) and re.fullmatch(empty, output)
    }


COUNTER_NODES = ("brace_stmt", "closure_expr", "original_init", "top_level_code_decl")


def erased_swift(files: set[Path]) -> set[Path]:
    """Parse-only proof: no body, closure or initial value, so Xcode lists no counters."""
    erased = set()
    for file in sorted(files):
        if IF_DIRECTIVE.search(file.read_text()):
            continue  # The parse drops code inside conditional compilation.
        parsed = subprocess.run(
            ["swiftc", "-frontend", "-dump-parse", str(file)],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if parsed.returncode == 0 and not any(
            f"({node}" in parsed.stdout for node in COUNTER_NODES
        ):
            erased.add(file)
    return erased


TOOL_CONFIGS = frozenset(
    {
        "astro",
        "babel",
        "capacitor",
        "commitlint",
        "cypress",
        "drizzle",
        "eslint",
        "jest",
        "knip",
        "lint-staged",
        "metro",
        "next",
        "next-sitemap",
        "nuxt",
        "open-next",
        "panda",
        "playwright",
        "postcss",
        "prettier",
        "release",
        "rollup",
        "rsbuild",
        "rspack",
        "stylelint",
        "svelte",
        "tailwind",
        "tsdown",
        "tsup",
        "uno",
        "vite",
        "vitest",
        "vue",
        "webpack",
        "wxt",
    }
)
CONFIG_EXTENSIONS = {"js", "mjs", "cjs", "ts", "mts", "cts"}
CODE_EXTENSIONS = {
    "python": {".py"},
    "javascript": {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"},
    "dart": {".dart"},
}
PLAYWRIGHT_TEST_DIR = re.compile(r"""\btestDir\s*:\s*(["'])(?:\./)?([^/"'\\]+)\1""")
PLAYWRIGHT_GLOBAL = re.compile(r"""\bglobal(?:Setup|Teardown)\s*:\s*(["'])([^"']+)\1""")
PLAYWRIGHT_IMPORT = re.compile(
    r"""\b(?:from|import|require)\s*\(?\s*(["'])@playwright/test\1"""
)


def root_tool_config(name: str) -> bool:
    """A name like `next.config.ts`, with one more part as in `vite.config.mobile.ts`, or a hidden file such as `.eslintrc.cjs`: tool configuration at the package root."""
    tool, *middle, extension = name.split(".")
    return extension in CONFIG_EXTENSIONS and (
        not tool or (tool in TOOL_CONFIGS and "config" in middle and len(middle) <= 2)
    )


def playwright_test_folders(
    directory: Path, files: list[Path], candidates: set[str]
) -> set[str]:
    """Candidate folders that a Playwright settings file names and whose code files are each a test by name, an importer of the Playwright test package or a named hook."""
    code = {
        Path(os.path.normpath(path)): path.relative_to(directory)
        for path in files
        if path.is_relative_to(directory)
        and path.suffix in CODE_EXTENSIONS["javascript"]
    }
    texts = [
        path.read_text(errors="replace")
        for path, relative in code.items()
        if len(relative.parts) == 1
        and root_tool_config(relative.name)
        and relative.name.startswith("playwright.")
    ]
    named = {match[2] for text in texts for match in PLAYWRIGHT_TEST_DIR.finditer(text)}
    hooks = {
        Path(os.path.normpath(directory / match[2]))
        for text in texts
        for match in PLAYWRIGHT_GLOBAL.finditer(text)
    }
    folders = set()
    for folder in named & candidates:
        inside = [
            path
            for path, relative in code.items()
            if relative.parts[0] == folder and len(relative.parts) > 1
        ]
        if inside and all(
            nonproduction_source(code[path])
            or path in hooks
            or PLAYWRIGHT_IMPORT.search(path.read_text(errors="replace"))
            for path in inside
        ):
            folders.add(folder)
    return folders


def source_roots(directory: Path, language: str, files: list[Path]) -> set[str]:
    """Top-level names that hold a package's production code."""
    sources = set()
    for path in files:
        if (
            not path.is_relative_to(directory)
            or path.suffix not in CODE_EXTENSIONS[language]
        ):
            continue
        relative = path.relative_to(directory)
        if (
            language == "javascript"
            and len(relative.parts) == 1
            and root_tool_config(relative.name)
        ) or (
            nonproduction_source(relative)
            or {".hooks", ".agents"} & set(relative.parts)
        ):
            continue
        sources.add(relative.parts[0])
    if language == "javascript" and sources:
        sources -= playwright_test_folders(directory, files, sources)
    return sources


def owned_files(
    root: Path, packages: list[Group], files: list[Path]
) -> dict[Path, list[Path]]:
    """Each file belongs to the package nearest to it."""
    owned: dict[Path, list[Path]] = {root / package["path"]: [] for package in packages}
    # Text prefixes, longest first: building each file's parents made large projects slow.
    prefixes = sorted(
        ((f"{directory}{os.sep}", paths) for directory, paths in owned.items()),
        key=lambda item: -len(item[0]),
    )
    for path in files:
        text = str(path)
        for prefix, paths in prefixes:
            if text.startswith(prefix):
                paths.append(path)
                break
    return owned


def require_listed_sources(
    root: Path, packages: list[Group], files: list[Path], python_only: bool
) -> None:
    """Code added after setup is checked only once its package lists it."""
    languages = {"python"} if python_only else {"python", "javascript", "dart"}
    groups = [group for group in packages if group.get("language") in languages]
    if not groups:
        return
    owned = owned_files(root, packages, files)
    for group in groups:
        language = group["language"]
        directory = root / group["path"]
        listed = tuple(os.path.normpath(source) for source in group.get("sources", []))
        if "." in listed:
            continue
        inside = tuple(f"{source}{os.sep}" for source in listed)
        start = len(str(directory)) + 1
        unlisted = [
            path
            for path in owned[directory]
            if (name := str(path)[start:]) not in listed and not name.startswith(inside)
        ]
        if missing := sorted(source_roots(directory, language, unlisted)):
            label = {"javascript": "JavaScript"}.get(language, language.title())
            add = "add each to that package's `sources` list in hard-eng.gates.json"
            tests = "Test-only code belongs in test/, tests/ or __tests__/."
            first = missing[0]
            steps = {
                "python": f"{add} and to every check that names them (tests --cov=, annotations, dead-code, duplicates)",
                "javascript": f"{add}. TypeScript also needs each in the `include` list of the package's TypeScript configuration. Tests must then cover that code. {tests}",
                "dart": f"move each under lib/ (for example {first} to lib/{first}) and test it there. Or {add}. Tests must then cover that code, and those tests need `test` as a dev dependency and a setup rerun. {tests}",
            }[language]
            raise ValueError(
                f"{group['path']}: {label} code is outside its sources: {', '.join(missing)}; {steps.rstrip('.')}. If a file moved, replace its old name in that list"
            )


def python_coverage(path: Path, directory: Path) -> dict[Path, tuple[int, int]]:
    files = {}
    try:
        text = path.read_text()
    except FileNotFoundError:
        raise ValueError(
            f"The test run wrote no Python coverage report ({path.name}). A --cov= value that names no module of the sources writes none. After a rename, replace the old name in the `sources` list of the package and in each --cov= value of its tests command in hard-eng.gates.json."
        ) from None
    report = json.loads(text)
    entries = report.get("files") if isinstance(report, dict) else None
    if not isinstance(entries, dict):
        raise TypeError("Invalid Python coverage files")
    for name, entry in entries.items():
        summary = entry.get("summary") if isinstance(entry, dict) else None
        if not isinstance(summary, dict):
            raise TypeError("Invalid Python coverage summary")
        covered, total = summary.get("covered_lines"), summary.get("num_statements")
        if (
            type(covered) is not int
            or type(total) is not int
            or not 0 <= covered <= total
        ):
            raise ValueError("Invalid Python line coverage counts")
        file = (directory / name).resolve()
        if file in files:
            raise ValueError(f"Duplicate Python coverage file: {name}")
        files[file] = covered, total
    return files


def xccov_coverage(path: Path, directory: Path) -> dict[Path, tuple[int, int]]:
    """Per-file counts from `xccov view --report --json`; targets share a file."""
    report = json.loads(path.read_text())
    targets = report.get("targets") if isinstance(report, dict) else None
    if not isinstance(targets, list):
        raise TypeError("Invalid xccov targets")
    files: dict[Path, tuple[int, int]] = {}
    for target in targets:
        for entry in target["files"]:
            covered, total = entry["coveredLines"], entry["executableLines"]
            if type(covered) is not int or type(total) is not int:
                raise TypeError("Invalid xccov line counts")
            if not 0 <= covered <= total:
                raise ValueError("Invalid xccov line counts")
            file = (directory / entry["path"]).resolve()
            files[file] = max(
                files.get(file, (0, 0)), (covered, total), key=lambda c: (c[1], c[0])
            )
    return files


def lcov_coverage(path: Path, directory: Path) -> dict[Path, tuple[int, int]]:
    files = {}
    lines = {}
    source = None
    for record in path.read_text().splitlines():
        if record.startswith("SF:"):
            if source is not None or not record[3:]:
                raise ValueError("Invalid LCOV source record")
            source = (directory / record[3:]).resolve()
            files.setdefault(source, (0, 0))
        elif record.startswith("DA:"):
            number, hits, *_ = record[3:].split(",")
            number, hits = int(number), int(hits)
            if source is None or number <= 0 or hits < 0:
                raise ValueError("Invalid LCOV line record")
            lines[source, number] = lines.get((source, number), False) or hits > 0
        elif record == "end_of_record":
            source = None
    if source is not None:
        raise ValueError("Incomplete LCOV source record")
    for (file, _), hit in lines.items():
        covered, total = files[file]
        files[file] = covered + hit, total + 1
    return files
