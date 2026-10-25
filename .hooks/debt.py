"""Shrink-only adoption debt: findings the existing code had when Hard Eng was installed."""

import json
import re
import subprocess
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from gate_config import Gate, Group, JsonObject

DEBT_FILE = "hard-eng.debt.json"
# Failing tests, broken installs and leaked secrets are never old findings to keep.
NEVER = {"tests", "lockfiles", "secrets-files", "secrets-history"}
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
RUNNER_LINES = re.compile(
    r"^(warning: (The `UV_|`VIRTUAL_ENV=)|mise |(Downloading|Downloaded|Installed|Uninstalled"
    r"|Resolved|Prepared|Audited|Building|Built) )"
)


def osv_findings(path: Path) -> list[str]:
    report = json.loads(path.read_text())
    return [
        f"{item['package']['name']} {item['package']['version']} "
        + ",".join(
            sorted(vulnerability["id"] for vulnerability in item["vulnerabilities"])
        )
        for result in report["results"]
        for item in result["packages"]
        if item.get("vulnerabilities")
    ]


def semgrep_findings(path: Path) -> list[str]:
    report = json.loads(path.read_text())
    return [
        f"{result['check_id']} {result['path']} {result['extra'].get('lines', '')}"
        for result in report["results"]
    ]


def jscpd_findings(path: Path) -> list[str]:
    report = json.loads(path.read_text())
    return [
        f"{clone['firstFile']['name']} {clone['secondFile']['name']} {clone.get('fragment', '')}"
        for clone in report["duplicates"]
    ]


def deptry_findings(path: Path) -> list[str]:
    report = json.loads(path.read_text())
    return [
        f"{issue['error']['code']} {issue['module']} {issue['location']['file']}"
        for issue in report
    ]


# Report types whose findings live in the report file; findings of the others are in the output.
REPORT_FINDINGS: dict[str, Callable[[Path], list[str]]] = {
    "osv": osv_findings,
    "semgrep": semgrep_findings,
    "jscpd": jscpd_findings,
    "deptry": deptry_findings,
}
OUTPUT_REPORTS = {None, "import-linter", "performance-junit"}
OUTPUTS: dict[str, str] = {}


def remember(group: Group, gate: Gate, text: str) -> str:
    """Keep a gate's output for the debt comparison and pass it on."""
    key = f"{group['path']}/{gate['name']}"
    OUTPUTS[key] = f"{OUTPUTS.get(key, '')}\n{text}"
    return text


def recordable(gate: Gate) -> bool:
    kind = gate.get("report", {}).get("type")
    return gate.get("role") not in NEVER and (
        kind in REPORT_FINDINGS or kind in OUTPUT_REPORTS
    )


def fingerprints(root: Path, group: Group, gate: Gate, output: str) -> Counter[str]:
    """Output lines with line numbers, counts and the checkout path made neutral."""
    report = gate.get("report", {})
    path = root / group["path"] / report.get("path", "")
    lines = output.splitlines()
    if report.get("stdout") is True and path.is_file():
        lines += path.read_text().splitlines()
    found: Counter[str] = Counter()
    for line in lines:
        line = re.sub(r"\d+", "N", ANSI.sub("", line).replace(str(root), ".")).strip()
        if line and not RUNNER_LINES.match(line):
            found[line] += 1
    extract = REPORT_FINDINGS.get(str(report.get("type")))
    if extract is not None and path.is_file():
        try:
            found.update(extract(path))
        except (ValueError, KeyError, TypeError, AttributeError):
            found["unreadable report"] += 1
    return found


def load(root: Path) -> dict[str, Counter[str]]:
    path = root / DEBT_FILE
    if not path.is_file():
        return {}
    debt = json.loads(path.read_text())
    gates = debt.get("gates") if isinstance(debt, dict) else None
    if (
        debt.get("version") != 1
        or not isinstance(gates, dict)
        or not all(
            isinstance(lines, dict)
            and all(type(count) is int and count > 0 for count in lines.values())
            for lines in gates.values()
        )
    ):
        raise ValueError(
            f"{DEBT_FILE} must hold version 1 and positive counts per gate"
        )
    return {key: Counter(lines) for key, lines in gates.items()}


def judge(root: Path, group: Group, gate: Gate, failed: bool, output: str) -> bool:
    """A gate with debt fails only on findings beyond it, or when listed ones are fixed."""
    debt = load(root).get(f"{group['path']}/{gate['name']}")
    if debt is None:
        return failed
    current = fingerprints(root, group, gate, output) if failed else Counter()
    if new := current - debt:
        print(f"FAIL {gate['name']}: findings beyond {DEBT_FILE}:")
        shown = sorted(new.elements(), key=lambda line: not re.search(r"\w", line))
        print("".join(f"  {line}\n" for line in shown[:20]), end="")
        return True
    if fixed := debt - current:
        print(
            f"FAIL {gate['name']}: {fixed.total()} recorded lines are fixed; run "
            f"`python3 .hooks/hard-eng.py adopt` to drop them from {DEBT_FILE}"
        )
        return True
    print(
        f"DEBT {gate['name']}: the failure above holds only the {debt.total()} lines "
        f"recorded in {DEBT_FILE}; no new finding"
    )
    return False


def record(
    root: Path, groups: list[Group], failed: set[str], outputs: dict[str, str]
) -> int:
    """Write the debt once; later runs only drop lines that are gone."""
    old = load(root) if (root / DEBT_FILE).is_file() else None
    gates: JsonObject = {}
    refused = []
    for group in groups:
        for gate in group["checks"]:
            key = f"{group['path']}/{gate['name']}"
            if key not in failed:
                continue
            if not recordable(gate):
                refused.append(key)
                continue
            current = fingerprints(root, group, gate, outputs.get(key, ""))
            if old is not None:
                current &= old.get(key, Counter())
            if current:
                gates[key] = dict(sorted(current.items()))
    if refused and old is None:
        print(
            f"These checks must pass before adoption; fix them first: {', '.join(refused)}"
        )
        return 1
    (root / DEBT_FILE).write_text(
        json.dumps({"version": 1, "gates": gates}, indent=2) + "\n"
    )
    print(
        f"Recorded {len(gates)} checks with old findings in {DEBT_FILE}; it can only shrink."
    )
    return 0


def git_file(root: Path, base: str, name: str) -> str | None:
    from plans import _git_output

    try:
        return _git_output(root, "show", f"{base}:{name}")
    except subprocess.CalledProcessError:
        return None


def require_shrink(root: Path, base: str | None) -> None:
    """HE-DEBT-SHRINK-ONLY: debt appears only with the install and never grows."""
    from plans import default_branch_point

    current = load(root)
    base = base or default_branch_point(root)
    if not current or base is None:
        return
    before = git_file(root, base, DEBT_FILE)
    if before is None:
        if git_file(root, base, ".hooks/hard-eng-source.json") is not None:
            raise ValueError(
                f"HE-DEBT-SHRINK-ONLY: only the change that installs Hard Eng can add {DEBT_FILE}; repair the findings instead"
            )
        return
    old = {key: Counter(lines) for key, lines in json.loads(before)["gates"].items()}
    if grown := sorted(
        key for key, lines in current.items() if lines - old.get(key, Counter())
    ):
        raise ValueError(
            f"HE-DEBT-SHRINK-ONLY: {DEBT_FILE} grew for {', '.join(grown)}; repair the new findings instead"
        )
