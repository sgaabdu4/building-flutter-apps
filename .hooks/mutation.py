"""Report changed lines whose tests still pass after a small deliberate bug."""

import ast
import fnmatch
import json
import os
import re
import shlex
import signal
import subprocess
import tempfile
import time
import tokenize
import xml.etree.ElementTree as ET
from collections.abc import Callable
from contextlib import suppress
from io import StringIO
from pathlib import Path

from gate_config import Group, parse_config
from project_setup import python_gate_command

GLOB = re.compile(r"[?*()[\]]")
HUNK = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
STACK_FRAME = re.compile(r"\s+at ")
LISTED = 20
Survivor = tuple[str, int, str]
Result = tuple[int, list[Survivor]]
Adapter = Callable[[Path, dict[str, set[int]], list[str], float | None, Path], Result]


class Capped(Exception):
    pass


def changed_lines(diff: str) -> dict[str, set[int]]:
    """New-side line numbers of each added or modified file in a -U0 diff."""
    changed: dict[str, set[int]] = {}
    path = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:].rstrip("\t") if line.startswith("+++ b/") else None
        elif path and (match := HUNK.match(line)):
            start, count = int(match[1]), int(match[2] or 1)
            changed.setdefault(path, set()).update(range(start, start + count))
    return {path: lines for path, lines in changed.items() if lines}


def ranges(lines: set[int]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for line in sorted(lines):
        if spans and spans[-1][1] == line - 1:
            spans[-1] = (spans[-1][0], line)
        else:
            spans.append((line, line))
    return spans


def run(
    command: list[str],
    directory: Path,
    deadline: float | None,
    output: Path,
) -> int:
    """Run in its own group so the cap stops every runner the tool started."""
    with output.open("a") as log:
        process = subprocess.Popen(
            command,
            cwd=directory,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            remaining = None if deadline is None else deadline - time.monotonic()
            return process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            raise Capped from None
        finally:
            if process.poll() is None:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()


def failed(tool: str, output: Path) -> ValueError:
    lines = output.read_text(errors="replace").strip().splitlines()
    tail = [line for line in lines if not STACK_FRAME.match(line)][-15:]
    return ValueError(f"{tool} did not finish:\n" + "\n".join(tail))


def mutated_line(source: str, mutant: dict[str, object]) -> str:
    location, replacement = mutant["location"], mutant["replacement"]
    if not isinstance(location, dict) or not isinstance(replacement, str):
        raise TypeError("Stryker reported a mutant without a location")
    start, end = location["start"], location["end"]
    lines = source.splitlines()
    original = lines[start["line"] - 1]
    if start["line"] != end["line"]:
        return f"{original.strip()} → {replacement.splitlines()[0].strip()} …"
    changed = (
        original[: start["column"] - 1] + replacement + original[end["column"] - 1 :]
    )
    return f"{original.strip()} → {changed.strip()}"


def stryker_survivors(report: object) -> Result:
    if not isinstance(report, dict) or not isinstance(report.get("files"), dict):
        raise TypeError("Stryker wrote no file results")
    tested, survivors = 0, list[Survivor]()
    for name, file in report["files"].items():
        for mutant in file["mutants"]:
            status = mutant["status"]
            tested += status in {"Killed", "Survived", "NoCoverage", "Timeout"}
            if status in {"Survived", "NoCoverage"}:
                line = mutant["location"]["start"]["line"]
                survivors.append((name, line, mutated_line(file["source"], mutant)))
    return tested, survivors


def javascript(
    directory: Path,
    files: dict[str, set[int]],
    tests: list[str],
    deadline: float | None,
    work: Path,
) -> Result:
    from tool_setup import provision_batch

    remaining = 600 if deadline is None else max(deadline - time.monotonic(), 1)
    provision_batch(directory, ["npm:@stryker-mutator/core@latest"], remaining)
    report, config, output = work / "report.json", work / "stryker.json", work / "log"
    # Stryker reads each path as a minimatch glob; brackets wrap its metacharacters.
    literal = {name: GLOB.sub(r"[\g<0>]", name) for name in files}
    mutate = [
        f"{literal[name]}:{a}-{b}" for name in files for a, b in ranges(files[name])
    ]
    config.write_text(
        json.dumps(
            {
                "testRunner": "command",
                "commandRunner": {"command": shlex.join(tests)},
                "mutate": mutate,
                "mutator": {"excludedMutations": ["StringLiteral"]},
                "reporters": ["json"],
                "jsonReporter": {"fileName": str(report)},
                "cleanTempDir": True,
                # The checkout is disposable; in place skips the tsconfig rewrite that imports typescript.
                "inPlace": True,
                # Backups stay outside the package, where test runners cannot discover them.
                "tempDirName": str(work / "stryker"),
            }
        )
    )
    run(["stryker", "run", str(config)], directory, deadline, output)
    if not report.is_file():
        raise failed("Stryker", output)
    return stryker_survivors(json.loads(report.read_text()))


def module_name(name: str) -> str:
    parts = list(Path(name).with_suffix("").parts)
    parts = parts[1:] if parts[0] == "src" else parts
    if not parts or not all(part.isidentifier() for part in parts):
        raise ValueError(
            f"mutmut imports mutated code as modules, and {name} is not an importable module path"
        )
    return ".".join(parts)


def changed_functions(
    name: str, source: str, lines: set[int]
) -> dict[str, tuple[str, dict[str, int]]]:
    """mutmut mutant-name globs for functions and methods holding changed lines."""
    tree, text = ast.parse(source), source.splitlines()
    functions = (ast.FunctionDef, ast.AsyncFunctionDef)
    found: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []
    for node in tree.body:
        if isinstance(node, functions):
            found.append(("x_", node))
        elif isinstance(node, ast.ClassDef):
            found += [
                (f"xǁ{node.name}ǁ", item)
                for item in node.body
                if isinstance(item, functions)
            ]
    globs = {}
    for prefix, node in found:
        first = min([node.lineno, *(item.lineno for item in node.decorator_list)])
        inside = lines & set(range(first, (node.end_lineno or node.lineno) + 1))
        if inside:
            pattern = f"{module_name(name)}.{prefix}{node.name}__mutmut_*"
            content = {
                text[line - 1].strip(): line for line in sorted(inside, reverse=True)
            }
            globs[pattern.replace(".__init__.", ".")] = (name, content)
    return globs


def mutmut_statuses(results: str, globs: list[str]) -> dict[str, str]:
    statuses = {}
    for line in results.splitlines():
        name, _, status = line.strip().rpartition(": ")
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in globs):
            statuses[name] = status
    return {
        name: status
        for name, status in statuses.items()
        if status not in {"not checked", "skipped", "check was interrupted by user"}
    }


def shape(line: str) -> list[str]:
    tokens = []
    with suppress(tokenize.TokenError, SyntaxError):
        for token in tokenize.generate_tokens(StringIO(line).readline):
            if token.type in {tokenize.STRING, tokenize.FSTRING_MIDDLE}:
                tokens.append("<text>")
            elif token.type not in {tokenize.NEWLINE, tokenize.NL, tokenize.ENDMARKER}:
                tokens.append(token.string)
    return tokens


def text_only(original: str, mutated: str) -> bool:
    """A change to text or an exception message, which tests rarely pin."""
    before, after = shape(original), shape(mutated)
    if not before or before == after:
        return bool(before)
    raising = original.startswith("raise ") and mutated.startswith("raise ")
    kept = [token for token in before if token != "<text>"]
    return raising and kept == [t for t in after if t not in {"<text>", "None"}]


def mutmut_change(diff: str) -> tuple[str, str]:
    removed = [
        line[1:].strip()
        for line in diff.splitlines()
        if line.startswith("-") and not line.startswith("---")
    ]
    added = [
        line[1:].strip()
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    if not removed:
        raise ValueError("mutmut showed a mutant without a changed line")
    return removed[0], added[0] if added else ""


def mutmut(manager: str, *arguments: str) -> list[str]:
    return python_gate_command(["mutmut", *arguments], manager)


def python(
    directory: Path,
    files: dict[str, set[int]],
    tests: list[str],
    deadline: float | None,
    work: Path,
) -> Result:
    globs: dict[str, tuple[str, dict[str, int]]] = {}
    for name, lines in files.items():
        globs |= changed_functions(name, (directory / name).read_text(), lines)
    if not globs:
        return 0, []
    manager = "poetry" if tests[0] == "poetry" else "uv"
    output, listing = work / "log", work / "results"
    if run(mutmut(manager, "run", *globs), directory, deadline, output) or run(
        mutmut(manager, "results", "--all", "true"), directory, deadline, listing
    ):
        raise failed("mutmut", output)
    statuses = mutmut_statuses(listing.read_text(), list(globs))
    survivors: list[Survivor] = []
    for index, (mutant, status) in enumerate(statuses.items()):
        if status not in {"survived", "no tests"}:
            continue
        shown = work / f"show-{index}"
        run(mutmut(manager, "show", mutant), directory, deadline, shown)
        original, mutated = mutmut_change(shown.read_text())
        file, content = next(
            globs[pattern] for pattern in globs if fnmatch.fnmatchcase(mutant, pattern)
        )
        if original in content and not text_only(original, mutated):
            survivors.append((file, content[original], f"{original} → {mutated}"))
    return len(statuses), survivors


def xunit_survivors(document: str) -> Result:
    tested, survivors = 0, list[Survivor]()
    for case in ET.fromstring(document).iter("testcase"):
        tested += 1
        failure = case.find("failure")
        if failure is None or failure.get("type") != "undetected":
            continue
        fields = dict(
            line.split(": ", 1)
            for line in (failure.text or "").splitlines()
            if ": " in line
        )
        change = f"{fields['Original line'].strip()} → {fields['Mutation'].strip()}"
        survivors.append((fields["File"].strip(), int(fields["Line"]), change))
    return tested, survivors


def dart(
    directory: Path,
    files: dict[str, set[int]],
    tests: list[str],
    deadline: float | None,
    work: Path,
) -> Result:
    output = work / "log"
    if run(
        ["dart", "pub", "global", "activate", "mutation_test"],
        directory,
        deadline,
        output,
    ):
        raise failed("dart pub global activate mutation_test", output)
    document = ET.Element("mutations", version="1.2")
    listing = ET.SubElement(document, "files")
    for name, lines in files.items():
        file = ET.SubElement(listing, "file")
        file.text = name
        for begin, end in ranges(lines):
            ET.SubElement(file, "lines", begin=str(begin), end=str(end))
    command = ET.SubElement(
        ET.SubElement(document, "commands"),
        "command",
        {
            "group": "test",
            "expected-return": "0",
            "working-directory": ".",
            "timeout": "3600",
        },
    )
    flutter = "flutter test" in " ".join(tests)
    command.text = "flutter test --no-pub" if flutter else "dart test"
    config = work / "mutations.xml"
    ET.ElementTree(document).write(config, encoding="unicode")
    run(
        [
            "dart",
            "pub",
            "global",
            "run",
            "mutation_test",
            "--exclude-strings",
            "-f",
            "xunit",
            "-o",
            str(work / "report"),
            str(config),
        ],
        directory,
        deadline,
        output,
    )
    report = work / "report/mutation-test.xunit.xml"
    if not report.is_file():
        raise failed("mutation_test", output)
    return xunit_survivors(report.read_text())


ADAPTERS: dict[str, Adapter] = {
    "javascript": javascript,
    "python": python,
    "dart": dart,
}


def summary(name: str, tested: int, survivors: list[Survivor], directory: Path) -> None:
    if not tested:
        print(f"{name}: no mutants on the changed lines.")
    elif not survivors:
        print(f"{name}: the tests caught every mutant ({tested}).")
    else:
        print(
            f"{name}: {len(survivors)} of {tested} mutants survived on changed lines; "
            "the tests still pass with these changes:"
        )
        for file, line, change in survivors[:LISTED]:
            print(f"  {directory / file}:{line}  {change}")
        if len(survivors) > LISTED:
            print(f"  … and {len(survivors) - LISTED} more")


def targets(
    root: Path, base: str, production: Callable[[Path, Group], set[Path]]
) -> list[tuple[Group, list[str], dict[str, set[int]]]]:
    """Packages with a supported language, a tests gate and changed production lines."""
    command = ["git", "-c", "core.quotePath=false", "diff", "-U0", "--no-color"]
    command += ["--no-ext-diff", "--no-renames", "--diff-filter=AM", base, "--"]
    diff = subprocess.run(command, cwd=root, capture_output=True, text=True, check=True)
    changed = changed_lines(diff.stdout)
    selected = []
    for group in parse_config((root / "hard-eng.gates.json").read_text())["packages"]:
        tests = [
            gate["command"] for gate in group["checks"] if gate.get("role") == "tests"
        ]
        if (
            group.get("language") not in ADAPTERS
            or not group.get("sources")
            or not tests
        ):
            continue
        directory = (root / group["path"]).resolve()
        files = {
            path.relative_to(directory).as_posix(): lines
            for path in production(directory, group)
            if (lines := changed.get(path.relative_to(root.resolve()).as_posix()))
        }
        if files:
            selected.append((group, tests[0], files))
    return selected


def report(
    root: Path,
    base: str,
    seconds: float | None,
    production: Callable[[Path, Group], set[Path]],
) -> int:
    """Print mutation results for each package's changed production lines; never fails."""
    deadline = None if seconds is None else time.monotonic() + seconds
    selected = targets(root, base, production)
    if selected:
        print(
            "Mutation testing (report only): small deliberate bugs on changed lines "
            "that the tests should catch.",
            flush=True,
        )
    for group, tests, files in selected:
        name = group.get("name", group["path"])
        try:
            with tempfile.TemporaryDirectory(prefix="hard-eng-mutation-") as work:
                adapter = ADAPTERS[group.get("language", "")]
                tested, survivors = adapter(
                    root / group["path"], files, tests, deadline, Path(work)
                )
        except Capped:
            print(
                f"Mutation testing stopped at its {seconds or 0:.0f}s limit before {name} "
                f"finished; run `python3 .hooks/hard-eng.py mutation --base {base}` "
                "for the full result.",
                flush=True,
            )
            return 0
        except (
            OSError,
            SyntaxError,
            TypeError,
            ValueError,
            KeyError,
            IndexError,
            subprocess.SubprocessError,
        ) as error:
            print(f"Mutation testing could not run for {name}: {error}", flush=True)
            continue
        summary(name, tested, survivors, Path(group["path"]))
    return 0
