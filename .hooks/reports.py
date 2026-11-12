"""Validate native test, coverage and scanner reports."""

import json
import math
import re
import subprocess
import tempfile
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import TextIO, cast

from coverage_sources import (
    erased_swift,
    erased_typescript,
    lcov_coverage,
    omit_step,
    python_coverage,
    xccov_coverage,
)
from dart_coverage import erased_dart
from dart_test_report import dart_events, failure_summary
from fallow_report import finding_lines as fallow_findings
from fallow_report import sdk_binaries, validate_fallow, write_istanbul
from gate_config import Gate, Group, JsonObject
from gate_schedule import QUICK_ROLES
from project_setup import (
    dependency_free,
    package_script_invocation,
)
from react_report import finding_lines as react_findings
from react_report import incomplete_reason
from scan_findings import (
    dart_performance_findings,
    decimate_findings,
    import_linter_findings,
    jscpd_findings,
    semgrep_findings,
    trivy_findings,
)

SHELL_OPERATOR = re.compile(r"[;&|]")
WARNINGS_LINE = re.compile(r"^Warnings$", re.MULTILINE)
SHA256_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
SCAN_PROGRESS_LINE = re.compile(r"Scanning [1-9][0-9]* files?\.\.\.")
DART_DECIMATE_VERSION = re.compile(r"dart-decimate( \d+\.\d+\.\d+\S*)?")
KEPT_OR_BROKEN_OUTCOME = re.compile(
    r"^.*\b(KEPT|BROKEN)(?: \([^\n]*\))?$", re.MULTILINE
)
CONTRACTS_SUMMARY = re.compile(
    r"^Contracts: ([0-9]+) kept, ([0-9]+) broken\.$", re.MULTILINE
)
ANALYZED_SUMMARY = re.compile(
    r"^Analyzed ([0-9]+) files, ([0-9]+) dependencies\.$", re.MULTILINE
)
EXPORT_PREFIX = re.compile(r"""(?:\s*export\s+(?:'[^'\r\n$]*'|"[^"\r\n$]*")\s*;\s*)+""")


def dart_test_failure(
    result: subprocess.CompletedProcess[bytes] | None,
    tests: bool,
    kind: str,
    path: Path | None,
) -> str | None:
    if result and result.returncode and tests and kind == "dart-tests" and path:
        return failure_summary(path)
    return None


def emit_dart_test_failure(
    result: subprocess.CompletedProcess[bytes] | None,
    tests: bool,
    kind: str,
    path: Path | None,
) -> None:
    if summary := dart_test_failure(result, tests, kind, path):
        print(summary)


def quick_groups(
    groups: list[Group], quick: bool = True, installed: frozenset[str] = frozenset()
) -> list[Group]:
    if not quick:
        return groups
    from process_group import INSTALL_ROLES, install_key

    return [
        {
            **group,
            "checks": [
                gate
                for gate in group["checks"]
                if gate.get("role") in QUICK_ROLES
                or (
                    gate.get("role") in INSTALL_ROLES
                    and install_key(group) not in installed
                )
            ],
        }
        for group in groups
    ]


def related_test_flags(
    gate: Gate, groups: list[Group], directory: Path, base: str
) -> list[str]:
    """Native related-test flags for a pre-push JavaScript test gate, else none."""
    if gate.get("report", {}).get("type") != "lcov-tests":
        return []
    # A Fallow gate run through a package script may read this run's coverage.
    if any(
        other.get("report", {}).get("type") == "fallow"
        and other["command"][:2] == ["bun", "run"]
        for selected in groups
        for other in selected["checks"]
    ):
        return []
    arguments, directory = package_script_invocation(gate["command"], directory)
    if any(SHELL_OPERATOR.search(argument) for argument in arguments):
        return []
    runner = Path(arguments[0]).name
    if arguments[:2] == ["bun", "test"]:
        bunfig = directory / "bunfig.toml"
        # Bun has no flag to lift a configured coverage threshold for a partial run.
        if bunfig.is_file() and "coverageThreshold" in tomllib.loads(
            bunfig.read_text()
        ).get("test", ()):
            return []
        return [f"--changed={base}", "--pass-with-no-tests"]
    if runner == "vitest":
        return ["--changed", base, "--coverage.enabled=false", "--passWithNoTests"]
    if runner == "jest":
        return [f"--changedSince={base}", "--coverage=false", "--passWithNoTests"]
    return []


def related_command(
    command: list[str],
    coverage: Path | None,
    gate: Gate,
    groups: list[Group],
    directory: Path,
    base: str | None,
) -> tuple[list[str], Path | None]:
    flags: list[str] = related_test_flags(gate, groups, directory, base) if base else []
    if not flags:
        return command, coverage
    print("Related tests only; CI runs the full suite and coverage.")
    return [*command, *flags], None


def validate_scanner_log(scanner: str | None, log: TextIO) -> None:
    if scanner in SCANNER_LOGS:
        SCANNER_LOGS[scanner](log)


def junit_root(path: Path) -> ET.Element:
    # Local JUnit only; ElementTree rejects external entities (test_junit_rejects_entities).
    # nosemgrep: python.lang.security.use-defused-xml-parse.use-defused-xml-parse
    return ET.parse(path).getroot()


def completed_tests(path: Path, kind: str) -> int:
    if kind == "dart-tests":
        if (
            not (events := dart_events(path))
            or events[-1].get("type") != "done"
            or events[-1].get("success") is not True
        ):
            raise ValueError("Test report does not contain a successful completed run")
        return sum(
            event.get("type") == "testDone"
            and event.get("hidden") is False
            and event.get("skipped") is False
            and event.get("result") == "success"
            for event in events
        )
    if kind == "xcode-tests":
        summary = json.loads(path.read_text())
        passed = summary.get("passedTests")
        if (
            summary.get("result") != "Passed"
            or summary.get("failedTests") != 0
            or type(passed) is not int
        ):
            raise ValueError("Test report does not contain a successful completed run")
        return passed
    try:
        tree = junit_root(path)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"The command passed but wrote no JUnit report ({'/'.join(path.parts[-2:])}). "
            "Make the command of this gate write its JUnit report to the `report` path "
            "that hard-eng.gates.json gives for this gate."
        ) from None
    if tree.tag not in {"testsuites", "testsuite"}:
        raise ValueError("Expected a JUnit test report")
    if tree.findall(".//failure") or tree.findall(".//error"):
        raise ValueError("Test report contains failures or errors")
    return sum(test.find("skipped") is None for test in tree.iter("testcase"))


def reported_skips(path: Path, kind: str) -> set[str]:
    if kind == "dart-tests":
        events = dart_events(path)
        names = {
            test.get("id"): test.get("name")
            for event in events
            if event.get("type") == "testStart"
            and isinstance(test := event.get("test"), dict)
        }
        return {
            str(names.get(event.get("testID")))
            for event in events
            if event.get("type") == "testDone" and event.get("skipped") is True
        }
    if kind == "xcode-tests":
        return set()
    tree = junit_root(path)
    return {
        test.get("name", "").split("[", 1)[0]
        for test in tree.iter("testcase")
        if test.find("skipped") is not None
    }


def skipped_tests(root: Path, groups: list[Group], since: float) -> set[str]:
    """Skips in the test reports that this run wrote."""
    names: set[str] = set()
    for group in groups:
        for gate in group["checks"]:
            report = gate.get("report", {})
            path = root / group["path"] / report.get("tests", "")
            if (
                gate.get("role") == "tests"
                and path.is_file()
                and path.stat().st_mtime >= since
            ):
                names |= reported_skips(path, report["type"])
    return names


def expected_coverage(
    path: Path, kind: str, directory: Path, expected: set[Path]
) -> dict[Path, tuple[int, int]]:
    reader = {"python-tests": python_coverage, "xcode-tests": xccov_coverage}.get(
        kind, lcov_coverage
    )
    files = reader(path, directory)
    if kind == "lcov-tests" and "\nFN:" not in path.read_text():
        write_istanbul(path, directory)
    if kind == "lcov-tests":
        expected = expected - erased_typescript(expected - files.keys())
    if kind == "xcode-tests":
        expected = expected - erased_swift(expected - files.keys())
    if kind == "dart-tests":
        # Dart LCOV omits simple export barrels: they have no executable lines.
        expected = {
            file
            for file in expected
            if file in files or not EXPORT_PREFIX.fullmatch(file.read_text())
        }
        expected = expected - erased_dart(expected - files.keys())
    missing = expected - files.keys()
    if missing:
        relative = [file.relative_to(directory) for file in sorted(missing)]
        outside_lib = kind == "dart-tests" and any(
            path.parts[0] != "lib" for path in relative
        )
        from dart_boundaries import flutter_without_test

        raise ValueError(
            f"Coverage report omits production files: {', '.join(map(str, relative))}. "
            "Cover them, or mark generator output with "
            "`<pattern> linguist-generated=true` in .gitattributes"
            + (omit_step(directory, relative) if kind == "python-tests" else "")
            + (
                ". For Dart code outside lib/: move it under lib/ and test it there"
                if outside_lib
                else ""
            )
            + (
                ". Or leave it in place and write tests under test/ that import it by a"
                " relative path and use package:test/test.dart (not flutter_test). The"
                " second way needs `test` as a dev dependency and a setup rerun, which adds"
                " the VM test run"
                if outside_lib and not flutter_without_test(directory)
                else ""
            )
        )
    return {file: files[file] for file in expected}


def line_coverage(
    path: Path, kind: str, directory: Path, expected: set[Path]
) -> tuple[int, int]:
    return coverage_totals(
        path, kind, directory, expected_coverage(path, kind, directory, expected)
    )


def coverage_totals(
    path: Path, kind: str, directory: Path, files: dict[Path, tuple[int, int]]
) -> tuple[int, int]:
    covered = sum(hit for hit, _ in files.values())
    total = sum(count for _, count in files.values())
    if not total:
        raise ValueError("Coverage report contains no executable lines")
    if kind != "xcode-tests":
        report_branches(path, kind, directory, set(files))
    return covered, total


def check_coverage(path: Path, kind: str, directory: Path, expected: set[Path]) -> None:
    files = expected_coverage(path, kind, directory, expected)
    covered, total = coverage_totals(path, kind, directory, files)
    print(
        f"Line coverage: {covered}/{total} ({100 * covered / total:.2f}%; minimum 70%)"
    )
    if covered * 100 < total * 70:
        raise ValueError(
            "HE-COVERAGE-MIN: Line coverage is below 70%. Files with the most uncovered lines: "
            + most_uncovered(files, directory)
        )


def most_uncovered(files: dict[Path, tuple[int, int]], directory: Path) -> str:
    lost = sorted(
        (hit - count, file.relative_to(directory.resolve()), count)
        for file, (hit, count) in files.items()
        if hit < count
    )
    return ", ".join(
        f"{file} {-gap} of {count} uncovered" for gap, file, count in lost[:5]
    )


def report_branches(
    path: Path, kind: str, directory: Path, expected: set[Path]
) -> None:
    covered = total = 0
    if kind == "python-tests":
        entries = json.loads(path.read_text())["files"]
        for name, entry in entries.items():
            if (directory / name).resolve() in expected:
                summary = entry["summary"]
                covered += summary.get("covered_branches", 0)
                total += summary.get("num_branches", 0)
    else:
        source = None
        for record in path.read_text().splitlines():
            if record.startswith("SF:"):
                source = (directory / record[3:]).resolve()
            elif record.startswith("BRDA:") and source in expected:
                hits = record.rsplit(",", 1)[-1]
                covered += hits != "-" and int(hits) > 0
                total += 1
    if total:
        if not 0 <= covered <= total:
            raise ValueError("Invalid branch coverage counts")
        print(
            f"Branch coverage: {covered}/{total} ({100 * covered / total:.2f}%; informational)"
        )


def validate_osv_package(
    item: JsonObject, source: JsonObject, layers: list[JsonObject], image: bool
) -> None:
    package = item["package"]
    if not isinstance(package, dict):
        raise TypeError("OSV package must be an object")
    commit = package.get("commit")
    if not (isinstance(commit, str) and commit) and not all(
        isinstance(package.get(key), str) and package[key]
        for key in ("name", "version", "ecosystem")
    ):
        from python_setup import osv_identity

        osv_identity(package, source["path"])
    if item.get("vulnerabilities", []) != [] or item.get("groups", []) != []:
        found = item.get("vulnerabilities")
        entries = found if isinstance(found, list) else []
        ids = [str(entry.get("id")) for entry in entries if isinstance(entry, dict)]
        name = f"{package.get('name') or commit}@{package.get('version')}"
        raise ValueError(f"OSV reports vulnerable packages: {name}: " + ", ".join(ids))
    if image:
        origin = package["image_origin_details"]
        if not isinstance(origin, dict):
            raise ValueError("OSV image package lacks layer origin details")
        index = origin["index"]
        if (
            source["type"] not in {"artifact", "os", "lockfile"}
            or type(index) is not int
            or not 0 <= index < len(layers)
            or layers[index]["is_empty"]
        ):
            raise ValueError("OSV package lacks a valid image layer origin")


def osv_layers(report: JsonObject) -> list[JsonObject]:
    metadata = report["image_metadata"]
    if not isinstance(metadata, dict):
        raise TypeError("OSV image metadata must be an object")
    layers = metadata["layer_metadata"]
    if not isinstance(layers, list) or not layers:
        raise ValueError("OSV image report contains no layers")
    for layer in layers:
        if not isinstance(layer, dict):
            raise TypeError("OSV image layer must be an object")
        if type(layer["is_empty"]) is not bool or (
            not layer["is_empty"]
            and (
                not isinstance(layer["diff_id"], str)
                or not SHA256_DIGEST.fullmatch(layer["diff_id"])
            )
        ):
            raise ValueError("OSV image report has invalid layer metadata")
    return cast(list[JsonObject], layers)


def validate_osv(
    path: Path, *, image: bool = False, empty_bun: Path | None = None
) -> None:
    try:
        report = json.loads(path.read_text())
        results = report["results"]
        if (
            report.get("errors")
            or report.get("error")
            or report.get("experimental_generic_findings")
        ):
            raise ValueError("OSV reports scan errors or findings")
        if (
            results in (None, [])
            and not image
            and empty_bun is not None
            and not (empty_bun / "bun.lock").exists()
            and dependency_free(empty_bun)
        ):
            print(
                "OSV: package.json declares no dependencies, so Bun keeps no lockfile"
            )
            return
        if not isinstance(results, list):
            raise TypeError("OSV results must be a list")
        layers = osv_layers(report) if image else []
        count = 0
        for result in results:
            if not all(
                isinstance(result["source"][key], str) and result["source"][key]
                for key in ("path", "type")
            ):
                raise ValueError("OSV report is missing its scan source")
            packages = result["packages"]
            if not isinstance(packages, list):
                raise TypeError("OSV packages must be a list")
            for item in packages:
                validate_osv_package(item, result["source"], layers, image)
                count += 1
        if not count:
            raise ValueError("OSV report contains no scanned packages")
        print(f"OSV validated {count} package records; no reported vulnerabilities")
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("OSV report is incomplete or malformed") from error


def validate_osv_image(path: Path) -> None:
    validate_osv(path, image=True)


def validate_semgrep(path: Path) -> None:
    try:
        report = json.loads(path.read_text())
        if results := report["results"]:
            raise ValueError(
                f"Semgrep reports {len(results)} findings; fix each as its message says: "
                + "; ".join(
                    f"{item['path']}:{item['start']['line']} {item['extra']['message']}"
                    for item in results[:30]
                )
            )
        from hot_paths import require_parsed

        require_parsed(report["errors"])
        if report["skipped_rules"] != [] or report["paths"].get("skipped", []) != []:
            raise ValueError("Semgrep reports skipped analysis")
        scanned, timing = report["paths"]["scanned"], report["time"]
        for values in (scanned, timing["rules"]):
            if (
                not isinstance(values, list)
                or not values
                or not all(isinstance(value, str) and value.strip() for value in values)
            ):
                raise ValueError(
                    "Semgrep requires scanned files and executed rules (--time)"
                )
        if timeouts := timing.get("fixpoint_timeouts", []):
            paths = {(t.get("location") or {}).get("path") for t in timeouts}
            named = ", ".join(sorted(p for p in paths if p))
            raise ValueError(
                f"Semgrep ran out of time on {named}. If a file holds big tables of "
                "text constants, move them to a data module, then run the same check again"
                if named
                else "Semgrep ran out of time and named no file; run the same check again"
            )
        targets = timing["targets"]
        if not isinstance(targets, list) or {t["path"] for t in targets} != set(
            scanned
        ):
            raise ValueError("Semgrep timing scope does not match scanned files")
        sizes = [target["num_bytes"] for target in targets]
        if not all(type(size) is int and size >= 0 for size in sizes) or not sum(sizes):
            raise ValueError("Semgrep report contains no source content")
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError(
            "Semgrep report is incomplete or malformed; use --time"
        ) from error


def validate_import_linter(path: Path) -> None:
    content = path.read_text()
    graphs = ANALYZED_SUMMARY.findall(content)
    contracts = CONTRACTS_SUMMARY.findall(content)
    outcomes = KEPT_OR_BROKEN_OUTCOME.findall(content)
    if (
        len(graphs) != 1
        or int(graphs[0][0]) == 0
        or len(contracts) != 1
        or int(contracts[0][0]) == 0
        or int(contracts[0][1]) != 0
        or len(outcomes) != int(contracts[0][0])
        or any(outcome != "KEPT" for outcome in outcomes)
        or WARNINGS_LINE.search(content)
    ):
        raise ValueError(
            "Import Linter requires a nonempty analysed graph and kept contracts without failures or warnings"
        )


def validate_deptry(path: Path) -> None:
    if json.loads(path.read_text()) != []:
        raise ValueError("Deptry reports dependency issues or malformed results")


def validate_deptry_log(log: TextIO) -> None:
    log.seek(0)
    scanned = False
    for line in log:
        if "Warning: Skipping processing of " in line:
            raise ValueError("Deptry skipped source analysis; see command diagnostics")
        if SCAN_PROGRESS_LINE.fullmatch(line.strip()):
            scanned = True
    if not scanned:
        raise ValueError("Deptry requires diagnostics showing a nonempty source scan")


def validate_trivy_log(log: TextIO) -> None:
    log.seek(0)
    started = False
    for line in log:
        if "\tERROR\t" in line:
            raise ValueError("Trivy reported scan errors; see command diagnostics")
        if "\tINFO\t[misconfig] Misconfiguration scanning is enabled" in line:
            started = True
    if not started:
        raise ValueError(
            "Trivy configuration diagnostics are missing; do not use quiet mode"
        )


def validate_trivy(path: Path) -> None:
    try:
        report = json.loads(path.read_text())
        if report["SchemaVersion"] != 2 or report["ArtifactType"] not in (
            "filesystem",
            "repository",
        ):
            raise ValueError("Expected a Trivy directory configuration report")
        results = report.get("Results")
        if not results:
            raise ValueError(
                "Trivy found no deployment configuration in current files; remove the deployment gate if the project has none"
            )
        for result in results:
            if result["Class"] != "config" or not all(
                isinstance(result[key], str) and result[key].strip()
                for key in ("Target", "Type")
            ):
                raise ValueError("Trivy report lacks a configuration target")
            summary = result["MisconfSummary"]
            if (
                type(summary["Successes"]) is not int
                or summary["Successes"] <= 0
                or type(summary["Failures"]) is not int
                or summary["Failures"] != 0
            ):
                raise ValueError("Trivy reports failed checks or no successful checks")
            findings = result.get("Misconfigurations", [])
            if not isinstance(findings, list) or any(
                finding["Status"] != "PASS" for finding in findings
            ):
                raise ValueError("Trivy reports misconfigurations or incomplete checks")
            if findings and len(findings) != summary["Successes"]:
                raise ValueError("Trivy successful check counts are inconsistent")
            if any(
                result.get(key, []) != []
                for key in (
                    "Vulnerabilities",
                    "Secrets",
                    "ExperimentalModifiedFindings",
                )
            ):
                raise ValueError("Trivy reports additional or suppressed findings")
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Trivy report is incomplete or malformed") from error


def validate_react_project(project: JsonObject) -> None:
    if (
        project["complete"] is not True
        or project["skippedChecks"] != []
        or project.get("skippedCheckReasons", {}) != {}
        or project["diagnostics"] != []
    ):
        raise ValueError(incomplete_reason(project))
    files = project["analyzedFiles"]
    if (
        not isinstance(files, list)
        or not files
        or not all(isinstance(name, str) and name.strip() for name in files)
        or len(set(files)) != len(files)
    ):
        raise ValueError("React Doctor report lacks distinct analysed files")
    source = project["project"]
    if not isinstance(source, dict):
        raise TypeError("React Doctor project metadata must be an object")
    for count in (
        project["analyzedFileCount"],
        project["scannedFileCount"],
        source["sourceFileCount"],
    ):
        if type(count) is not int or count != len(files):
            raise ValueError(
                "React Doctor analysis counts are incomplete or inconsistent"
            )


def validate_react_doctor(path: Path) -> None:
    try:
        report = json.loads(path.read_text())
        if (
            report["schemaVersion"] != 3
            or report["mode"] != "full"
            or report["ok"] is not True
            or report["reactDetected"] is not True
            or report["error"] is not None
            or report["diff"] is not None
            or report.get("skippedProjects", []) != []
        ):
            raise ValueError("React Doctor requires a successful full React scan")
        if report["diagnostics"] != []:
            raise ValueError("React Doctor reports diagnostics")
        for key in (
            "errorCount",
            "warningCount",
            "affectedFileCount",
            "totalDiagnosticCount",
        ):
            value = report["summary"][key]
            if type(value) is not int or value != 0:
                raise ValueError("React Doctor reports diagnostics or invalid totals")
        projects = report["projects"]
        if not isinstance(projects, list) or not projects:
            raise ValueError("React Doctor report contains no projects")
        for project in projects:
            validate_react_project(project)
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("React Doctor report is incomplete or malformed") from error


def validate_dart_decimate(path: Path) -> None:
    try:
        report = json.loads(path.read_text())
        envelope = {
            "schema_version": "dart-decimate.report.v1",
            "kind": "combined",
            "command": "check",
            "verdict": "pass",
        }
        if any(report[key] != value for key, value in envelope.items()) or not (
            DART_DECIMATE_VERSION.fullmatch(report["tool"])
        ):
            raise ValueError("Expected a passing combined Dart Decimate check")
        if report["findings"] != [] or report["clone_groups"] != []:
            raise ValueError("Dart Decimate reports findings or duplicate code")
        summary = report["summary"]
        for key in (
            "findings",
            "dead_files",
            "unused_exports",
            "unused_types",
            "unused_enum_members",
            "unused_class_members",
            "unrendered_widgets",
            "missing_entry_points",
            "unresolved_dependencies",
            "code_duplications",
            "duplicated_lines",
            "duplication_percentage_basis_points",
            "duplication_threshold_basis_points",
        ):
            if type(summary[key]) is not int or summary[key] != 0:
                raise ValueError("Dart Decimate reports findings or invalid counts")
        if summary["duplication_threshold_exceeded"] is not False:
            raise ValueError("Dart Decimate duplication threshold failed")
        for key in ("files", "duplication_analyzed_lines"):
            if type(summary[key]) is not int or summary[key] <= 0:
                raise ValueError("Dart Decimate report contains no analysed source")
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Dart Decimate report is incomplete or malformed") from error


def jscpd_scanned(path: Path) -> bool:
    try:
        formats = json.loads(path.read_text())["statistics"]["formats"]
        return set(formats) in ({"python"}, {"swift"}) and all(
            type(summary["sources"]) is int and summary["sources"] > 0
            for summary in formats.values()
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def validate_jscpd(path: Path, below_minimum: Callable[[], bool] | None = None) -> None:
    try:
        report = json.loads(path.read_text())
        if report["duplicates"] != []:
            raise ValueError("jscpd reports duplicate code or malformed findings")
        stats = report["statistics"]
        formats, total = stats["formats"], stats["total"]
        if (
            formats == {}
            and total["sources"] == 0
            and below_minimum
            and below_minimum()
        ):
            print(
                "jscpd: every file is below jscpd's --min-tokens, so no clone can exist"
            )
            return
        if not isinstance(formats, dict) or set(formats) not in ({"python"}, {"swift"}):
            raise ValueError("jscpd report requires Python or Swift analysis")
        analysed = next(iter(formats.values()))
        for summary in (analysed, total):
            for key in (
                "clones",
                "duplicatedLines",
                "duplicatedTokens",
                "newClones",
                "newDuplicatedLines",
                "percentage",
                "percentageTokens",
            ):
                value = summary[key]
                if type(value) not in (int, float) or value != 0:
                    raise ValueError("jscpd reports duplication or invalid counts")
            for key in ("sources", "lines", "tokens"):
                value = summary[key]
                if type(value) is not int or value <= 0 or value != analysed[key]:
                    raise ValueError("jscpd analysis scope is empty or inconsistent")
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("jscpd report is incomplete or malformed") from error


def osv_lockfiles(command: list[str], directory: Path) -> list[str]:
    """Leave out lockfiles that hold no package OSV can scan; [] when none is left."""
    from python_setup import locks_nothing

    if "--lockfile=bun.lock" in command and not (directory / "bun.lock").exists():
        command = [value for value in command if value != "--lockfile=bun.lock"]
    if "--lockfile=uv.lock" in command and locks_nothing(directory):
        command = [value for value in command if value != "--lockfile=uv.lock"]
        if not any(value.startswith("--lockfile=") for value in command):
            return []
    return command


def jscpd_below_minimum(command: list[str], directory: Path, timeout: float) -> bool:
    """An empty jscpd scope is real only if the smallest --min-tokens still scans nothing."""
    options = {"--min-tokens", "-k", "--output", "-o"}
    rescan = [
        argument
        for index, argument in enumerate(command)
        if argument.split("=", 1)[0] not in options
        and (index == 0 or command[index - 1] not in options)
    ]
    with tempfile.TemporaryDirectory(prefix="hard-eng-jscpd-") as output:
        subprocess.run(
            [*rescan, "--min-tokens", "1", "--output", output],
            cwd=directory,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
        return jscpd_scanned(Path(output) / "jscpd-report.json")


def validate_scanner_report(
    scanner: str,
    gate: Gate,
    path: Path,
    command: list[str],
    directory: Path,
    timeout: float,
) -> None:
    if scanner == "osv" and "--lockfile=bun.lock" in gate["command"]:
        validate_osv(path, empty_bun=directory)
    elif scanner == "jscpd":
        validate_jscpd(path, lambda: jscpd_below_minimum(command, directory, timeout))
    elif scanner == "freshness":
        from freshness import freshness_waiting, validate_freshness

        waiting = freshness_waiting(gate, directory)
        validate_freshness(path, gate, waiting=waiting, directory=directory)
    elif scanner == "fallow":
        validate_fallow(path, sdk_binaries(directory), directory)
    else:
        SCANNERS[scanner](path)


def scanner_result(
    passed: bool,
    scanner: str,
    gate: Gate,
    path: Path,
    command: list[str],
    directory: Path,
    timeout: float,
) -> None:
    """A failed scan shows its findings from its report, as the tool prints none."""
    if passed:
        validate_scanner_report(scanner, gate, path, command, directory, timeout)
    elif scanner in {"osv", "osv-image"} and path.is_file():
        try:
            validate_scanner_report(scanner, gate, path, command, directory, timeout)
        except ValueError as error:
            print(error)
    elif scanner in FINDING_READERS:
        lines = FINDING_READERS[scanner](path)
        if (more := len(lines) - FINDING_LIMIT) > 0:
            lines[FINDING_LIMIT:] = [f"{more} more findings in {path}"]
        for line in lines:
            print(f"{gate['name']}: {line}")
        if scanner == "import-linter" and missing_build_system(lines, directory):
            print(
                f"{gate['name']}: Add a [build-system] table to pyproject.toml and run `uv sync`."
            )


def missing_build_system(lines: list[str], directory: Path) -> bool:
    """Import Linter cannot find the package when uv has no build system to install it with."""
    project = directory / "pyproject.toml"
    return (
        any(line.startswith("Could not find package") for line in lines)
        and project.is_file()
        and "[build-system]" not in project.read_text()
    )


def commit_sha(item: JsonObject) -> str:
    prints = item.get("partialFingerprints")
    sha = prints.get("commitSha") if isinstance(prints, dict) else None
    return f" in commit {sha[:12]}" if isinstance(sha, str) and sha else ""


def gitleaks_findings(path: Path) -> list[str]:
    try:
        results = json.loads(path.read_text())["runs"][0]["results"]
        return [
            f"{item['ruleId']} {place['artifactLocation']['uri']}:"
            f"{place['region']['startLine']}{commit_sha(item)}"
            for item in results
            for place in [item["locations"][0]["physicalLocation"]]
        ]
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return []


def validate_gitleaks(path: Path) -> None:
    try:
        report = json.loads(path.read_text())
        runs = report["runs"]
        if report["version"] != "2.1.0" or not isinstance(runs, list) or len(runs) != 1:
            raise ValueError("Expected one Gitleaks SARIF 2.1.0 run")
        run = runs[0]
        if run["results"] != []:
            raise ValueError("Gitleaks reports secret findings or malformed results")
        driver = run["tool"]["driver"]
        rules = driver["rules"]
        if driver["name"] != "gitleaks" or not isinstance(rules, list) or not rules:
            raise ValueError("Gitleaks report must identify the scanner and its rules")
        if not all(
            isinstance(rule["id"], str) and rule["id"].strip() for rule in rules
        ):
            raise ValueError("Gitleaks report contains invalid rule identities")
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Gitleaks report is incomplete or malformed") from error


def validate_performance_junit(path: Path) -> None:
    if not completed_tests(path, "junit"):
        raise ValueError("No performance tests ran")


def validate_performance_dart(path: Path) -> None:
    if not completed_tests(path, "dart-tests"):
        raise ValueError("No performance tests ran")


def validate_lighthouse(path: Path) -> None:
    results = json.loads(path.read_text())
    if not isinstance(results, list) or not results:
        raise ValueError("Lighthouse requires nonempty assertions")
    urls = set()
    budgeted = set()
    for result in results:
        if not isinstance(result, dict) or not result.get("url"):
            raise ValueError("Lighthouse assertion is missing its URL")
        urls.add(result["url"])
        if result.get("passed") is not True:
            raise ValueError("Lighthouse assertion failed")
        if (
            result.get("level") == "error"
            and result.get("name") in {"minScore", "maxNumericValue"}
            and result.get("auditId")
            in {
                "categories",
                "largest-contentful-paint",
                "total-blocking-time",
                "cumulative-layout-shift",
                "first-contentful-paint",
                "speed-index",
                "resource-summary",
            }
            and (
                result.get("auditId") != "categories"
                or result.get("auditProperty") == "performance"
            )
            and all(
                type(result.get(key)) in {int, float} and math.isfinite(result[key])
                for key in ("actual", "expected")
            )
        ):
            budgeted.add(result["url"])
    if urls != budgeted:
        raise ValueError(
            "Every Lighthouse URL requires an error-level performance budget"
        )


SCANNERS = {
    "lighthouse-ci": validate_lighthouse,
    "performance-junit": validate_performance_junit,
    "performance-dart": validate_performance_dart,
    "import-linter": validate_import_linter,
    "deptry": validate_deptry,
    "dart-decimate": validate_dart_decimate,
    "react-doctor": validate_react_doctor,
    "trivy": validate_trivy,
    "fallow": validate_fallow,
    "osv": validate_osv,
    "osv-image": validate_osv_image,
    "semgrep": validate_semgrep,
    "gitleaks": validate_gitleaks,
    "jscpd": validate_jscpd,
}

FINDING_LIMIT = 20
FINDING_READERS = {
    "gitleaks": gitleaks_findings,
    "react-doctor": react_findings,
    "fallow": fallow_findings,
    "semgrep": semgrep_findings,
    "trivy": trivy_findings,
    "dart-decimate": decimate_findings,
    "jscpd": jscpd_findings,
    "import-linter": import_linter_findings,
    "performance-dart": dart_performance_findings,
}
SCANNER_LOGS = {"deptry": validate_deptry_log, "trivy": validate_trivy_log}
