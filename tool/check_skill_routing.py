#!/usr/bin/env python3
"""Validate skill routing, reference hygiene, and canonical guidance."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "building-flutter-apps"
SKILL = SKILL_ROOT / "SKILL.md"
MAX_SKILL_LINES = 260
MAX_SKILL_CHARS = 24_000
LEGACY_REFERENCE_FILES = {
    "references/crashlytics.md",
    "references/crash-reporting.md",
    "references/state-management.md",
    "references/extensions-utilities.md",
}
FORBIDDEN_GUIDANCE = {
    "child widgets watch providers directly",
    "widgets must watch providers directly",
    "watch providers in leaf widgets",
    "children watch providers directly",
}


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def trigger_map_rows(text: str) -> list[str]:
    match = re.search(r"## Trigger Map\n(?P<body>.*?)(?:\n## |\Z)", text, re.S)
    if not match:
        fail("SKILL.md missing Trigger Map section")
    return [
        line
        for line in match.group("body").splitlines()
        if line.startswith("|") and not line.startswith("|---") and "Touching" not in line
    ]


def markdown_links(text: str) -> list[str]:
    return [target.split("#", 1)[0] for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)]


def main() -> None:
    text = SKILL.read_text()
    lines = text.splitlines()

    if len(lines) > MAX_SKILL_LINES:
        fail(f"SKILL.md has {len(lines)} lines; limit is {MAX_SKILL_LINES}")
    if len(text) > MAX_SKILL_CHARS:
        fail(f"SKILL.md has {len(text)} chars; limit is {MAX_SKILL_CHARS}")
    if "Progressive Disclosure Gate" not in text:
        fail("SKILL.md missing Progressive Disclosure Gate")
    if (
        "| Crashlytics, FirebaseCrashlytics, Sentry,"
        not in text
        or "[error-reporting.md](references/error-reporting.md)" not in text
    ):
        fail("generic error-reporting trigger must route directly to error-reporting.md")

    for legacy in LEGACY_REFERENCE_FILES:
        if (SKILL_ROOT / legacy).exists():
            fail(f"legacy reference still exists: {legacy}")

    rows = trigger_map_rows(text)
    if not rows:
        fail("Trigger Map has no routed rows")

    skill_links = {
        target
        for target in markdown_links(text)
        if target and "://" not in target and target.startswith("references/")
    }

    for row in rows:
        for target in markdown_links(row):
            if not target or "://" in target:
                continue
            path = (SKILL_ROOT / target).resolve()
            if not path.exists():
                fail(f"Trigger Map target missing: {target}")
            if path.suffix == ".md":
                body = path.read_text()
                if "## Read first" not in body:
                    fail(f"Trigger Map target lacks '## Read first': {target}")

    references = sorted((SKILL_ROOT / "references").rglob("*.md"))
    for path in references:
        relative = path.relative_to(SKILL_ROOT).as_posix()
        body = path.read_text()
        if relative not in skill_links:
            fail(f"reference is not linked directly from SKILL.md: {relative}")
        if "## Read first" not in body:
            fail(f"reference lacks '## Read first': {relative}")
        lowered = body.lower()
        for phrase in FORBIDDEN_GUIDANCE:
            if phrase in lowered:
                fail(f"conflicting widget guidance in {relative}: {phrase}")

    routing_eval = json.loads((ROOT / "evals" / "routing-eval.json").read_text())
    if not any(
        "no crash-reporting provider" in case["query"]
        and "references/error-reporting.md" in case["forbidden_refs"]
        for case in routing_eval
    ):
        fail("routing eval must prove no-provider work skips error-reporting.md")
    if not any(
        "inno_bundle" in case["query"]
        and "references/windows-installer-pipeline.md" in case["expected_refs"]
        for case in routing_eval
    ):
        fail("routing eval must prove Windows installer work reads its direct reference")
    if not any(
        "first Flutter Windows release" in case["query"]
        and "references/windows-installer-pipeline.md" in case["expected_refs"]
        for case in routing_eval
    ):
        fail("routing eval must prove bootstrap release work reads its direct reference")
    if not any(
        "notifier lifecycle" in case["query"]
        and "references/windows-installer-pipeline.md" in case["forbidden_refs"]
        for case in routing_eval
    ):
        fail("routing eval must prove non-Windows work skips the Windows reference")
    answer_eval = json.loads((ROOT / "evals" / "evals.json").read_text())["evals"]
    if not any(
        "Unable to find type [checked]" in case["prompt"]
        and any(
            "Parser.ParseFile" in expectation
            for expectation in case["expectations"]
        )
        for case in answer_eval
    ):
        fail("answer eval must reject unparsed PowerShell smoke syntax")
    if not any(
        "$childPidPath.tmp" in case["prompt"]
        and any(
            "literal single-quoted content" in expectation
            for expectation in case["expectations"]
        )
        for case in answer_eval
    ):
        fail("answer eval must reject nested expandable PowerShell source")
    if not any(
        "[Files] AfterInstall" in case["prompt"]
        and any("PrepareToInstall" in expectation for expectation in case["expectations"])
        and any("exit code 7" in expectation for expectation in case["expectations"])
        for case in answer_eval
    ):
        fail("answer eval must reject false AfterInstall forced-failure proof")
    reference_names = {
        path.relative_to(SKILL_ROOT).as_posix()
        for path in (SKILL_ROOT / "references").rglob("*")
        if path.is_file()
    }
    for case in routing_eval:
        for target in case["expected_refs"] + case["forbidden_refs"]:
            if target not in reference_names:
                fail(f"routing eval {case['id']} names missing reference: {target}")
        if case["should_trigger"]:
            for target in case["expected_refs"]:
                if target not in skill_links:
                    fail(f"routing eval {case['id']} expects indirect reference: {target}")

    stale_results = sorted((ROOT / "evals" / "results").glob("*.json"))
    if stale_results:
        fail("tracked/generated eval result artifacts must not be canonical package state")
    if any((ROOT / "evals").glob("*eval-decisions.md")):
        fail("historical eval decision log must not be canonical package state")

    workflow_asset = SKILL_ROOT / "assets" / "windows-installer-workflow.yml"
    if not workflow_asset.is_file():
        fail("Windows installer workflow asset missing")
    if "assets/windows-installer-workflow.yml" not in markdown_links(text):
        fail("Windows installer workflow asset is not linked directly from SKILL.md")

    print("SKILL_ROUTING_OK")


if __name__ == "__main__":
    main()
