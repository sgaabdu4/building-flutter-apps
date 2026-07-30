#!/usr/bin/env python3
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parent.parent
COMMANDS = (
    ("python3", "tool/check_skill_routing.py"),
    ("python3", "tool/check_windows_installer_assets.py"),
    ("bash", "tool/check_drift_test.sh"),
    ("bash", "tool/check_drift.sh"),
    ("ruby", "tool/verify_markdown_examples.rb"),
    ("python3", "tool/dart_decimate_gate_test.py"),
    ("bash", "tool/smoke_test.sh"),
    ("ruby", "tool/check_upstream_flutter_skills.rb"),
)


for command in COMMANDS:
    subprocess.run(command, cwd=REPO_ROOT, check=True)
