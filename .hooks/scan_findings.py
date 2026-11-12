"""Read the findings of a failed scanner gate from its report, one line each."""

import json
from pathlib import Path

from dart_test_report import failure_summary
from fallow_report import located

PRINTED_ELSEWHERE = {"deptry", "lighthouse-ci", "osv", "osv-image", "performance-junit"}
READ_ERRORS = (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError)


def one_line(text: object) -> str:
    return " ".join(str(text).split())


def semgrep_findings(path: Path) -> list[str]:
    try:
        return [
            f"{located(item['path'], item['start']['line'])} {item['check_id']} "
            f"{one_line(item['extra']['message'])}"
            for item in json.loads(path.read_text())["results"]
        ]
    except READ_ERRORS:
        return []


def trivy_findings(path: Path) -> list[str]:
    try:
        return [
            f"{located(result['Target'], (item.get('CauseMetadata') or {}).get('StartLine'))} "
            f"{item['ID']} {one_line(item['Title'])}"
            for result in json.loads(path.read_text())["Results"]
            for item in result.get("Misconfigurations", [])
            if item["Status"] != "PASS"
        ]
    except READ_ERRORS:
        return []


def decimate_findings(path: Path) -> list[str]:
    try:
        return [
            f"{located(item['path'], item.get('line'))} {item['rule_id']} "
            f"{one_line(item['message'])}"
            for item in json.loads(path.read_text())["findings"]
        ]
    except READ_ERRORS:
        return []


def repository_root(path: Path) -> Path | None:
    return next(
        (
            parent
            for parent in path.resolve().parents
            if (parent / "hard-eng.gates.json").is_file()
        ),
        None,
    )


def scanned_by(path: Path, root: Path) -> tuple[Path, list[str]] | None:
    config = json.loads((root / "hard-eng.gates.json").read_text())
    for group in config["packages"]:
        folder = root / group["path"]
        for gate in group["checks"]:
            command = gate["command"]
            report = gate.get("report")
            if (
                command[:1] == ["jscpd"]
                and report
                and (folder / report["path"]).resolve() == path.resolve()
            ):
                scanned = command[1:]
                end = next(
                    (i for i, argument in enumerate(scanned) if argument[:1] == "-"),
                    len(scanned),
                )
                return folder, scanned[:end]
    return None


def named_from_root(name: str, root: Path, folder: Path, scanned: list[str]) -> str:
    found = [
        (folder / entry / name) if (folder / entry / name).is_file() else folder / entry
        for entry in scanned
        if (folder / entry / name).is_file()
        or ((folder / entry).is_file() and Path(entry).name == name)
    ]
    names = [str(item.relative_to(root)) for item in found]
    return f"({' or '.join(names)})" if len(names) > 1 else "".join(names) or name


def jscpd_findings(path: Path) -> list[str]:
    root = repository_root(path)
    try:
        place = scanned_by(path, root) if root else None
    except READ_ERRORS:
        place = None

    def shown(name: str) -> str:
        return named_from_root(name, root, *place) if root and place else name

    try:
        return [
            "copied code "
            + " ".join(
                f"{shown(copy['name'])}:{copy['start']}-{copy['end']}"
                for copy in (clone["firstFile"], clone["secondFile"])
            )
            for clone in json.loads(path.read_text())["duplicates"]
        ]
    except READ_ERRORS:
        return []


def import_linter_findings(path: Path) -> list[str]:
    try:
        text = path.read_text()
    except (OSError, ValueError):
        return []
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    rules = [set(line.strip()) == {"-"} for line in lines]
    if "Broken contracts" in lines:
        start = lines.index("Broken contracts") + 1
        return [
            f"broken contract: {line}"
            if rules[index + 1 : index + 2] == [True]
            else line
            for index, line in enumerate(lines)
            if index >= start and not rules[index]
        ]
    kept = [line for line, rule in zip(lines, rules, strict=True) if not rule]
    return [] if any(line.startswith("Contracts:") for line in kept) else kept[:1]


def dart_performance_findings(path: Path) -> list[str]:
    summary = failure_summary(path)
    return [summary] if summary else []
