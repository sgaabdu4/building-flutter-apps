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
        write(project / "pubspec.yaml", "name: fixture\n")
        write(project / "analysis_options.yaml", "plugins:\n  flutter_skill_lints:\n")
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

    print("dart-decimate-runtime-regressions: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
