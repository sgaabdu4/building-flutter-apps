"""Split a pytest tests gate over CI shards; only a shard run or a full check loads this."""

import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import cast

from ci_jobs import CHECKOUT, IMPACT_BASE, LINUX_HEADER
from coverage_sources import coverage_file, file_sections
from gate_config import Gate, GateConfig, Group
from process_group import run_in_group
from reports import junit_root
from retry_forms import PYTEST_FILES

COLLECTED_FILE = re.compile(r"^(\S.*): [0-9]+$", re.MULTILINE)
KEPT = "coverage/shards"
PROVEN = "proven.txt"
RAN = "ran.txt"
RELEASE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
MINIMUM_DECIMALS_FROM = (7, 17, 1)
PYTEST_FILE = "Move those settings to a file that pytest reads with no option."
COVERAGE_FILE = "a file that coverage.py reads with no option."
MOVED_OPTIONS = {
    "-c": PYTEST_FILE,
    "--config-file": PYTEST_FILE,
    "--cov-config": f"Move those settings to {COVERAGE_FILE}",
    "--cov-precision": "Set precision in the settings file of coverage.py.",
}
OVERRIDE_OPTIONS = ("-o", "--override-ini")
OVERRIDE_STEP = "Put those options in the tests command."
MOVED_VARIABLES = {
    "PYTEST_ADDOPTS": "Remove the variable and put its options in the tests command.",
    "COVERAGE_RCFILE": f"Remove the variable and move its settings to {COVERAGE_FILE}",
}
SHORT_CONFIG = re.compile(r"-c(?!-)")
CHECK_LINE = re.compile(r'(\.hooks/hard-eng\.py check --base "\$BASE_SHA")')
JOB_NAME = re.compile(r"(?m)^  ([\w-]+):\n")
SHARD_LIST = re.compile(r"(?m)^(        shard: \[)[^\]]*\]$")
UPLOAD = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1"
DOWNLOAD = "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1"
HEADER = "  hard-eng:\n    name: hard-eng\n"
CHECKS_HEADER = "  checks:\n    name: hard-eng-checks\n"
UPLOAD_STEP = f"""      - name: Keep the shard reports
        uses: {UPLOAD}
        with:
          name: hard-eng-shard-${{{{ matrix.shard }}}}
          path: {KEPT}
          retention-days: 1
          overwrite: true
          if-no-files-found: ignore
"""
GATE_JOB = (
    HEADER
    + "    needs: [checks, tests]\n    if: ${{ !cancelled() }}\n"
    + LINUX_HEADER
    + f"""    timeout-minutes: 5
    steps:
%s      - uses: {DOWNLOAD}
        with:
          pattern: hard-eng-shard-*
          merge-multiple: true
          path: {KEPT}
      - name: Merge the test shards
        env:
          CHECKS: ${{{{ needs.checks.result }}}}
          TESTS: ${{{{ needs.tests.result }}}}
"""
    + IMPACT_BASE
    + """          GH_TOKEN: ${{ github.token }}
        run: |
          if [ "$CHECKS" != success ] || [ "$TESTS" != success ]; then
            echo "checks: $CHECKS, tests: $TESTS"
            exit 1
          fi
          python3 .hooks/hard-eng.py check --base "$BASE_SHA" --shard merge
"""
)
SHARD_NOTE = (
    "CI shards not added: .github/workflows/hard-eng.yml is customised or split. "
    "Split its hard-eng job into the checks, tests and hard-eng jobs of Hard "
    "Eng's own workflow, or remove shards."
)
UNSPLIT_NOTE = (
    "CI shards not removed: .github/workflows/hard-eng.yml is customised. Join its "
    "checks, tests and hard-eng jobs into the one hard-eng job of Hard Eng's own "
    "workflow."
)


def split(sizes: dict[str, int], count: int) -> list[list[str]]:
    """Largest file first, each to the lightest shard; a tie goes to the lowest shard."""
    parts: list[list[str]] = [[] for _ in range(count)]
    loads = [0] * count
    for path, size in sorted(sizes.items(), key=lambda item: (-item[1], item[0])):
        lightest = loads.index(min(loads))
        parts[lightest].append(path)
        loads[lightest] += size
    return [sorted(part) for part in parts]


def require_pytest(groups: list[Group]) -> None:
    for group in groups:
        if sum("shards" in gate for gate in group["checks"]) > 1:
            raise ValueError(
                f'{group["path"]}: only one gate of a package can hold "shards". '
                'Remove "shards" from all but one tests gate in hard-eng.gates.json.'
            )
        for gate in group["checks"]:
            direct = (
                gate.get("report", {}).get("type") == "python-tests"
                and "pytest" in gate["command"]
            )
            if "shards" in gate and not direct:
                raise ValueError(
                    f"{group['path']}/{gate['name']}: shards split pytest suites only, "
                    "and the command must run pytest directly. "
                    'Remove "shards" from this gate in hard-eng.gates.json.'
                )


def pick(
    groups: list[Group], keep: Callable[[Group, Gate], Gate | None]
) -> list[Group]:
    """Groups holding only the gates `keep` returns; a group left with none is dropped."""
    chosen = [
        (group, [keep(group, gate) for gate in group["checks"]]) for group in groups
    ]
    return [
        {**group, "checks": [gate for gate in gates if gate is not None]}
        for group, gates in chosen
        if any(gate is not None for gate in gates)
    ]


def shard_groups(groups: list[Group], shard: str) -> list[Group]:
    """The groups of one `check --shard` run; a kept tests gate carries its part."""
    require_pytest(groups)
    if shard == "rest":
        return pick(groups, lambda _group, gate: None if "shards" in gate else gate)
    if shard == "merge":
        return pick(
            groups,
            lambda _group, gate: {**gate, "part": shard} if "shards" in gate else None,
        )
    number = int(shard)
    homes = [
        PurePosixPath(group["path"])
        for group in groups
        if any(gate.get("shards", 0) >= number for gate in group["checks"])
    ]

    def keep(group: Group, gate: Gate) -> Gate | None:
        if gate.get("shards", 0) >= number:
            return {**gate, "part": shard}
        above = any(PurePosixPath(group["path"]) in (p, *p.parents) for p in homes)
        return gate if above and gate.get("role") == "lockfiles" else None

    return pick(groups, keep)


def mark_shard(root: Path, part: str, proven: bool) -> None:
    """Leave one file in the folder of a numbered shard, so that its upload is never empty."""
    if part.isdecimal():
        folder = root / KEPT / part
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (PROVEN if proven else RAN)).write_text("ok\n")


def proven_shard(root: Path) -> bool:
    """A numbered shard whose own job proved this tree elsewhere covers the gate job."""
    found = sorted((root / KEPT).glob(f"*/{PROVEN}"))
    if found:
        print(
            f"Shard {found[0].parent.name} proved this tree in its own job; "
            "not merging the shard reports.",
            flush=True,
        )
    return bool(found)


def shard_folder(root: Path, part: str, group: Group) -> Path:
    return root / KEPT / part / group["path"]


def runner_arguments(command: list[str]) -> list[str]:
    return command[len(command) - command[::-1].index("pytest") :]


def named_path(directory: Path, arguments: list[str]) -> str | None:
    """The first argument that names a test folder or a Python file."""
    for argument in arguments:
        named = directory / argument.split("::")[0]
        if not argument.startswith("-") and (
            named.is_dir() or (named.is_file() and named.suffix == ".py")
        ):
            return argument
    return None


def require_no_path(root: Path, group: Group, gate: Gate, command: list[str]) -> None:
    name, addopts = pytest_addopts(root / group["path"])
    for arguments, subject, place in (
        (runner_arguments(command), "the command", "the command"),
        (addopts, f"addopts in {name}", "addopts"),
    ):
        if argument := named_path(root / group["path"], arguments):
            raise ValueError(
                f"{group['path']}/{gate['name']}: {subject} names the path "
                f'"{argument}", so every shard would run it whole. Remove the path '
                f"from {place} and list it in testpaths in the pytest settings. "
                "If it is the value of an option, write it as --option=value "
                "(for example --cov=src)."
            )


def override_given(arguments: list[str], index: int) -> tuple[str, str] | None:
    """The option and the setting that a -o or --override-ini item gives, in each written form."""
    argument = arguments[index]
    if argument.startswith("--override-ini="):
        return "--override-ini", argument.partition("=")[2]
    if argument.startswith("-o") and not argument.startswith("--") and argument != "-o":
        return "-o", argument[2:]
    if argument in OVERRIDE_OPTIONS:
        return argument, "".join(arguments[index + 1 : index + 2])
    return None


def moved_option(arguments: list[str]) -> tuple[str, str] | None:
    """The first option that moves the pytest or coverage.py settings, as the refusal names it, with its step."""
    for index, argument in enumerate(arguments):
        name = "-c" if SHORT_CONFIG.match(argument) else argument.partition("=")[0]
        if name in MOVED_OPTIONS:
            return name, MOVED_OPTIONS[name]
        override = override_given(arguments, index)
        if override and override[1].partition("=")[0] == "addopts":
            return f"{override[0]} addopts", OVERRIDE_STEP
    return None


def require_default_settings(
    root: Path, group: Group, gate: Gate, command: list[str], variables: bool = True
) -> None:
    """Refuse each option, and each variable when asked, that moves a settings file the shard merge reads."""
    prefix = f"{group['path']}/{gate['name']}: "
    name, addopts = pytest_addopts(root / group["path"])
    gives = [
        (f"the environment sets {variable}", step)
        for variable, step in MOVED_VARIABLES.items()
        if variables and os.environ.get(variable)
    ]
    for arguments, place in (
        (runner_arguments(command), "the tests command"),
        (addopts, f"addopts in {name}"),
    ):
        if option := moved_option(arguments):
            gives.append((f"{place} gives {option[0]}", option[1]))
    if gives:
        what, step = gives[0]
        raise ValueError(
            f"{prefix}{what}, which moves the pytest or coverage.py settings. "
            "The shard merge reads the settings only from the tests command and "
            "from the files that pytest and coverage.py read with no option. "
            f'{step} Or remove "shards" from this gate in hard-eng.gates.json.'
        )


def collected(
    root: Path, group: Group, gate: Gate, command: list[str], timeout: float
) -> tuple[Path, dict[str, int]]:
    """The folder pytest reports from and the size of each file the gate command collects."""
    parallel = any(
        argument.startswith(("-n", "--numprocesses"))
        for argument in runner_arguments(command)
    )
    listing = [
        *command,
        "--collect-only",
        "--verbosity=-2",
        *(["-n", "0"] if parallel else []),
    ]
    result = run_in_group(
        listing,
        cwd=root / group["path"],
        timeout=timeout,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    names = COLLECTED_FILE.findall(result.stdout)
    bases = [
        base
        for base in (root / group["path"], *(root / group["path"]).parents)
        if all((base / name).is_file() for name in names)
    ]
    if (
        result.returncode not in (0, 5)
        or not bases
        or (not names and not result.returncode)
    ):
        raise ValueError(
            f"{group['path']}/{gate['name']}: pytest could not list the tests of this "
            "shard, so the shard did not start. Run the tests command with "
            "--collect-only --verbosity=-2 to see the cause.\n" + result.stdout
        )
    return bases[0], {name: (bases[0] / name).stat().st_size for name in names}


def pytest_addopts(directory: Path) -> tuple[str, list[str]]:
    """The settings file that pytest reads for a run in this folder, by pytest's own search, with its addopts arguments."""
    import shlex

    folder = directory.resolve()
    for base in (folder, *folder.parents):
        for name in PYTEST_FILES:
            if not (base / name).is_file():
                continue
            section = file_sections(base / name)
            if name == "pyproject.toml":
                table = section("tool.pytest") or {}
                legacy = table.get("ini_options")
                native = {key: table[key] for key in table if key != "ini_options"}
                found = native or (legacy if isinstance(legacy, dict) else None)
            else:
                found = section("tool:pytest" if name == "setup.cfg" else "pytest")
            if found is None and not name.endswith(("pytest.toml", "pytest.ini")):
                continue
            value = (found or {}).get("addopts", [])
            return (
                os.path.relpath(base / name, folder),
                [str(item) for item in value]
                if isinstance(value, list)
                else shlex.split(str(value)),
            )
    return "", []


def option_value(arguments: list[str], option: str) -> str | None:
    """The last value of an option that the arguments give as --option=value or as two items."""
    found = None
    for index, argument in enumerate(arguments):
        if argument.startswith(option + "="):
            found = argument.partition("=")[2]
        elif argument == option and index + 1 < len(arguments):
            found = arguments[index + 1]
    return found


def uses_coverage(directory: Path, command: list[str]) -> bool:
    """pytest-cov takes every --cov option, so one in the command or in pytest's addopts shows it runs."""
    arguments = [*pytest_addopts(directory)[1], *runner_arguments(command)]
    return any(argument.startswith("--cov") for argument in arguments)


def part_command(
    root: Path,
    group: Group,
    gate: Gate,
    command: list[str],
    coverage: Path | None,
    timeout: float,
) -> tuple[list[str], Path | None]:
    """The command of one shard: the gate command and the files of that shard."""
    require_default_settings(root, group, gate, command)
    if gate["part"] == "merge":
        merge_reports(root, group, gate, command)
        return [], coverage
    require_no_path(root, group, gate, command)
    base, sizes = collected(root, group, gate, command, timeout)
    names = split(sizes, gate["shards"])[int(gate["part"]) - 1]
    folder = shard_folder(root, gate["part"], group)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "shard-files.txt").write_text("".join(f"{name}\n" for name in names))
    for name in (gate["report"]["tests"], gate["report"]["coverage"]):
        (root / group["path"] / name).unlink(missing_ok=True)
    held = (
        ["--cov-fail-under=0"] if uses_coverage(root / group["path"], command) else []
    )
    return (
        [*command, *held, *(str(base / name) for name in names)] if names else []
    ), None


def keep_reports(root: Path, group: Group, gate: Gate) -> None:
    """Move the reports of a numbered shard beside its file list, away from the normal paths."""
    if not gate["part"].isdecimal():
        return
    folder = shard_folder(root, gate["part"], group)
    for name in (gate["report"]["tests"], gate["report"]["coverage"]):
        source = root / group["path"] / name
        if source.is_file():
            (folder / name).parent.mkdir(parents=True, exist_ok=True)
            source.replace(folder / name)


type Entry = dict[str, list[int] | list[list[int]]]


def lines(entries: list[Entry], key: str) -> set[int]:
    return {n for entry in entries for n in cast(list[int], entry.get(key, []))}


def pairs(entries: list[Entry], key: str) -> set[tuple[int, int]]:
    return {
        (start, end)
        for entry in entries
        for start, end in cast(list[list[int]], entry.get(key, []))
    }


def merge_file(entries: list[Entry]) -> dict[str, object]:
    """Lines and branches that ran in any shard count as run."""
    run = lines(entries, "executed_lines")
    missed = lines(entries, "missing_lines") - run
    excluded = lines(entries, "excluded_lines")
    taken = pairs(entries, "executed_branches")
    untaken = pairs(entries, "missing_branches") - taken
    return {
        "executed_lines": sorted(run),
        "missing_lines": sorted(missed),
        "excluded_lines": sorted(excluded),
        "executed_branches": [list(pair) for pair in sorted(taken)],
        "missing_branches": [list(pair) for pair in sorted(untaken)],
        "summary": {
            "covered_lines": len(run),
            "num_statements": len(run | missed),
            "missing_lines": len(missed),
            "excluded_lines": len(excluded),
            "num_branches": len(taken | untaken),
            "covered_branches": len(taken),
            "missing_branches": len(untaken),
        },
    }


def merge_coverage(reports: list[dict[str, object]]) -> dict[str, object]:
    """One coverage report from the shard reports; a file only some shards list comes from them."""
    seen: dict[str, list[Entry]] = {}
    for report in reports:
        for name, entry in cast(dict[str, Entry], report["files"]).items():
            seen.setdefault(name, []).append(entry)
    meta = reports[0].get("meta") if reports else None
    return {"meta": meta, "files": {n: merge_file(e) for n, e in seen.items()}}


def merge_junit(paths: list[Path], target: Path) -> None:
    merged = ET.Element("testsuites")
    for path in paths:
        part = junit_root(path)
        merged.extend([part] if part.tag == "testsuite" else list(part))
    ET.ElementTree(merged).write(target, encoding="utf-8", xml_declaration=True)


def coverage_settings(directory: Path) -> tuple[str, float, int] | None:
    """The file coverage.py reads, with its fail_under and precision."""
    found = coverage_file(directory)
    if found is None:
        return None
    report = found[1]("report") or {}
    return (
        found[0],
        float(str(report.get("fail_under", 0))),
        int(str(report.get("precision", 0))),
    )


def coverage_minimum(directory: Path, command: list[str]) -> tuple[float, str, int]:
    """The minimum, the place that sets it and the precision; the command beats pytest's addopts, then coverage's file."""
    settings = coverage_settings(directory)
    precision = settings[2] if settings else 0
    name, addopts = pytest_addopts(directory)
    for arguments, place in (
        (runner_arguments(command), "the tests command"),
        (addopts, name),
    ):
        given = option_value(arguments, "--cov-fail-under")
        if given is not None:
            return float(given), f"--cov-fail-under in {place}", precision
    if settings and settings[1]:
        return settings[1], f"fail_under in {settings[0]}", precision
    return 0.0, "", precision


def merged_total(report: dict[str, object]) -> float:
    """The total percent that coverage.py reports: lines and branches over statements and branches."""
    summaries = [
        cast(dict[str, int], entry["summary"])
        for entry in cast(dict[str, dict[str, object]], report["files"]).values()
    ]
    covered = sum(s["covered_lines"] + s.get("covered_branches", 0) for s in summaries)
    count = sum(s["num_statements"] + s.get("num_branches", 0) for s in summaries)
    return 100.0 * covered / count if count else 100.0


def reports_release(report: dict[str, object]) -> str | None:
    """The coverage.py release that wrote a report, when it says."""
    meta = report.get("meta")
    version = meta.get("version") if isinstance(meta, dict) else None
    return version if isinstance(version, str) else None


def effective_precision(minimum: float, precision: int, release: str | None) -> int:
    """The decimal places that coverage.py judges with: from 7.17.1 at least those of the minimum."""
    found = RELEASE.match(release or "")
    if not found or tuple(map(int, found.groups())) < MINIMUM_DECIMALS_FROM:
        return precision
    if minimum == int(minimum):
        return precision
    exponent = Decimal(str(minimum)).as_tuple().exponent
    return max(precision, -int(exponent))


def below_minimum(
    total: float, minimum: float, precision: int, release: str | None
) -> bool:
    """The rule of coverage.py's should_fail_under for the release: a minimum of 100 needs exactly 100."""
    if minimum == 100.0 and total != 100.0:
        return True
    return round(total, effective_precision(minimum, precision, release)) < minimum


def shown(total: float, precision: int) -> str:
    """The total as coverage.py prints it: never 0 or 100 unless the total is exactly that."""
    near = 1.0 / 10**precision
    if 0 < total < near:
        total = near
    elif 100.0 - near < total < 100:
        total = 100.0 - near
    return f"{round(total, precision):.{precision}f}"


def merge_reports(root: Path, group: Group, gate: Gate, command: list[str]) -> None:
    """Write the merged test and coverage reports of shards 1 to N at the gate's report paths."""
    report, count = gate["report"], gate["shards"]
    tests: list[Path] = []
    coverage: list[dict[str, object]] = []
    for number in range(1, count + 1):
        folder = shard_folder(root, str(number), group)
        listed = folder / "shard-files.txt"
        kept = [folder / report["tests"], folder / report["coverage"]]
        empty = listed.is_file() and not listed.read_text().strip()
        if not listed.is_file() or not (empty or all(path.is_file() for path in kept)):
            raise ValueError(
                f"Shard {number} of {count} for {group['path']}/{gate['name']} sent no "
                f"reports. List shards 1 to {count} in the tests job of "
                ".github/workflows/hard-eng.yml (setup writes it), then rerun all jobs of the workflow."
            )
        if not empty:
            tests.append(kept[0])
            coverage.append(json.loads(kept[1].read_text()))
    directory = root / group["path"]
    merge_junit(tests, directory / report["tests"])
    merged = merge_coverage(coverage)
    (directory / report["coverage"]).write_text(json.dumps(merged))
    minimum, origin, precision = coverage_minimum(directory, command)
    total = merged_total(merged)
    release = reports_release(merged)
    if below_minimum(total, minimum, precision, release):
        digits = effective_precision(minimum, precision, release)
        raise ValueError(
            f"{group['path']}/{gate['name']}: the merged coverage total is "
            f"{shown(total, digits)}%, below the minimum of {minimum:g}% that "
            f"{origin} sets. Add tests, or lower that minimum."
        )


def split_job(content: str, numbers: str) -> str | None:
    """The one-job workflow as checks, one tests job per shard and the gate job; None when it is not the generated one-job form."""
    names = JOB_NAME.findall(content.partition("\njobs:\n")[2])
    start, checkout = content.find(HEADER), CHECKOUT.search(content)
    if (
        names != ["hard-eng"]
        or start < 0
        or checkout is None
        or len(CHECK_LINE.findall(content)) != 2
        or "\n    env:\n" not in content
    ):
        return None
    rest = content[start + len(HEADER) :].rstrip("\n") + "\n"
    checks = CHECK_LINE.sub(lambda match: match[1] + " --shard rest", rest)
    tests = CHECK_LINE.sub(lambda match: match[1] + ' --shard "$SHARD"', rest)
    tests = tests.replace(
        "    env:\n", "    env:\n      SHARD: ${{ matrix.shard }}\n", 1
    )
    return (
        content[:start]
        + CHECKS_HEADER
        + checks
        + "\n  tests:\n    name: hard-eng-tests ${{ matrix.shard }}\n"
        + f"    strategy:\n      fail-fast: false\n      matrix:\n        shard: [{numbers}]\n"
        + tests
        + UPLOAD_STEP
        + "\n"
        + GATE_JOB % checkout[0]
    )


def one_job(content: str) -> str:
    """The one-job workflow back from the generated split form; any other workflow is unchanged."""
    shards = SHARD_LIST.search(content)
    head, found, rest = content.partition(CHECKS_HEADER)
    if shards is None or not found:
        return content
    body = rest.partition("\n  tests:\n")[0].replace(" --shard rest", "")
    restored = head + HEADER + body
    numbers = content[shards.end(1) : shards.end() - 1]
    return restored if split_job(restored, numbers) == content else content


def split_test_shards(config: GateConfig, content: str) -> str:
    """The one-job workflow as checks, one tests job per shard and the required hard-eng job."""
    count = max(
        (
            gate.get("shards", 0)
            for group in config["packages"]
            for gate in group["checks"]
        ),
        default=0,
    )
    if not count:
        restored = one_job(content)
        if restored == content and CHECKS_HEADER in content:
            print(UNSPLIT_NOTE, file=sys.stderr)
        return restored
    require_pytest(config["packages"])
    numbers = ", ".join(str(number) for number in range(1, count + 1))
    names = JOB_NAME.findall(content.partition("\njobs:\n")[2])
    if names == ["checks", "tests", "hard-eng"]:
        return SHARD_LIST.sub(lambda match: match[1] + numbers + "]", content)
    split = split_job(content, numbers)
    if split is None:
        print(SHARD_NOTE, file=sys.stderr)
        return content
    return split
