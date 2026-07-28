#!/usr/bin/env python3
"""Regression proof for the shipped package-scoped Dart Decimate adapter."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE_SCRIPTS = (
    ROOT / "skills/building-flutter-apps/templates/flutter/tool"
)
GATE = GATE_SCRIPTS / "dart_decimate_gate.py"
if str(GATE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(GATE_SCRIPTS))

from git_env import scrub_environ

scrub_environ(ceiling=tempfile.gettempdir())


def fail(message: str) -> None:
    raise SystemExit(f"dart-decimate-gate-regressions: {message}")


def run_git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        fail(result.stderr.strip() or "fixture git failed")
    return result.stdout.strip()


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def invoke(
    package: Path,
    environment: dict[str, str],
    *mode: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE), "--package", str(package), *mode],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )


def aggregate_report(
    introduced_errors: int,
    introduced_warnings: int,
    pre_existing_errors: int,
    pre_existing_warnings: int,
) -> dict:
    errors = [
        {
            "kind": "security-candidate",
            "severity": "error",
            "fingerprint": "sec:fixture",
            "path": "functions/worker/lib/main.dart",
        },
        *(
            {
                "kind": "high-cyclomatic-complexity",
                "severity": "error",
                "fingerprint": f"error-{index}",
                "path": "functions/worker/lib/main.dart",
            }
            for index in range(introduced_errors + pre_existing_errors - 1)
        ),
    ]
    warnings = [
        {
            "kind": "feature-flag",
            "severity": "warning",
            "fingerprint": f"warning-{index}",
            "path": "functions/worker/lib/main.dart",
        }
        for index in range(introduced_warnings + pre_existing_warnings)
    ]
    return {
        "command": "audit",
        "verdict": "fail",
        "summary": {
            "attribution": {
                "introduced": {
                    "findings": introduced_errors + introduced_warnings,
                    "error_findings": introduced_errors,
                    "warning_findings": introduced_warnings,
                },
                "pre_existing": {
                    "findings": pre_existing_errors + pre_existing_warnings,
                    "error_findings": pre_existing_errors,
                    "warning_findings": pre_existing_warnings,
                },
            }
        },
        "findings": [*errors, *warnings],
        "security_candidates": [
            {
                "finding_id": "sec:fixture",
                "fingerprint": "sec:fixture",
                "severity": "error",
                "occurrences": [
                    {"path": "functions/worker/lib/main.dart", "line": 1}
                ],
            }
        ],
    }


def main() -> int:
    reference = ROOT / "skills/building-flutter-apps/references/dart-decimate.md"
    if "bundled Dart Decimate adapter" not in reference.read_text(encoding="utf-8"):
        fail("public adapter ownership is missing")
    skill = ROOT / "skills/building-flutter-apps"
    for pattern in ("*.md", "*.sh", "*.py"):
        for path in skill.rglob(pattern):
            if ".agents/skills/deterministic-checks" in path.read_text(
                encoding="utf-8"
            ):
                fail(f"public resource depends on a machine-local skill: {path}")

    with tempfile.TemporaryDirectory(
        prefix="dart-decimate-scope-"
    ) as temporary:
        temporary_root = Path(temporary)
        root = (temporary_root / "repo").resolve()
        package = root / "functions/worker"
        sibling = root / "apps/mobile"
        duplicate_name = root / "tmp/worker-copy"
        write(root / "pubspec.yaml", "name: workspace_root\n")
        write(package / "pubspec.yaml", "name: worker\n")
        write(package / "lib/main.dart", "void main() {}\n")
        write(sibling / "pubspec.yaml", "name: mobile\n")
        write(sibling / "lib/main.dart", "void main() {}\n")
        write(duplicate_name / "pubspec.yaml", "name: worker\n")
        write(duplicate_name / "lib/main.dart", "void main() {}\n")
        run_git(root, "init", "-q", "-b", "main")
        run_git(root, "config", "user.email", "fixture@example.invalid")
        run_git(root, "config", "user.name", "Fixture")
        run_git(root, "add", ".")
        run_git(root, "commit", "-q", "-m", "baseline")
        write(package / "lib/main.dart", "void main() {}\n// changed line\n")

        fake_bin = temporary_root / "bin"
        capture = temporary_root / "capture.json"
        fake_npx = fake_bin / "npx"
        write(
            fake_npx,
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['DART_DECIMATE_CAPTURE']).write_text("
            "json.dumps({'argv': sys.argv[1:], 'cwd': os.getcwd()}))\n"
            "if os.environ.get('DART_DECIMATE_REPORT'):\n"
            "    print(os.environ['DART_DECIMATE_REPORT'])\n"
            "raise SystemExit(int(os.environ.get('DART_DECIMATE_EXIT', '0')))\n",
        )
        fake_npx.chmod(0o755)
        environment = {
            **os.environ,
            "HOME": str(temporary_root / "empty-home"),
            "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "DART_DECIMATE_CAPTURE": str(capture),
        }

        changed = invoke(package, environment, "--base", "HEAD")
        if changed.returncode:
            fail(changed.stderr.strip() or "nested package gate failed")
        expected_changed = [
            "--yes",
            "dart-decimate",
            "audit",
            str(root),
            "--base",
            "HEAD",
            "--format",
            "json",
            "--summary",
            "--gate",
            "new-only",
            "--workspace",
            "functions/worker",
        ]
        if json.loads(capture.read_text()) != {
            "argv": expected_changed,
            "cwd": str(root),
        }:
            fail("nested package lost exact workspace scope")

        full = invoke(package, environment, "--full")
        if full.returncode:
            fail("nested full gate failed")
        if json.loads(capture.read_text()) != {
            "argv": [
                "--yes",
                "dart-decimate",
                "json",
                str(root),
                "--workspace",
                "functions/worker",
            ],
            "cwd": str(root),
        }:
            fail("nested full gate lost exact workspace scope")

        root_gate = invoke(root, environment, "--base", "HEAD")
        if root_gate.returncode:
            fail("repository-root gate failed")
        root_invocation = json.loads(capture.read_text())
        if "--workspace" in root_invocation["argv"]:
            fail("repository-root package was incorrectly narrowed")

        for upstream_exit in (2, 8):
            blocked = invoke(
                package,
                {**environment, "DART_DECIMATE_EXIT": str(upstream_exit)},
                "--base",
                "HEAD",
            )
            if blocked.returncode != upstream_exit:
                fail(f"upstream exit {upstream_exit} was weakened")

        malformed = "{not-json"
        malformed_result = invoke(
            package,
            {
                **environment,
                "DART_DECIMATE_EXIT": "1",
                "DART_DECIMATE_REPORT": malformed,
            },
            "--base",
            "HEAD",
        )
        if (
            malformed_result.returncode != 1
            or malformed_result.stdout.strip() != malformed
        ):
            fail("malformed upstream report did not fail unchanged")

        unique_report = aggregate_report(1, 3, 52, 97)
        unique = invoke(
            package,
            {
                **environment,
                "DART_DECIMATE_EXIT": "1",
                "DART_DECIMATE_REPORT": json.dumps(unique_report),
            },
            "--base",
            "HEAD",
        )
        corrected = json.loads(unique.stdout)
        if (
            unique.returncode
            or corrected.get("hard_eng_gate", {}).get("result") != "pass"
        ):
            fail("uniquely attributable inherited security error did not pass")
        if corrected["findings"] != unique_report["findings"]:
            fail("attribution correction suppressed upstream evidence")

        write(
            package / "lib/main.dart",
            "void main() { print('changed'); }\n// changed line\n",
        )
        changed = invoke(
            package,
            {
                **environment,
                "DART_DECIMATE_EXIT": "1",
                "DART_DECIMATE_REPORT": json.dumps(unique_report),
            },
            "--base",
            "HEAD",
        )
        if (
            json.loads(changed.stdout).get("hard_eng_gate", {}).get("reason")
            != "CHANGED_SECURITY_OCCURRENCE"
            or changed.returncode != 1
        ):
            fail("changed security occurrence did not fail closed")
        write(package / "lib/main.dart", "void main() {}\n// changed line\n")

        untracked_path = package / "lib/untracked.dart"
        write(untracked_path, "const candidate = 1;\n")
        untracked_report = json.loads(json.dumps(unique_report))
        untracked_report["security_candidates"][0]["occurrences"][0].update(
            {"path": "functions/worker/lib/untracked.dart", "line": 1}
        )
        untracked = invoke(
            package,
            {
                **environment,
                "DART_DECIMATE_EXIT": "1",
                "DART_DECIMATE_REPORT": json.dumps(untracked_report),
            },
            "--base",
            "HEAD",
        )
        if (
            json.loads(untracked.stdout).get("hard_eng_gate", {}).get("reason")
            != "CHANGED_SECURITY_OCCURRENCE"
            or untracked.returncode != 1
        ):
            fail("untracked security occurrence did not fail closed")
        untracked_path.unlink()

        real_shape = aggregate_report(6, 10, 51, 92)
        if len(real_shape["findings"]) != 159:
            fail("real aggregate fixture lost its 159-finding shape")
        ambiguous = invoke(
            package,
            {
                **environment,
                "DART_DECIMATE_EXIT": "1",
                "DART_DECIMATE_REPORT": json.dumps(real_shape),
            },
            "--base",
            "HEAD",
        )
        ambiguous_output = json.loads(ambiguous.stdout)
        ambiguous_receipt = ambiguous_output.get("hard_eng_gate", {})
        expected_counts = {
            "introduced_error_findings": 6,
            "introduced_warning_findings": 10,
            "pre_existing_error_findings": 51,
            "pre_existing_warning_findings": 92,
            "security_candidate_count": 1,
            "per_finding_attribution": False,
        }
        if (
            ambiguous.returncode != 1
            or ambiguous_receipt.get("reason")
            != "PER_FINDING_ATTRIBUTION_UNAVAILABLE"
            or any(
                ambiguous_receipt.get(key) != value
                for key, value in expected_counts.items()
            )
            or ambiguous_output["findings"] != real_shape["findings"]
        ):
            fail("aggregate-only attribution was guessed or lost structural evidence")

        invalid_rollup = json.loads(json.dumps(real_shape))
        invalid_rollup["summary"]["attribution"]["introduced"]["findings"] = 99
        invalid = invoke(
            package,
            {
                **environment,
                "DART_DECIMATE_EXIT": "1",
                "DART_DECIMATE_REPORT": json.dumps(invalid_rollup),
            },
            "--base",
            "HEAD",
        )
        if (
            json.loads(invalid.stdout).get("hard_eng_gate", {}).get("reason")
            != "INVALID_ATTRIBUTION_ROLLUP"
            or invalid.returncode != 1
        ):
            fail("invalid attribution rollup did not fail closed")

        outside = temporary_root / "outside"
        write(outside / "pubspec.yaml", "name: outside\n")
        rejected = invoke(outside, environment, "--base", "HEAD")
        if rejected.returncode != 2:
            fail("package outside a Git repository was not rejected")

    print("dart-decimate-gate-regressions: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
