#!/usr/bin/env python3
"""Regression tests for the Windows workflow dispatch-input boundary."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "skills/building-flutter-apps/assets/windows-installer-workflow.yml"
REFERENCE = ROOT / "skills/building-flutter-apps/references/windows-installer-pipeline.md"
VALID_REVISION = "a" * 40
VALID_VERSION = "1.2.3"
VALID_RUN_ID = "1234567890"
HOSTILE_VALUES = (
    "'",
    '"',
    "`",
    "$(touch /tmp/workflow-input-injected)",
    ";",
    "line\nfeed",
    "carriage\rreturn",
    "$(Get-Date)",
    "-unexpected-option",
    "nested/path",
    "../escape",
    "x" * 128,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")


def workflow_runs(node: object, path: str = "") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key == "run" and isinstance(value, str):
                found.append((child_path, value))
            else:
                found.extend(workflow_runs(value, child_path))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(workflow_runs(value, f"{path}[{index}]"))
    return found


def validator_source(validation_run: str) -> str:
    match = re.search(r"python3 - <<'PY'\n(?P<body>.*?)\nPY(?:\n|$)", validation_run, re.S)
    require(match is not None, "validator must contain one inline Python program")
    return match.group("body")


def run_validator(source: str, values: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], str]:
    with tempfile.NamedTemporaryFile(prefix="windows-input-output-", delete=False) as handle:
        output_path = Path(handle.name)
    try:
        environment = os.environ.copy()
        environment.update(
            {
                "DISPATCH_MODE": values["mode"],
                "DISPATCH_REVISION": values["revision"],
                "DISPATCH_EVENT_SHA": values["event_sha"],
                "DISPATCH_VERSION": values["version"],
                "DISPATCH_RUN_ID": values["run_id"],
                "GITHUB_OUTPUT": str(output_path),
            }
        )
        result = subprocess.run(
            [sys.executable, "-c", source],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return result, output_path.read_text(encoding="utf-8")
    finally:
        output_path.unlink(missing_ok=True)


def valid_values(mode: str = "publish") -> dict[str, str]:
    return {
        "mode": mode,
        "revision": VALID_REVISION,
        "event_sha": VALID_REVISION,
        "version": VALID_VERSION,
        "run_id": VALID_RUN_ID if mode == "publish" else "",
    }


workflow_text = WORKFLOW.read_text(encoding="utf-8")
reference_text = REFERENCE.read_text(encoding="utf-8")
ruby = shutil.which("ruby")
require(ruby is not None, "YAML regression requires the repository's Ruby runtime")
yaml_result = subprocess.run(
    [ruby, "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.safe_load(STDIN.read))"],
    input=workflow_text,
    capture_output=True,
    text=True,
    cwd=ROOT,
    timeout=10,
    check=False,
)
require(yaml_result.returncode == 0, f"workflow YAML must parse: {yaml_result.stderr}")
workflow = json.loads(yaml_result.stdout)
jobs = workflow["jobs"]
require("validate_inputs" in jobs, "workflow must validate dispatch inputs before checkout jobs")
validation_job = jobs["validate_inputs"]
validation_step = validation_job["steps"][0]
validation_run = validation_step["run"]
source = validator_source(validation_run)

require(validation_job["permissions"] == {}, "input validation must have no repository permissions")
require(validation_job["outputs"]["revision"] == "${{ steps.validate.outputs.revision }}", "revision output must be validator-owned")
require(validation_job["outputs"]["version"] == "${{ steps.validate.outputs.version }}", "version output must be validator-owned")
require(
    validation_step["env"]
    == {
        "DISPATCH_MODE": "${{ inputs.mode }}",
        "DISPATCH_REVISION": "${{ inputs.revision }}",
        "DISPATCH_EVENT_SHA": "${{ github.sha }}",
        "DISPATCH_VERSION": "${{ inputs.version }}",
        "DISPATCH_RUN_ID": "${{ inputs.diagnostic_run_id }}",
    },
    "raw dispatch values must enter only through the validator environment",
)
require("set -euo pipefail" in validation_run, "validator shell must use strict mode")
require("GITHUB_OUTPUT" in source, "validator must emit typed outputs for later jobs")
require(
    "Dispatch input validation" in reference_text
    and "MAJOR.MINOR.PATCH" in reference_text
    and "1-20 decimal digits" in reference_text,
    "Windows reference must document the dispatch grammar",
)
require(
    re.search(r"\[0-9a-f\]\{40\}", source) is not None,
    "validator must require a lowercase 40-character revision",
)
require(
    "verify-windows" in source and "publish" in source,
    "validator must enumerate the two supported modes",
)
require(
    "[0-9]{1,20}" in source,
    "validator must bound diagnostic run IDs to decimal digits",
)
require(
    "[0-9]{0,8}" in source,
    "validator must bound each version component",
)

runs = workflow_runs(workflow)
require(runs, "workflow must contain run blocks")
for path, run in runs:
    require("${{ inputs." not in run, f"dispatch input is embedded in run source at {path}")
    require("${{" not in run, f"workflow expression is embedded in run source at {path}")

for field in ("mode", "revision", "version", "diagnostic_run_id"):
    expression = f"${{{{ inputs.{field} }}}}"
    require(workflow_text.count(expression) == 1, f"raw {field} must have exactly one environment ingress")

for job_name in ("verify_windows", "admission", "publish"):
    job = jobs[job_name]
    require("validate_inputs" in job["needs"], f"{job_name} must depend on pre-checkout validation")
    require("needs.validate_inputs.outputs.mode" in job["if"], f"{job_name} must branch on validated mode")

verify_run = next(run for path, run in runs if "verify_windows" in path and "windows_installer.ps1 verify" in run)
admission_run = next(run for path, run in runs if "admission" in path and "run_linux_release_admission.sh" in run)
publish_run = next(run for path, run in runs if "publish" in path and "windows_installer.ps1 publish" in run)
for run, tokens in (
    (verify_run, ("$env:DISPATCH_REVISION", "$env:DISPATCH_EVENT_SHA", "$env:DISPATCH_VERSION")),
    (admission_run, ("$DISPATCH_REVISION", "$DISPATCH_EVENT_SHA", "$DISPATCH_VERSION", "$DISPATCH_RUN_ID")),
    (publish_run, ("$env:DISPATCH_REVISION", "$env:DISPATCH_EVENT_SHA", "$env:DISPATCH_VERSION", "$env:DISPATCH_RUN_ID", "$env:ADMISSION_ROOT")),
):
    for token in tokens:
        require(token in run, f"release command must consume validated environment data: {token}")

if shutil.which("pwsh"):
    parser = (
        "$tokens=$null; $errors=$null; "
        "[void][System.Management.Automation.Language.Parser]::ParseInput(" 
        "[Console]::In.ReadToEnd(), [ref]$tokens, [ref]$errors); "
        "if (@($errors).Count -ne 0) { $errors | % Message; exit 1 }"
    )
    for path, run in runs:
        if "windows_installer.ps1" not in run:
            continue
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", parser],
            input=run,
            text=True,
            capture_output=True,
            cwd=ROOT,
            timeout=10,
            check=False,
        )
        require(result.returncode == 0, f"PowerShell run block does not parse: {path}: {result.stderr}")

normal_verify = valid_values("verify-windows")
result, output = run_validator(source, normal_verify)
require(result.returncode == 0, "normal verify inputs must pass")
require(
    dict(line.split("=", 1) for line in output.splitlines())
    == {
        "mode": "verify-windows",
        "revision": VALID_REVISION,
        "event_sha": VALID_REVISION,
        "version": VALID_VERSION,
        "diagnostic_run_id": "",
    },
    "validated normal inputs must remain exact literal outputs",
)
result, _ = run_validator(source, valid_values("publish"))
require(result.returncode == 0, "normal publish inputs must pass")

if os.name == "nt":
    with tempfile.TemporaryDirectory(prefix="windows-argument-roundtrip-") as directory:
        script_path = Path(directory) / ".github/scripts/windows_installer.ps1"
        script_path.parent.mkdir(parents=True)
        script_path.write_text(
            "param([string]$Revision, [string]$DispatchRevision, [string]$Version, "
            "[string]$DiagnosticRunId, [string]$AdmissionRoot)\n"
            "[ordered]@{ revision = $Revision; event_sha = $DispatchRevision; "
            "version = $Version; run_id = $DiagnosticRunId; root = $AdmissionRoot } "
            "| ConvertTo-Json -Compress\n",
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment.update(
            {
                "DISPATCH_MODE": "publish",
                "DISPATCH_REVISION": VALID_REVISION,
                "DISPATCH_EVENT_SHA": VALID_REVISION,
                "DISPATCH_VERSION": VALID_VERSION,
                "DISPATCH_RUN_ID": VALID_RUN_ID,
                "ADMISSION_ROOT": r"C:\Program Files\admission",
            }
        )
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", publish_run],
            cwd=directory,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        require(result.returncode == 0, f"PowerShell argument round-trip failed: {result.stderr}")
        require(
            json.loads(result.stdout)
            == {
                "revision": VALID_REVISION,
                "event_sha": VALID_REVISION,
                "version": VALID_VERSION,
                "run_id": VALID_RUN_ID,
                "root": r"C:\Program Files\admission",
            },
            "PowerShell release arguments must remain one exact literal value",
        )

for field in ("mode", "revision", "event_sha", "version", "run_id"):
    for hostile in HOSTILE_VALUES:
        values = valid_values("publish")
        values[field] = hostile
        result, _ = run_validator(source, values)
        require(
            result.returncode != 0,
            f"hostile {field} value must be rejected before release code: {hostile!r}",
        )

for invalid_revision in ("A" * 40, "a" * 39, "a" * 41, "a" * 20 + " " + "a" * 19):
    values = valid_values("publish")
    values["revision"] = invalid_revision
    result, _ = run_validator(source, values)
    require(result.returncode != 0, "invalid revision must fail closed")

print("WINDOWS_INSTALLER_INPUT_CONTRACT_OK")
