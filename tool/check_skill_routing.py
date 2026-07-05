#!/usr/bin/env python3
"""Validate SKILL.md progressive-disclosure routing.

This is a structural guard for the skill itself. It keeps the hot-path
SKILL.md lean and verifies trigger-map links route to existing files with a
`Read first` section.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "SKILL.md"
MAX_SKILL_LINES = 260
MAX_SKILL_CHARS = 24_000
FORBIDDEN_TRIGGER_REFS = {
    "references/state-management.md",
    "references/extensions-utilities.md",
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

    rows = trigger_map_rows(text)
    if not rows:
        fail("Trigger Map has no routed rows")

    for row in rows:
        for target in markdown_links(row):
            if not target or "://" in target:
                continue
            if target in FORBIDDEN_TRIGGER_REFS:
                fail(f"Trigger Map routes to bulky parent ref: {target}")
            path = (ROOT / target).resolve()
            if not path.exists():
                fail(f"Trigger Map target missing: {target}")
            if path.suffix == ".md":
                body = path.read_text()
                if "## Read first" not in body:
                    fail(f"Trigger Map target lacks '## Read first': {target}")

    print("SKILL_ROUTING_OK")


if __name__ == "__main__":
    main()
