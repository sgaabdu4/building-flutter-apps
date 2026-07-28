#!/usr/bin/env python3
"""Run Dart Decimate with Git-root attribution and exact package scope."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from git_env import git_env

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def error(message: str) -> int:
    print(f"Dart Decimate gate: {message}", file=sys.stderr)
    return 2


def git(package: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(package), *args],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
    )


def repository_root(package: Path) -> Path | None:
    result = git(package, "rev-parse", "--show-toplevel")
    if result.returncode:
        return None
    return Path(result.stdout.strip()).resolve()


def current_changed_lines(
    root: Path, base: str, relative: str
) -> tuple[set[int], int] | None:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        return None
    absolute = (root / path).resolve()
    try:
        absolute.relative_to(root)
    except ValueError:
        return None
    if not absolute.is_file():
        return None
    try:
        line_count = len(absolute.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeError):
        return None
    tracked = git(root, "ls-files", "--error-unmatch", "--", relative)
    if tracked.returncode:
        return set(range(1, line_count + 1)), line_count
    diff = git(
        root,
        "diff",
        "--unified=0",
        "--no-ext-diff",
        "--no-color",
        base,
        "--",
        relative,
    )
    if diff.returncode:
        return None
    changed = set()
    for line in diff.stdout.splitlines():
        if match := HUNK.match(line):
            start, count = int(match.group(1)), int(match.group(2) or "1")
            changed.update(range(start, start + count))
    return changed, line_count


def fail_receipt(
    reason: str,
    counts: tuple[int, ...] | None = None,
    candidates: int | None = None,
) -> dict:
    receipt = {
        "schema_version": "1",
        "result": "fail",
        "reason": reason,
        "upstream_exit": 1,
    }
    if counts is not None:
        receipt.update(
            {
                "introduced_findings": counts[0],
                "introduced_error_findings": counts[1],
                "introduced_warning_findings": counts[2],
                "pre_existing_findings": counts[3],
                "pre_existing_error_findings": counts[4],
                "pre_existing_warning_findings": counts[5],
                "per_finding_attribution": False,
            }
        )
    if candidates is not None:
        receipt["security_candidate_count"] = candidates
    return receipt


def new_only_receipt(report: object, root: Path, base: str) -> dict:
    if not isinstance(report, dict) or report.get("command") != "audit":
        return fail_receipt("INVALID_AUDIT_REPORT")
    try:
        attribution = report["summary"]["attribution"]
        introduced, pre_existing = attribution["introduced"], attribution["pre_existing"]
        findings, candidates = report["findings"], report["security_candidates"]
        counts = tuple(
            bucket[key]
            for bucket in (introduced, pre_existing)
            for key in ("findings", "error_findings", "warning_findings")
        )
    except (KeyError, TypeError):
        return fail_receipt("INVALID_ATTRIBUTION_SHAPE")
    if any(type(count) is not int or count < 0 for count in counts):
        return fail_receipt("INVALID_ATTRIBUTION_COUNT")
    introduced_total, introduced_errors, introduced_warnings = counts[:3]
    pre_existing_total, pre_existing_errors, pre_existing_warnings = counts[3:]
    if introduced_total != introduced_errors + introduced_warnings or (
        pre_existing_total != pre_existing_errors + pre_existing_warnings
    ):
        return fail_receipt("INVALID_ATTRIBUTION_ROLLUP", counts)
    if not isinstance(findings, list) or not isinstance(candidates, list):
        return fail_receipt("INVALID_FINDING_COLLECTION", counts)
    if any(not isinstance(finding, dict) for finding in findings):
        return fail_receipt("INVALID_FINDING", counts, len(candidates))
    if any(finding.get("severity") not in {"error", "warning"} for finding in findings):
        return fail_receipt("INVALID_FINDING_SEVERITY", counts, len(candidates))
    errors = [finding for finding in findings if finding["severity"] == "error"]
    if len(errors) != introduced_errors + pre_existing_errors or len(findings) != (
        introduced_total + pre_existing_total
    ):
        return fail_receipt("ATTRIBUTION_TOTAL_MISMATCH", counts, len(candidates))
    if introduced_errors == 0:
        return fail_receipt("UPSTREAM_EXIT_ATTRIBUTION_MISMATCH", counts, len(candidates))
    security_errors = [
        finding for finding in errors if finding.get("kind") == "security-candidate"
    ]
    non_security_errors = [
        finding for finding in errors if finding.get("kind") != "security-candidate"
    ]
    uniquely_partitioned = (
        len(security_errors) == introduced_errors
        and len(non_security_errors) == pre_existing_errors
        and len(candidates) == introduced_errors
    )
    if not uniquely_partitioned:
        return fail_receipt(
            "PER_FINDING_ATTRIBUTION_UNAVAILABLE", counts, len(candidates)
        )
    by_fingerprint: dict[str, dict] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            return fail_receipt("INVALID_SECURITY_CANDIDATE", counts, len(candidates))
        fingerprint = candidate.get("fingerprint")
        if (
            not isinstance(fingerprint, str)
            or candidate.get("finding_id") != fingerprint
            or candidate.get("severity") != "error"
            or fingerprint in by_fingerprint
        ):
            return fail_receipt(
                "AMBIGUOUS_SECURITY_FINGERPRINT", counts, len(candidates)
            )
        by_fingerprint[fingerprint] = candidate
    corrected = []
    for finding in security_errors:
        fingerprint = finding.get("fingerprint")
        candidate = (
            by_fingerprint.get(fingerprint) if isinstance(fingerprint, str) else None
        )
        occurrences = candidate.get("occurrences") if isinstance(candidate, dict) else None
        if not isinstance(occurrences, list) or not occurrences:
            return fail_receipt("MISSING_SECURITY_OCCURRENCES", counts, len(candidates))
        for occurrence in occurrences:
            if not isinstance(occurrence, dict):
                return fail_receipt(
                    "INVALID_SECURITY_OCCURRENCE", counts, len(candidates)
                )
            relative, line = occurrence.get("path"), occurrence.get("line")
            if not isinstance(relative, str) or type(line) is not int or line < 1:
                return fail_receipt("INVALID_SECURITY_LOCATION", counts, len(candidates))
            line_state = current_changed_lines(root, base, relative)
            if line_state is None:
                return fail_receipt(
                    "SECURITY_LOCATION_PROOF_FAILED", counts, len(candidates)
                )
            changed_lines, line_count = line_state
            if line > line_count or line in changed_lines:
                return fail_receipt(
                    "CHANGED_SECURITY_OCCURRENCE", counts, len(candidates)
                )
        if fingerprint in corrected:
            return fail_receipt("DUPLICATE_SECURITY_FINDING", counts, len(candidates))
        corrected.append(fingerprint)
    return {
        "schema_version": "1",
        "result": "pass",
        "basis": (
            "aggregate counts uniquely partition inherited security errors and Git "
            "proves every occurrence unchanged"
        ),
        "upstream_exit": 1,
        "introduced_error_findings": 0,
        "retained_pre_existing_error_findings": pre_existing_errors,
        "inherited_security_fingerprints": sorted(corrected),
    }


def run_new_only(command: list[str], root: Path, base: str) -> int:
    result = subprocess.run(
        command, cwd=root, capture_output=True, text=True, check=False
    )
    if result.stderr:
        sys.stderr.write(result.stderr)
    if result.returncode != 1:
        sys.stdout.write(result.stdout)
        return result.returncode
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        sys.stdout.write(result.stdout)
        return result.returncode
    if not isinstance(report, dict):
        sys.stdout.write(result.stdout)
        return result.returncode
    receipt = new_only_receipt(report, root, base)
    report["hard_eng_gate"] = receipt
    print(json.dumps(report, separators=(",", ":")))
    return 0 if receipt["result"] == "pass" else result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package", default=".", help="Dart package containing pubspec.yaml"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--base", help="Git base ref for new-only audit")
    mode.add_argument("--full", action="store_true", help="Run full JSON gate")
    args = parser.parse_args()

    package = Path(args.package).expanduser().resolve()
    if not package.is_dir() or not (package / "pubspec.yaml").is_file():
        return error("--package must be a Dart package directory")
    root = repository_root(package)
    if root is None:
        return error("package is not inside a Git repository")
    try:
        relative_package = package.relative_to(root)
    except ValueError:
        return error("package resolves outside the Git repository")
    if shutil.which("npx") is None:
        return error("npx is required")

    if args.base:
        if args.base.startswith("-"):
            return error("invalid base ref")
        verified = git(
            root, "rev-parse", "--verify", "--quiet", f"{args.base}^{{commit}}"
        )
        if verified.returncode:
            return error(f"base ref is not a commit: {args.base}")
        command = [
            "npx",
            "--yes",
            "dart-decimate",
            "audit",
            str(root),
            "--base",
            args.base,
            "--format",
            "json",
            "--summary",
            "--gate",
            "new-only",
        ]
    else:
        command = ["npx", "--yes", "dart-decimate", "json", str(root)]
    if relative_package != Path("."):
        command.extend(["--workspace", relative_package.as_posix()])
    if args.base:
        return run_new_only(command, root, args.base)
    return subprocess.run(command, cwd=root, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
