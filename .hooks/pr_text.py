"""The rules for the text of a pull request body."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from gate_config import JsonObject, JsonValue

if TYPE_CHECKING:
    from shipping import _PullRequest

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


def _at(value: JsonValue, *keys: str) -> JsonValue:
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def pull_problem(pull: JsonObject, root: Path, number: int) -> str | None:
    """Name what the text of a pull request lacks, as GitHub gives it; None when it passes. CI, `pr-text` and `ship` all call this."""
    from shipping import ShippingError, load_policy
    from update_runner import UPDATE_BRANCH

    head_repo = _at(pull, "head", "repo", "full_name")
    if (
        _at(pull, "head", "ref") == UPDATE_BRANCH
        and head_repo
        and head_repo == _at(pull, "base", "repo", "full_name")
    ):
        return None
    if str(_at(pull, "user", "login") or "") in DEPENDENCY_BOTS:
        return None
    try:
        policy = load_policy(root, required=False)
    except ShippingError:
        policy = None
    if policy is not None and _at(pull, "base", "ref") != policy["base"]:
        return None
    body = str(pull.get("body") or "")
    problem = body_problem(body)
    if not problem and policy is not None and policy["ui_paths"]:
        problem = ui_problem(
            root,
            str(_at(pull, "base", "repo", "full_name") or ""),
            (number, str(_at(pull, "head", "sha") or "")),
            body,
            policy["ui_paths"],
        )
    if problem:
        return f"{problem}. Edit the PR text; this check runs again on each edit."
    return None


def ready_problem(pull: _PullRequest, root: Path, number: int) -> str | None:
    """The CI text check on a pull request that `ship` has already read."""
    return pull_problem(
        {
            "head": {
                "ref": pull.head_ref,
                "sha": pull.head_sha,
                "repo": {"full_name": pull.head_repository},
            },
            "base": {
                "ref": pull.base_ref,
                "repo": {"full_name": pull.base_repository},
            },
            "body": pull.body,
        },
        root,
        number,
    )


def event_problem(event_path: str, root: Path = Path()) -> str | None:
    """Name what the text of the PR in a GitHub event file lacks; None when it passes."""
    pull = json.loads(Path(event_path).read_text())["pull_request"]
    return pull_problem(pull, root, pull["number"])


def fetch_pull(root: Path, repository: str, number: int) -> JsonObject:
    from shipping import ShippingError, gh

    pull = json.loads(gh(root, "api", f"repos/{repository}/pulls/{number}"))
    if not isinstance(pull, dict):
        raise ShippingError("the pull request answer is not an object")
    return pull


def pr_text_command(root: Path, pr: str) -> int:
    """Run the CI text check on a pull request, given by URL or number; 1 with the reason on a fault."""
    from shipping import _pr_url, git, origin_repository

    repository = origin_repository(git(root, "remote", "get-url", "origin").strip())
    if pr.isdecimal():
        number = int(pr)
    else:
        owner, name, number = _pr_url(pr)
        if f"{owner}/{name}".lower() != repository.lower():
            print(
                f"Hard Eng: the PR URL repository does not match origin ({repository}); "
                "its policy is the one that this checkout holds",
                file=sys.stderr,
            )
            return 1
    problem = pull_problem(fetch_pull(root, repository, number), root, number)
    if problem:
        print(f"Hard Eng: {problem}", file=sys.stderr)
        return 1
    print(f"PASS pr-text: {repository}#{number}")
    return 0


def ui_problem(
    root: Path,
    repository: str,
    pull: tuple[int, str],
    body: str,
    patterns: list[str],
) -> str | None:
    """The screen-evidence form of a PR that changes a UI file; CI has no captures, so it checks forms only."""
    from look import block_problem
    from ship_evidence import UI_APPEARANCE_UNCHANGED, attachment_urls
    from shipping import ShippingError, gh
    from ui_proof import (
        Change,
        changed_files,
        file_names,
        reference_problem,
        ui_names,
        visible_files,
    )

    owner, _, name = repository.partition("/")
    number, head_sha = pull
    try:
        files = changed_files(root, owner, name, number)
    except ShippingError as error:
        return f"The list of files that the PR changes is unavailable ({error})"
    try:
        urls = attachment_urls(body, file_names(files), patterns)
    except ValueError as error:
        return str(error)
    if urls and (problem := block_problem(body, len(urls) // 2)):
        return problem
    changes = [
        Change(
            name,
            item["patch"] if is_new and isinstance(item.get("patch"), str) else None,
        )
        for item in files
        for name, is_new in ui_names(item, patterns)
    ]
    visible = visible_files(changes)
    note = bool(UI_APPEARANCE_UNCHANGED.search(body))
    plans = [
        str(item["filename"])
        for item in files
        if str(item["filename"]).endswith("PLAN.md") and item.get("status") != "removed"
    ]
    if not plans and (problem := reference_problem("", visible, body, note)):
        return problem
    for plan in plans:
        endpoint = f"repos/{owner}/{name}/contents/{plan}?ref={head_sha}"
        try:
            text = gh(root, "api", "-H", "Accept: application/vnd.github.raw", endpoint)
        except ShippingError as error:
            return f"The plan {plan} cannot be read at the PR head ({error})"
        if problem := reference_problem(text, visible, body, note):
            return problem
    return None
