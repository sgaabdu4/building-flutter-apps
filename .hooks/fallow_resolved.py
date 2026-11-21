"""Judge the config Fallow prints for a gate: no check switched off and no file dropped without a reason."""

import json
import re
import subprocess
import tempfile
from collections.abc import Callable
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from fallow_table import judge
from project_files import GIT_LISTING
from scope_check import FALLOW_CONFIGS, glob_regex, left_out, refusal, tracked


def printed_config(
    directory: Path, config: str | None, timeout: float
) -> dict[str, object]:
    done = subprocess.run(
        ["fallow", "config", *(["-c", config] if config else [])],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if done.returncode:
        raise ValueError(
            f"HE-NO-SWITCH-OFF: fallow cannot read its config: {done.stderr.strip()}"
        )
    return json.loads(done.stdout)


def default_config(timeout: float) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="hard-eng-fallow-") as empty:
        return printed_config(Path(empty), None, timeout)


def pattern_hits(
    directory: Path, children: frozenset[str]
) -> Callable[[list[str]], list[str]]:
    """A check for the patterns of one setting: each tracked source file that a pattern drops must be generated or belong to a child group."""

    def drop(patterns: list[str]) -> list[str]:
        if not patterns:
            return []
        names = tracked(directory, FALLOW_SUFFIXES)
        regexes = [glob_regex(pattern) for pattern in patterns]
        matched = {name for name in names if any(r.fullmatch(name) for r in regexes)}
        left = left_out(
            directory, FALLOW_SUFFIXES, set(names) - matched, children, FALLOW_SKIPPED
        )
        return [f"drops {name}" for name in left[:1]] if left else []

    return drop


FALLOW_SUFFIXES = (
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".mts",
    ".cts",
    ".vue",
    ".svelte",
    ".astro",
)
FALLOW_SKIPPED = frozenset(
    {
        "node_modules",
        "dist",
        "build",
        "coverage",
        ".next",
        ".nuxt",
        ".svelte-kit",
        ".output",
        ".turbo",
        ".cache",
    }
)


def listed_files(directory: Path, config: str | None, timeout: float) -> set[str]:
    """The files Fallow discovers for this gate."""
    done = subprocess.run(
        [
            "fallow",
            "list",
            "--files",
            "--format",
            "json",
            *(["-c", config] if config else []),
        ],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if done.returncode:
        raise ValueError(
            f"HE-NO-SWITCH-OFF: fallow cannot list the files of this gate: {done.stderr.strip()}"
        )
    files = json.loads(done.stdout).get("files")
    return (
        {name for name in files if isinstance(name, str)}
        if isinstance(files, list)
        else set()
    )


def entry_sources(
    directory: Path, printed: dict[str, object], timeout: float
) -> dict[str, str]:
    """Each entry point that Fallow finds with no manual `entry` list, with the plugin or package script that finds it."""
    without = {name: value for name, value in printed.items() if name != "entry"}
    with tempfile.TemporaryDirectory(prefix="hard-eng-fallow-") as folder:
        path = Path(folder) / "config.json"
        path.write_text(json.dumps(without))
        done = subprocess.run(
            ["fallow", "list", "--entry-points", "--format", "json", "-c", str(path)],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    if done.returncode:
        raise ValueError(
            f"HE-NO-SWITCH-OFF: fallow cannot list the entry points of this gate: {done.stderr.strip()}"
        )
    items = json.loads(done.stdout).get("entry_points")
    return {
        item["path"]: str(item.get("source", ""))
        for item in items or []
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }


def covering(checked: set[str], found: dict[str, str]) -> Callable[[str], str]:
    """For an entry glob, the names of what finds all its files already, or nothing when any file is found only by the glob."""

    def covered(glob: str) -> str:
        pattern = glob_regex(glob)
        matched = {name for name in checked if pattern.fullmatch(name)}
        if not matched or not matched <= found.keys():
            return ""
        return ", ".join(sorted({found[name] for name in matched}))

    return covered


def written_coverage(directory: Path, reports: list[str]) -> set[Path]:
    """The Istanbul map that Hard Eng writes beside each report of a tests gate in the group."""
    return {
        (directory / Path(report).parent / "coverage-final.json").resolve()
        for report in reports
    }


def committed(directory: Path, path: Path) -> bool:
    done = subprocess.run(
        [*GIT_LISTING, "ls-files", "--error-unmatch", str(path)],
        cwd=directory,
        capture_output=True,
        check=False,
    )
    return done.returncode == 0


def covers_every_file(directory: Path, patterns: list[str]) -> bool:
    regexes = [glob_regex(pattern) for pattern in patterns]
    names = tracked(directory, FALLOW_SUFFIXES)
    return bool(regexes and names) and all(
        any(regex.fullmatch(name) for regex in regexes) for name in names
    )


def proved_hits(
    printed: dict[str, object], directory: Path, proof: tuple[list[str], str | None]
) -> list[str]:
    """Settings judged by what proves them: coverage that the group's own tests write, and boundaries that cover every file."""
    reports, flag = proof
    hits = []
    health = printed.get("health")
    coverage = health.get("coverage") if isinstance(health, dict) else None
    for value in [*([str(coverage)] if coverage else []), *([flag] if flag else [])]:
        path = (directory / value).resolve()
        if path not in written_coverage(directory, reports) or committed(
            directory, path
        ):
            hits.append(
                f"health.coverage is {value}; Fallow may read only the coverage-final.json that a tests gate writes in this group, and never a committed file"
            )
    boundaries = printed.get("boundaries")
    if isinstance(boundaries, dict) and boundaries.get("zones"):
        coverage = boundaries.get("coverage")
        if not (isinstance(coverage, dict) and coverage.get("requireAllFiles") is True):
            hits.append(
                "boundaries must set coverage.requireAllFiles to true, so no file escapes its zones"
            )
        allowed = coverage.get("allowUnmatched") if isinstance(coverage, dict) else None
        if isinstance(allowed, list) and covers_every_file(directory, allowed):
            hits.append(
                "boundaries.coverage.allowUnmatched covers every file, so no file has to belong to a zone; list only the files that belong to none"
            )
    return hits


NATIVE_FORMS = (
    ("capacitor.config.*", r"""['"]{name}['"]\s*:"""),
    ("AndroidManifest.xml", r"""=\s*["'][^"']*{name}"""),
    ("Podfile", r"^\s*pod\s.*{name}"),
    ("Package.swift", r"^\s*\.package\(.*{name}"),
    ("*.gradle", r"^\s*(?!//).*\bproject\(.*{name}"),
    ("*.gradle.kts", r"^\s*(?!//).*\bproject\(.*{name}"),
)
NATIVE_TWINS = {
    "@capacitor/ios": "capacitor-swift-pm",
    "@capacitor/android": "capacitor-android",
}
WHOLE = r"(?<![\w@.-]){}(?![\w-])"


BLOCK_COMMENTS = re.compile(r"/\*.*?\*/|<!--.*?-->", re.DOTALL)


def without_comments(text: str, file_name: str) -> str:
    """The text with its comments cut out; a comment marker inside a quoted string, such as the `//` of a URL, stays."""
    marker = "#" if file_name == "Podfile" else "//"
    cleaned: list[str] = []
    for line in BLOCK_COMMENTS.sub(" ", text).splitlines():
        quote = ""
        for at, char in enumerate(line):
            if quote:
                quote = "" if char == quote else quote
            elif char in "'\"":
                quote = char
            elif line.startswith(marker, at):
                line = line[:at]
                break
        cleaned.append(line)
    return "\n".join(cleaned)


def native_lines(directory: Path) -> list[tuple[str, list[str]]]:
    """For each tracked native or config file, the patterns of its real dependency forms and its lines; native files count only in a platform folder."""
    listed = subprocess.run(
        [*GIT_LISTING, "ls-files", "-z"],
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split("\0")
    found = []
    for name in listed:
        path = PurePosixPath(name)
        for pattern, form in NATIVE_FORMS:
            config = pattern.startswith("capacitor.config")
            platform = {part.lower() for part in path.parts[:-1]} & {"ios", "android"}
            if fnmatch(path.name, pattern) and (config or platform):
                text = (directory / name).read_text(errors="replace")
                found.append((form, without_comments(text, path.name).splitlines()))
    return found


def named_in_native_files(directory: Path) -> Callable[[str], bool]:
    """A check that a package is used through a real dependency form (a pod, a Swift package, a Gradle project, a manifest value or a Capacitor plugin key) in a platform folder or the Capacitor config, where a package can be used without a JavaScript import."""
    files = native_lines(directory)

    def used(package: str) -> bool:
        for name in (package, NATIVE_TWINS.get(package, package)):
            word = WHOLE.format(re.escape(name))
            for form, lines in files:
                regex = re.compile(form.replace("{name}", word))
                if any(regex.search(line) for line in lines):
                    return True
        return False

    return used


def untracked_configs(directory: Path) -> list[str]:
    """A Fallow settings file that Git does not track: a script can write it just before the run."""
    hits = []
    for name in sorted(FALLOW_CONFIGS):
        path = directory / name
        if path.is_file() and not committed(directory, path):
            hits.append(
                f"{name} is not tracked by Git: commit it, because a file that a script writes can change what Fallow reports"
            )
    return hits


def fallow_hits(
    directory: Path,
    config: str | None,
    children: frozenset[str],
    defaults: dict[str, object],
    timeout: float,
    proof: tuple[list[str], str | None] = ([], None),
) -> list[str]:
    printed = printed_config(directory, config, timeout)
    checked = listed_files(directory, config, timeout)
    left = left_out(directory, FALLOW_SUFFIXES, checked, children, FALLOW_SKIPPED)
    drop = pattern_hits(directory, children)
    found = entry_sources(directory, printed, timeout) if printed.get("entry") else {}
    covered = covering(checked, found)
    return [
        *judge(printed, defaults, drop, covered, named_in_native_files(directory)),
        *proved_hits(printed, directory, proof),
        *untracked_configs(directory),
        *refusal(left),
    ]
