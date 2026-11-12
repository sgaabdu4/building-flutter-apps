"""The rules for the text of a pull request body."""

from __future__ import annotations

import json
import re
from pathlib import Path

UNDO_LINE = re.compile(r"^[ \t]*Undo:[ \t]*\S", re.MULTILINE)
MERMAID_BLOCK = re.compile(r"^[ \t]*(?:```|~~~)[ \t]*mermaid\b", re.MULTILINE)
NOT_CHECKED_LINE = re.compile(r"^[ \t]*(?:[-*][ \t]+)?Not checked:(.*)$", re.MULTILINE)
EMPTY_ANSWER = re.compile(r"(?:none|nothing|n/a)?[ \t]*[-—–]*", re.IGNORECASE)
DEPENDENCY_BOTS = frozenset({"dependabot[bot]", "renovate[bot]"})
MAX_VISIBLE_CHARACTERS = 6000
MAX_LINE_CHARACTERS = 600
CODE_FENCE = re.compile(
    r"^[ \t]*(`{3,}|~{3,}).*?(?:^[ \t]*\1|\Z)", re.MULTILINE | re.DOTALL
)
HTML_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
DETAILS_TAG = re.compile(r"<(/?)details\b[^>]*>", re.IGNORECASE)
LINK_TARGET = re.compile(r"\]\([^)\n]*\)")


def _blank(match: re.Match[str]) -> str:
    return "\n" * match.group().count("\n")


def _hide_details(text: str) -> str:
    """Blank every details block, nested ones too; an unclosed one hides the rest."""
    depth = 0
    start = 0
    parts: list[str] = []
    for tag in DETAILS_TAG.finditer(text):
        if tag.group(1):
            depth = max(depth - 1, 0)
            if depth == 0:
                parts.append("\n" * text[start : tag.end()].count("\n"))
                start = tag.end()
            continue
        if depth == 0:
            parts.append(text[start : tag.start()])
            start = tag.start()
        depth += 1
    if depth:
        return "".join(parts) + "\n" * text[start:].count("\n")
    return "".join(parts) + text[start:]


def _visible(body: str) -> str:
    """The body without code blocks, folded blocks, comments and link targets."""
    text = body.replace("\r\n", "\n")
    text = CODE_FENCE.sub(_blank, text)
    text = HTML_COMMENT.sub(_blank, text)
    return LINK_TARGET.sub("]()", _hide_details(text))


def _size_problem(body: str) -> str | None:
    """Name a wall of visible text or one very long visible line; None when short."""
    visible = _visible(body)
    size = len(visible.replace("\n", ""))
    if size > MAX_VISIBLE_CHARACTERS:
        return (
            f"PR body shows {size:,} characters outside folded blocks and code blocks; "
            f"the limit is {MAX_VISIBLE_CHARACTERS:,}. Put a short summary first, "
            "and move each long list into a <details> block or link the plan"
        )
    for number, line in enumerate(visible.split("\n"), 1):
        if len(line) > MAX_LINE_CHARACTERS:
            return (
                f"PR body line {number} has {len(line):,} characters "
                f'(it starts "{line.strip()[:40]}"); the limit is {MAX_LINE_CHARACTERS}. '
                "Split it into a list or short paragraphs, or move it into a <details> block"
            )
    return None


def body_problem(body: str) -> str | None:
    """Name what a PR body lacks or has too much of; None when it passes."""
    if not UNDO_LINE.search(body):
        return "PR body needs a line that starts `Undo:` and lists the undo steps"
    if len(MERMAID_BLOCK.findall(body)) < 2:
        return (
            "PR body needs a `Before and after` part with two or more Mermaid diagrams: "
            "one of the old flow and one of the new flow for each main change, "
            "or two or more of the new flows when no old flow exists"
        )
    for found in NOT_CHECKED_LINE.findall(body):
        if not EMPTY_ANSWER.fullmatch(found.strip().rstrip(".")):
            return _size_problem(body)
    return (
        "PR body needs a line that starts `Not checked:`, with the answer on that line: "
        "`Not checked: <what no check covered>`, "
        "or `Not checked: None — <reason>`"
    )


def event_problem(event_path: str, root: Path = Path()) -> str | None:
    """Name what the text of the PR in a GitHub event file lacks; None when it passes."""
    from shipping import ShippingError, load_policy
    from update_runner import UPDATE_BRANCH

    pull = json.loads(Path(event_path).read_text())["pull_request"]
    head_repo = (pull["head"].get("repo") or {}).get("full_name")
    base_repo = (pull["base"].get("repo") or {}).get("full_name")
    if pull["head"]["ref"] == UPDATE_BRANCH and head_repo and head_repo == base_repo:
        return None
    if (pull.get("user") or {}).get("login") in DEPENDENCY_BOTS:
        return None
    try:
        policy = load_policy(root, required=False)
    except ShippingError:
        policy = None
    if policy is not None and pull["base"]["ref"] != policy["base"]:
        return None
    problem = body_problem(pull["body"] or "")
    if problem:
        return f"{problem}. Edit the PR text; this check runs again on each edit."
    return None
