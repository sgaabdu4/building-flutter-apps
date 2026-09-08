#!/usr/bin/env python3
"""Regression proof for globally coordinated Dart Decimate execution."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/building-flutter-apps"
REMOVED_BUNDLE = (
    SKILL / "templates/flutter/tool/dart_decimate_pre_push.sh",
    SKILL / "templates/flutter/tool/dart_decimate_gate.py",
    SKILL / "templates/flutter/tool/git_env.py",
)


def fail(message: str) -> None:
    raise SystemExit(f"dart-decimate-runtime-regressions: {message}")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    for path in REMOVED_BUNDLE:
        if path.exists():
            fail(f"project-local runtime returned: {path.relative_to(ROOT)}")

    public_files = [
        SKILL / "SKILL.md",
        SKILL / "references/dart-decimate.md",
        SKILL / "references/setup.md",
        ROOT / "README.md",
        ROOT / "hooks/scripts/preflight_audit.sh",
        ROOT / "hooks/scripts/skill_reminder.sh",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in public_files)
    required = (
        "npx --yes dart-decimate@latest",
        "one scan per affected Git root",
        "project-local adapter",
        "`deterministic-checks`",
        "skills/deterministic-checks/scripts/dart_decimate_gate.py",
    )
    for marker in required:
        if marker not in combined:
            fail(f"missing canonical contract: {marker}")
    forbidden = (
        "python3 tool/dart_decimate_gate.py",
        "templates/flutter/tool/dart_decimate",
        "npx --yes dart-decimate audit",
        "npx --yes dart-decimate json",
        "dart-decimate@latest audit",
        "--gate new-only",
        "npx --yes dart-decimate@latest json .",
    )
    for marker in forbidden:
        if marker in combined:
            fail(f"stale project-local or unversioned command: {marker}")

    preflight = ROOT / "hooks/scripts/preflight_audit.sh"
    if "$(npx --yes dart-decimate@latest" in preflight.read_text(encoding="utf-8"):
        fail("preflight bypasses canonical coordination")

    with tempfile.TemporaryDirectory(prefix="dart-decimate-coordinated-") as temporary:
        root = Path(temporary)
        project = root / "project"
        fake_bin = root / "bin"
        fake_home = root / "home"
        capture = root / "capture.json"
        gate = (
            fake_home
            / ".agents/skills/deterministic-checks/scripts/dart_decimate_gate.py"
        )
        flutter_pubspec = (
            "name: fixture\n"
            "environment:\n"
            "  sdk: ^3.13.0\n"
            "dependencies:\n"
            "  flutter:\n"
            "    sdk: flutter\n"
            "  flutter_riverpod: ^3.4.3\n"
        )
        valid_analysis_options = (
            "plugins:\n"
            "  riverpod_lint: ^3.1.9\n"
            "  flutter_skill_lints: ^0.10.0\n"
        )
        write(project / "pubspec.yaml", flutter_pubspec)
        write(project / "analysis_options.yaml", valid_analysis_options)
        write(project / "lib/main.dart", "void main() {}\n")
        write(fake_bin / "dart", "#!/bin/sh\nexit 0\n")
        write(
            gate,
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['CAPTURE']).write_text(json.dumps(sys.argv[1:]))\n"
        )
        (fake_bin / "dart").chmod(0o755)
        result = subprocess.run(
            [str(preflight)],
            cwd=project,
            env={
                **os.environ,
                "HOME": str(fake_home),
                "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                "CLAUDE_PROJECT_DIR": str(project),
                "CAPTURE": str(capture),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            fail(result.stderr.strip() or "preflight hook failed")
        if json.loads(capture.read_text(encoding="utf-8")) != [
            "--package",
            str(project),
            "--timeout",
            "600",
        ]:
            fail("preflight did not invoke canonical coordination with exact package scope")

        write(
            project / "analysis_options.yaml",
            "analyzer:\n"
            "  plugins:\n"
            "    riverpod_lint: ^3.1.9\n"
            "    flutter_skill_lints: ^0.10.0\n",
        )
        nested = subprocess.run(
            [str(preflight)],
            cwd=project,
            env={
                **os.environ,
                "HOME": str(fake_home),
                "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                "CLAUDE_PROJECT_DIR": str(project),
                "CAPTURE": str(capture),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        if nested.returncode:
            fail(nested.stderr.strip() or "preflight rejected nested plugin fixture")
        if "top-level plugins: map" not in nested.stdout:
            fail("nested analyzer.plugins configuration was accepted")
        if "Add it under analyzer.plugins" in nested.stdout:
            fail("preflight still recommends the legacy analyzer.plugins configuration")

        write(
            project / "analysis_options.yaml",
            "plugins:\n"
            "  riverpod_lint: ^3.1.9\n"
            "  flutter_skill_lints:\n",
        )
        empty_plugin = subprocess.run(
            [str(preflight)],
            cwd=project,
            env={
                **os.environ,
                "HOME": str(fake_home),
                "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                "CLAUDE_PROJECT_DIR": str(project),
                "CAPTURE": str(capture),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        if "Invalid analysis_options.yaml plugin configuration: flutter_skill_lints" not in empty_plugin.stdout:
            fail("preflight accepted an unpinned analyzer plugin")

        write(project / "analysis_options.yaml", valid_analysis_options)
        write(
            project / "pubspec.yaml",
            flutter_pubspec
            + "dev_dependencies:\n"
            + "  flutter_skill_lints: ^0.10.0\n",
        )
        pubspec_plugin = subprocess.run(
            [str(preflight)],
            cwd=project,
            env={
                **os.environ,
                "HOME": str(fake_home),
                "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                "CLAUDE_PROJECT_DIR": str(project),
                "CAPTURE": str(capture),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        if "not pubspec.yaml: flutter_skill_lints" not in pubspec_plugin.stdout:
            fail("preflight accepted an analyzer plugin declared in pubspec.yaml")
        write(project / "pubspec.yaml", flutter_pubspec)

        write(
            project / "analysis_options.yaml",
            "plugins:\n"
            "  flutter_skill_lints: ^0.10.0\n",
        )
        missing_riverpod = subprocess.run(
            [str(preflight)],
            cwd=project,
            env={
                **os.environ,
                "HOME": str(fake_home),
                "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                "CLAUDE_PROJECT_DIR": str(project),
                "CAPTURE": str(capture),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        if "missing plugin(s): riverpod_lint" not in missing_riverpod.stdout:
            fail("preflight accepted a Flutter/Riverpod package without riverpod_lint")

        write(project / "analysis_options.yaml", valid_analysis_options)

        gate.unlink()
        missing = subprocess.run(
            [str(preflight)],
            cwd=project,
            env={
                **os.environ,
                "HOME": str(fake_home),
                "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                "CLAUDE_PROJECT_DIR": str(project),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        if "Canonical Dart Decimate gate unavailable" not in missing.stdout:
            fail("missing canonical coordinator did not fail closed")

        pure_dart = root / "pure_dart"
        write(
            pure_dart / "pubspec.yaml",
            "name: pure_dart_fixture\n"
            "tooling:\n"
            "  flutter: metadata only\n",
        )
        write(pure_dart / "lib/main.dart", "void main() {}\n")
        pure_result = subprocess.run(
            [str(preflight)],
            cwd=pure_dart,
            env={
                **os.environ,
                "HOME": str(fake_home),
                "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                "CLAUDE_PROJECT_DIR": str(pure_dart),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        if pure_result.returncode or pure_result.stdout.strip():
            fail("pure-Dart CLI fixture did not bypass the Flutter/Riverpod preflight")

    print("dart-decimate-runtime-regressions: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
