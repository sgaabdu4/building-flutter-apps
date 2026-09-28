"""Validate native Fallow combined scans and audit metric enforcement."""

import json
import math
import os
import shlex
from pathlib import Path

from gate_config import Gate, Group, JsonObject, Report


def owns_package_fallow(
    group: Group,
    gate: Gate,
    scripts: dict[str, str],
    package_groups: list[Group] | None = None,
) -> bool:
    """Keep the audit owner while allowing serial coverage to be reused."""
    command = gate["command"]
    if gate.get("report", {}).get("type") != "fallow":
        return False
    if command[:3] == ["pnpm", "run", "check:fallow"]:
        return True
    if command[:2] != ["pnpm", "run"] or gate.get("parallel"):
        return False
    try:
        standalone = shlex.split(scripts.get("check:fallow", ""))
    except ValueError:
        return False
    prerequisites = _serial_test_prerequisites(group, gate)
    if not prerequisites:
        return False
    expected = _chain_commands(prerequisites + [command])
    if standalone == expected:
        return True
    if package_groups is None:
        return False
    dependencies = _dependency_coverage_commands(group, package_groups)
    return dependencies is not None and standalone == _chain_commands(
        prerequisites + dependencies + [command]
    )


def _serial_test_prerequisites(
    group: Group, gate: Gate | None
) -> list[list[str]] | None:
    prerequisites = []
    for previous in group["checks"]:
        if gate is not None and previous is gate:
            return prerequisites
        if previous.get("role") == "tests":
            if previous.get("parallel"):
                return None
            prerequisites.append(previous["command"])
    return prerequisites if gate is None else None


def _dependency_coverage_commands(
    group: Group, package_groups: list[Group]
) -> list[list[str]] | None:
    by_path = {
        candidate["path"]: (index, candidate)
        for index, candidate in enumerate(package_groups)
    }
    current_index = next(
        (index for index, candidate in enumerate(package_groups) if candidate is group),
        None,
    )
    if current_index is None:
        return None
    commands: list[list[str]] = []
    for dependency in group.get("depends_on", []):
        owner = by_path.get(dependency)
        if owner is None:
            return None
        owner_index, owner_group = owner
        if owner_index >= current_index or group["path"] not in owner_group.get(
            "depends_on", []
        ):
            return None
        owner_commands = _serial_test_prerequisites(owner_group, None)
        if not owner_commands or any(
            command[:2] != ["pnpm", "run"] for command in owner_commands
        ):
            return None
        commands.extend(
            [
                [
                    "pnpm",
                    "--dir",
                    os.path.relpath(dependency, start=group["path"]),
                    "run",
                    *command[2:],
                ]
                for command in owner_commands
            ]
        )
    return commands


def _chain_commands(commands: list[list[str]]) -> list[str]:
    return [
        argument
        for index, command in enumerate(commands)
        for argument in (["&&"] if index else []) + command
    ]


SCANNERS = {"fallow", "dart-decimate", "react-doctor"}
TOLERANCE_FLAGS = {
    "--baseline",
    "--save-baseline",
    "--dead-code-baseline",
    "--health-baseline",
    "--dupes-baseline",
    "--regression-baseline",
    "--fail-on-regression",
    "--tolerance",
}


def native_scanner_command(arguments: list[str]) -> list[str] | None:
    """Return a scanner executable with its arguments behind package-manager prefixes."""
    if arguments[:2] in (["pnpm", "dlx"], ["pnpm", "exec"]):
        arguments = arguments[2:]
        while arguments and arguments[0].startswith(("--package=", "--allow-build=")):
            arguments = arguments[1:]
    if not arguments:
        return None
    executable = Path(arguments[0]).name.split("@", 1)[0]
    return [executable, *arguments[1:]] if executable in SCANNERS else None


def native_fallow_command(arguments: list[str]) -> list[str] | None:
    invocation = native_scanner_command(arguments)
    return invocation if invocation and invocation[0] == "fallow" else None


def option(invocation: list[str], flag: str) -> str | None:
    for index, argument in enumerate(invocation):
        key, separator, value = argument.partition("=")
        if key == flag:
            return value if separator else next(iter(invocation[index + 1 :]), "")
    return None


def fallow_failure(invocation: list[str], report: Report) -> str | None:
    crap = option(invocation, "--max-crap")
    if crap is not None and (not math.isfinite(float(crap)) or float(crap) <= 0):
        return "Fallow CRAP enforcement cannot be disabled; repair its coverage input"
    if "audit" not in invocation:
        if "--fail-on-issues" not in invocation:
            return "Fallow scans must fail on every finding; add --fail-on-issues"
        return None
    if report.get("type") != "fallow":
        return "Fallow audit gates require a native fallow report; exit status alone cannot prove enabled metrics"
    if option(invocation, "--gate") != "all":
        return (
            "Fallow audit must fail on every finding, not only new ones; add --gate all"
        )
    return None


def scanner_failure(invocation: list[str], report: Report) -> str | None:
    if invocation[0] == "dart-decimate":
        if "check" in invocation and "--strict" not in invocation:
            return "dart-decimate check must fail on every finding; add --strict"
    elif invocation[0] == "react-doctor":
        if option(invocation, "--blocking") != "warning":
            return "React Doctor must fail on warnings; use --blocking warning"
        if "--no-respect-inline-disables" not in invocation:
            return "React Doctor must not honour inline suppressions; add --no-respect-inline-disables"
    else:
        return fallow_failure(invocation, report)
    return None


def validate_scanner_command(arguments: list[str], report: Report) -> None:
    """Every finding fails; none may be baselined, tolerated or suppressed."""
    invocation = native_scanner_command(arguments)
    if invocation is None:
        return
    for argument in invocation:
        if argument.partition("=")[0] in TOLERANCE_FLAGS:
            raise ValueError(
                f"{invocation[0]} cannot tolerate existing findings with {argument}; repair every reported finding and commit the repair before continuing"
            )
    failure = scanner_failure(invocation, report)
    if failure is not None:
        raise ValueError(failure)


def fallow_report_path(arguments: list[str]) -> str | None:
    invocation = native_fallow_command(arguments) or []
    for index, argument in enumerate(invocation):
        flag, separator, value = argument.partition("=")
        if flag == "--output-file":
            output = (
                value
                if separator
                else next(iter(invocation[index + 1 : index + 2]), "")
            )
            if not output:
                raise ValueError("check:fallow --output-file needs a report path")
            return output
    return None


def validate_fallow_audit(report: JsonObject) -> None:
    if report["command"] != "audit" or report["verdict"] != "pass":
        raise ValueError("Fallow requires a passing native audit")
    complexity = report["complexity"]
    if not isinstance(complexity, dict) or complexity["findings"] != []:
        raise ValueError("Fallow audit reports missing complexity analysis or findings")
    summary = complexity["summary"]
    if not isinstance(summary, dict):
        raise TypeError("Fallow audit complexity summary must be an object")
    threshold = summary["max_crap_threshold"]
    if (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or not math.isfinite(threshold)
        or threshold <= 0
    ):
        raise ValueError("Fallow CRAP enforcement is disabled or invalid")
    for key in (
        "functions_above_threshold",
        "severity_critical_count",
        "severity_high_count",
        "severity_moderate_count",
    ):
        if type(summary[key]) is not int or summary[key] != 0:
            raise ValueError("Fallow audit reports complexity findings")
    for key in ("files_analyzed", "functions_analyzed"):
        count = summary[key]
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("Fallow audit lacks a valid analysis scope")


def validate_fallow(path: Path) -> None:
    try:
        report = json.loads(path.read_text())
        audit = report["kind"] == "audit"
        if audit:
            validate_fallow_audit(report)
            report = {
                **report,
                "kind": "combined",
                "check": report["dead_code"],
                "dupes": report["duplication"],
            }
        check, dupes = report["check"], report["dupes"]
        stats = dupes["stats"]
        counts = [check["total_issues"], check["summary"]["total_issues"]]
        counts += [stats["clone_groups"], stats["duplication_percentage"]]
        counts += list(check["summary"].values())
        corpus = {"total_files", "total_lines", "total_tokens"}
        counts += [value for key, value in stats.items() if key not in corpus]
        clean = all(type(n) in (int, float) and n == 0 for n in counts)
        if report["kind"] != "combined" or not clean:
            raise ValueError("Fallow reports findings or skipped analysis")
        optional = {"boundaries-not-configured", "rule-packs-not-configured"}
        diagnostics = report.get("workspace_diagnostics", [])
        if not isinstance(diagnostics, list):
            raise TypeError("Fallow diagnostics must be a list")
        if (
            any(isinstance(value, list) and value for value in check.values())
            or dupes["clone_groups"] != []
            or any(
                not isinstance(item, dict) or item.get("kind") not in optional
                for item in diagnostics
            )
        ):
            raise ValueError("Fallow reports findings or analysis diagnostics")
        if diagnostics:
            print(
                "Fallow: optional boundary/policy detectors unconfigured; not verified"
            )
        scopes = [(check["entry_points"]["total"], 0 if audit else 1)]
        scopes += [(stats[key], 0) for key in corpus]
        for value, minimum in scopes:
            if type(value) is not int or value < minimum:
                raise ValueError("Fallow report lacks a valid analysis scope")
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Fallow report is incomplete") from error
