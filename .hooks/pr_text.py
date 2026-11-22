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
MERMAID_FENCE = re.compile(
    r"^[ \t]*(`{3,}|~{3,})[ \t]*(\w*)[^\n]*\n?(.*?)(?:^[ \t]*\1[`~]*[ \t]*$|\Z)",
    re.MULTILINE | re.DOTALL,
)
MAX_LABEL_CHARACTERS = 13
FLOW_HEAD = re.compile(r"(?:flowchart|graph)\b(?:[ \t]+(?:TD|TB|BT|RL|LR)\b)?[ \t]*;?")
NON_LABEL_STATEMENT = re.compile(
    r"(?:%%|subgraph\b|end\b|style\b|classDef\b|class\b|linkStyle\b|direction\b"
    r"|click\b|acc(?:Title|Descr)\b|title\b(?![ \t]*[\[({>]))"
)
ENTITY_CODE = re.compile(r"#\w+;")
DASH_LABEL = re.compile(r"(?:--|==|-\.)[ \t]+(.+?)[ \t]+(?:-->|==>|\.->|---|===|-\.-)")
QUOTED_PIPE_LABEL = re.compile(r'\|("[^"\n]*")\|')
PIPE_LABEL = re.compile(r"\|([^|\n]*)\|")
ATTRIBUTE_LABEL = re.compile(
    r"""(\w[\w-]*)@\{[^}\n]*?label:[ \t]*["']([^"'\n]*)["'][^}\n]*\}"""
)
SHAPE_LABEL = re.compile(
    r"(\w[\w-]*)(\(\(\(|\(\[|\[\(|\(\(|\[\[|\{\{|\[[/\\]?|[({>])[ \t]*"
    r'("[^"\n]*"|.*?)[ \t]*(\)\)\)|\]\)|\)\]|\)\)|\]\]|\}\}|[/\\]?\]|[)}])'
)
ACC_BLOCK = re.compile(r"accDescr[ \t]*\{")
CLASS_SUFFIX = re.compile(r":::[\w-]+")
ARROW = re.compile(r"[<>ox]?(?:--+|==+|-\.+)[>ox]?|~~~+|&")
BARE_ID = re.compile(r"\w[\w-]*")
LINE_BREAK = re.compile(r"<br[ \t]*/?>", re.IGNORECASE)
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


def _diagrams(body: str) -> list[str]:
    """The text of each Mermaid block that GitHub draws; examples in other fences and comments do not count."""
    text = HTML_COMMENT.sub(_blank, body.replace("\r\n", "\n"))
    return [
        fence.group(3)
        for fence in MERMAID_FENCE.finditer(text)
        if fence.group(2).lower() == "mermaid"
    ]


def _split_statements(line: str) -> list[str]:
    """Split a line at semicolons that are outside quotes and brackets."""
    parts: list[str] = []
    depth = 0
    quoted = False
    start = 0
    for index, char in enumerate(line):
        if char == '"':
            quoted = not quoted
        elif not quoted and char in "([{":
            depth += 1
        elif not quoted and char in ")]}":
            depth = max(depth - 1, 0)
        elif char == ";" and not quoted and depth == 0:
            parts.append(line[start:index])
            start = index + 1
    return [*parts, line[start:]]


def _flow_statements(block: str) -> list[str]:
    lines = [line.strip() for line in block.split("\n")]
    if lines and lines[0] == "---" and "---" in lines[1:]:
        lines = lines[lines.index("---", 1) + 1 :]
    statements: list[str] = []
    header = False
    closing = ""
    for line in lines:
        if closing:
            closing = "" if closing in line else closing
            continue
        if line.startswith("%%{") and "}%%" not in line:
            closing = "}%%"
        if ACC_BLOCK.match(line) and "}" not in line:
            closing = "}"
        if not line or line.startswith("%%"):
            continue
        if not header:
            head = FLOW_HEAD.match(line)
            if not head:
                return []
            header = True
            line = line[head.end() :]
        statements.extend(_split_statements(ENTITY_CODE.sub("\x00", line)))
    return [
        statement.strip()
        for statement in statements
        if statement.strip() and not NON_LABEL_STATEMENT.match(statement.strip())
    ]


def _statement_labels(statement: str, defined: set[str]) -> tuple[list[str], list[str]]:
    """The label texts a statement defines, and the node IDs it only mentions."""
    labels: list[str] = []

    def attribute(match: re.Match[str]) -> str:
        defined.add(match.group(1))
        labels.append(match.group(2).strip())
        return " "

    def node(match: re.Match[str]) -> str:
        defined.add(match.group(1))
        label = match.group(3).strip().strip('"')
        closer = match.group(4)
        if closer in ("/]", "\\]") and match.group(2) not in ("[/", "[\\"):
            label += closer[0]
        labels.append(label)
        return " "

    def edge(match: re.Match[str]) -> str:
        labels.append(match.group(1).strip().strip('"'))
        return " "

    statement = QUOTED_PIPE_LABEL.sub(edge, statement)
    statement = SHAPE_LABEL.sub(node, ATTRIBUTE_LABEL.sub(attribute, statement))
    statement = DASH_LABEL.sub(edge, PIPE_LABEL.sub(edge, statement))
    rest = ARROW.sub(" ", CLASS_SUFFIX.sub(" ", statement))
    return labels, BARE_ID.findall(rest)


def _label_problem(body: str) -> str | None:
    """Name the first flowchart label line over the limit; None when all fit."""
    for block in _diagrams(body):
        defined: set[str] = set()
        labels: list[str] = []
        mentioned: list[str] = []
        for statement in _flow_statements(block):
            found, bare = _statement_labels(statement, defined)
            labels += found
            mentioned += bare
        labels += [name for name in mentioned if name not in defined]
        for label in labels:
            for part in LINE_BREAK.split(label):
                shown = part.strip()
                if len(shown) > MAX_LABEL_CHARACTERS:
                    note = (
                        "; each entity code such as #quot; counts as one character"
                        if "\x00" in shown
                        else ""
                    )
                    return (
                        f'Mermaid label line "{shown.replace(chr(0), "#;")}" has '
                        f"{len(shown)} characters; the limit is {MAX_LABEL_CHARACTERS}, "
                        "because GitHub cuts longer lines at zoom levels other than 100%. "
                        'Split the label with <br> into shorter lines, such as A["Pull request<br>opened"]'
                        f"{note}"
                    )
    return None


def body_problem(body: str) -> str | None:
    """Name what a PR body lacks or has too much of; None when it passes."""
    if not UNDO_LINE.search(body):
        return "PR body needs a line that starts `Undo:` and lists the undo steps"
    if len(_diagrams(body)) < 2:
        return (
            "PR body needs a `Before and after` part with two or more Mermaid diagrams: "
            "one of the old flow and one of the new flow for each main change, "
            "or two or more of the new flows when no old flow exists"
        )
    if problem := _label_problem(body):
        return problem
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
    from plan_parent import named_parents
    from plans import is_plan_path
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
        if is_plan_path(Path(str(item["filename"]))) and item.get("status") != "removed"
    ]
    if not plans and (problem := reference_problem("", visible, body, note)):
        return problem
    texts = {}
    for plan in plans:
        endpoint = f"repos/{owner}/{name}/contents/{plan}?ref={head_sha}"
        try:
            texts[plan] = gh(
                root, "api", "-H", "Accept: application/vnd.github.raw", endpoint
            )
        except ShippingError as error:
            return f"The plan {plan} cannot be read at the PR head ({error})"
    parents = named_parents(texts)
    for plan, text in texts.items():
        if plan not in parents and (
            problem := reference_problem(text, visible, body, note)
        ):
            return problem
    return None
