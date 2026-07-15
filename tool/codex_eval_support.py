"""Pure schemas, parsing, and output sanitization for the Codex eval runner."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "expectations_met": {
            "type": "array",
            "items": {"type": "boolean"},
        },
        "notes": {"type": "string"},
    },
    "required": ["expectations_met", "notes"],
    "additionalProperties": False,
}

TRIGGER_SCHEMA = {
    "type": "object",
    "properties": {
        "triggered": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["triggered", "reason"],
    "additionalProperties": False,
}

ROUTING_SCHEMA = {
    "type": "object",
    "properties": {
        "triggered": {"type": "boolean"},
        "refs": {
            "type": "array",
            "items": {"type": "string"},
        },
        "reason": {"type": "string"},
    },
    "required": ["triggered", "refs", "reason"],
    "additionalProperties": False,
}


def parse_skill_md(skill_path: Path) -> tuple[str, str, str]:
    text = (skill_path / "SKILL.md").read_text()
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not match:
        raise ValueError(f"No frontmatter found in {skill_path / 'SKILL.md'}")

    header, body = match.groups()
    name = ""
    desc_lines: list[str] = []
    in_description = False

    for line in header.splitlines():
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip().strip('"')
            in_description = False
            continue
        if line.startswith("description:"):
            raw = line.split(":", 1)[1].strip()
            in_description = raw in {">", ">-", "|", "|-"}
            if not in_description:
                desc_lines.append(raw.strip('"'))
            continue
        if in_description:
            if line and not line.startswith(" ") and ":" in line:
                in_description = False
            else:
                desc_lines.append(line.strip())

    description = " ".join(part for part in desc_lines if part).strip()
    if not name or not description:
        raise ValueError("SKILL.md must include name and description frontmatter")
    return name, description, body


def load_eval_items(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        return list(data.get("evals", []))
    if isinstance(data, list):
        return list(data)
    raise ValueError(f"Unsupported eval file shape: {path}")


def extract_first_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        char = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : idx + 1])
                except json.JSONDecodeError:
                    return None
    return None


def parse_tokens(stderr: str) -> int | None:
    match = re.search(r"tokens used\s+([\d,]+)", stderr, re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def timeout_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def public_path(path: Path, *, base: Path) -> str:
    resolved = path.resolve()
    base = base.resolve()
    try:
        relative = resolved.relative_to(base)
        return "." if str(relative) == "." else str(relative)
    except ValueError:
        pass

    home = Path.home().resolve()
    try:
        return "$HOME/" + str(resolved.relative_to(home))
    except ValueError:
        return str(resolved)


def sanitize_text(text: str) -> str:
    return text.replace(str(Path.home()), "$HOME")


def sanitize_json(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, list):
        return [sanitize_json(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize_json(item) for key, item in value.items()}
    return value
