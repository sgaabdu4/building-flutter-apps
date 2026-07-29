#!/usr/bin/env python3
"""Regression proof for direct, canonical Dart Decimate execution."""

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
        ROOT / "hooks/scripts/preflight_audit.sh",
        ROOT / "hooks/scripts/skill_reminder.sh",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in public_files)
    required = (
        "npx --yes dart-decimate@latest",
        "one scan per affected Git root",
        "project-local adapter",
        "`deterministic-checks`",
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
    )
    for marker in forbidden:
        if marker in combined:
            fail(f"stale project-local or unversioned command: {marker}")

    with tempfile.TemporaryDirectory(prefix="dart-decimate-direct-") as temporary:
        root = Path(temporary)
        project = root / "project"
        fake_bin = root / "bin"
        capture = root / "capture.json"
        write(project / "pubspec.yaml", "name: fixture\n")
        write(project / "analysis_options.yaml", "plugins:\n  flutter_skill_lints:\n")
        write(project / "lib/main.dart", "void main() {}\n")
        write(fake_bin / "dart", "#!/bin/sh\nexit 0\n")
        write(
            fake_bin / "git",
            "#!/bin/sh\n"
            "case \"$*\" in\n"
            "  'rev-parse --is-inside-work-tree') echo true ;;\n"
            "  'symbolic-ref --quiet --short refs/remotes/origin/HEAD') echo origin/main ;;\n"
            "  *) exit 0 ;;\n"
            "esac\n",
        )
        write(
            fake_bin / "npx",
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['CAPTURE']).write_text(json.dumps(sys.argv[1:]))\n"
            "print('{\"verdict\":\"pass\"}')\n",
        )
        for executable in (fake_bin / "dart", fake_bin / "git", fake_bin / "npx"):
            executable.chmod(0o755)
        result = subprocess.run(
            [str(ROOT / "hooks/scripts/preflight_audit.sh")],
            cwd=project,
            env={
                **os.environ,
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
            "--yes",
            "dart-decimate@latest",
            "json",
            ".",
        ]:
            fail("preflight did not invoke the latest CLI directly")

    print("dart-decimate-runtime-regressions: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
