"""Code comments are none by default; a changed source file may hold one-line comments only.

Installed agent skills under .agents/ are vendored tooling and are not checked.
"""

import io
import re
import subprocess
import tokenize
from pathlib import Path

from gate_config import changed_files, generated_sources

HASH = {".py", ".pyi", ".sh", ".bash", ".zsh"}
JAVASCRIPT = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx"}
SLASH = {".dart", ".rs", *JAVASCRIPT}
DIRECTIVE = re.compile(
    r"^(#!|#\s*-\*-|//\s*ignore(_for_file)?:|///\s*<reference|//go:|//\s*\+build"
    r"|//\s*#(region|endregion))|(eslint|prettier|biome|jscpd|istanbul|c8|coverage)[-:]"
    r"|@ts-|noqa|type:\s*ignore|pyright:|pylint:|mypy:|pragma|fmt:\s*(off|on|skip)"
    r"|isort:|shellcheck|nolint|NOSONAR|nosemgrep|nosec"
)
# Delimiters, blank comment lines, JSDoc type tags and rustdoc section headings carry no narration.
NEUTRAL = re.compile(
    DIRECTIVE.pattern
    + r"|^(/\*+|\*+/|/\*+\s*\*+/|\*|/{2,}!?|#+)$"
    + r"|^(/\*+|\*|/{2,})\s*@(param|arg|argument|returns?|type|typedef|template|property"
    + r"|prop|callback|satisfies|import|overload|this|enum|extends|augments|implements)\b"
    + r"|^/{3}!?\s*#\s*(Errors|Panics|Safety|Examples?)$"
)


def python_comment_lines(text: str) -> dict[int, str] | None:
    """Full-line comments by tokenizer, so `#` inside strings is not a comment."""
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        return {
            token.start[0]: token.string
            for token in tokens
            if token.type == tokenize.COMMENT and token.line.strip().startswith("#")
        }
    except (tokenize.TokenError, SyntaxError):
        return None


CHARACTER = re.compile(r"'(\\.[^']{0,8}|[^'\\\n])'")
ARITHMETIC = re.compile(r"\$?\(\(.*?\)\)")
HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)\s*((?:'[^']*'|\"[^\"]*\"|[^\s<>|&;()'\"])+)")
RAW = {".rs": re.compile(r'b?r(#*)"'), ".dart": re.compile(r"r('''|\"\"\"|'|\")")}
QUOTE = re.compile(r"'''|\"\"\"|['\"]")
REGEX_BEFORE = re.compile(
    r"(^|[(,=:\[!&|?{};+\-*%<>~^]"
    r"|\b(return|typeof|case|do|else|in|of|new|delete|void|throw|yield|await))\s*$"
)
REGEX = re.compile(r"/(?![/*])(\\.|\[(\\.|[^\]\\\n])*\]|[^/\\\[\n])+/")


def string_end(text: str, index: int, quote: str, raw: bool, line: bool = False) -> int:
    """Index just past the string that opens at index with quote; a line string stops at a newline."""
    while index < len(text):
        if text[index] == "\\" and not raw:
            index += 2
        elif text.startswith(quote, index):
            return index + len(quote)
        elif line and text[index] == "\n":
            return index
        else:
            index += 1
    return len(text)


def string_at(text: str, index: int, suffix: str) -> int | None:
    """Index just past a string or regex literal starting at index, else None."""
    previous = text[index - 1 : index]
    raw = None if previous.isalnum() or previous == "_" else RAW.get(suffix)
    opened = raw.match(text, index) if raw is not None else None
    if opened is not None:
        closing = '"' + opened.group(1) if suffix == ".rs" else opened.group(1)
        return string_end(text, opened.end(), closing, True)
    quote = QUOTE.match(text, index)
    if quote is not None and (quote.group(0) != "'" or suffix != ".rs"):
        line = len(quote.group(0)) == 1 and suffix != ".rs"
        return string_end(text, quote.end(), quote.group(0), False, line)
    regex = REGEX.match(text, index) if suffix in JAVASCRIPT else None
    return regex.end() if regex and regex_allowed(text, index) else None


def regex_allowed(text: str, index: int) -> bool:
    """Whether `/` at index starts a regex: after an operator, keyword or control condition."""
    before = text[max(0, index - 200) : index].rstrip()
    if not before.endswith(")"):
        return REGEX_BEFORE.search(before[-16:]) is not None
    depth = 0
    for position in range(len(before) - 1, -1, -1):
        depth += {")": 1, "(": -1}.get(before[position], 0)
        if depth == 0:
            return (
                re.search(r"\b(if|while|for|with)\s*$", before[:position]) is not None
            )
    return False


def template_end(text: str, index: int) -> tuple[int, bool]:
    """Index just past a template's text, and whether a ${ expression opened there."""
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif text[index] == "`":
            return index + 1, False
        elif text.startswith("${", index):
            return index + 2, True
        else:
            index += 1
    return len(text), False


def code_step(text: str, index: int, suffix: str, depths: list[int]) -> int | None:
    """Index past a template segment, interpolation brace or literal at index, else None."""
    character = text[index]
    if suffix in JAVASCRIPT and (
        character == "`" or (character == "}" and depths[-1:] == [0])
    ):
        if character == "}":
            depths.pop()
        close, interpolating = template_end(text, index + 1)
        depths.extend([0] if interpolating else [])
        return close
    if depths and character in "{}":
        depths[-1] += 1 if character == "{" else -1
        return index + 1
    return string_at(text, index, suffix)


def slash_comment_lines(text: str, suffix: str) -> dict[int, str]:
    """Comment text of each line that opens with a comment or lies in a spanning block."""
    found: dict[int, str] = {}
    index, line, blank = 0, 1, True
    depths: list[int] = []
    while index < len(text):
        character = text[index]
        if character == "\n":
            index, line, blank = index + 1, line + 1, True
        elif character in " \t\r":
            index += 1
        elif text.startswith(("//", "/*"), index):
            close = text.find("\n" if text[index + 1] == "/" else "*/", index + 2)
            close = len(text) if close < 0 else close + (text[index + 1] == "*") * 2
            parts = text[index:close].split("\n")
            if blank or len(parts) > 1:
                found.update(enumerate(parts, line))
            index, line, blank = close, line + len(parts) - 1, False
        elif (close := code_step(text, index, suffix, depths)) is not None:
            index, line, blank = close, line + text.count("\n", index, close), False
        else:
            literal = CHARACTER.match(text, index) if character == "'" else None
            index, blank = (literal.end() if literal else index + 1), False
    return found


def shell_code(line: str, quote: str | None) -> tuple[str, set[int], str | None]:
    """The line before any comment, its quoted positions and the quote still open."""
    code, quoted, escaped = "", set(), False
    for character in line:
        if quote is None and character == "#" and (not code or code[-1].isspace()):
            break
        if escaped:
            escaped = False
        elif character == "\\" and quote != "'":
            escaped = True
        elif character in "\"'" and quote in {None, character}:
            quote = None if quote else character
        if quote is not None:
            quoted.add(len(code))
        code += character
    return code, quoted, quote


def hash_comment_lines(lines: list[str]) -> dict[int, str]:
    """Full-line `#` comments outside shell strings and heredocs."""
    found: dict[int, str] = {}
    heredocs: list[tuple[str, bool]] = []
    quote: str | None = None
    for number, line in enumerate(lines, 1):
        if heredocs:
            delimiter, tabs = heredocs[0]
            if (line.lstrip("\t") if tabs else line) == delimiter:
                heredocs.pop(0)
            continue
        if quote is None and line.lstrip().startswith("#"):
            found[number] = line
            continue
        code, quoted, quote = shell_code(line, quote)
        quoted |= {i for m in ARITHMETIC.finditer(code) for i in range(*m.span())}
        heredocs = [
            (re.sub(r"[\\'\"]", "", opened.group(2)), opened.group(1) == "-")
            for opened in HEREDOC.finditer(code)
            if opened.start() not in quoted
        ]
    return found


def comment_blocks(path: Path) -> list[tuple[int, int]]:
    """(first narration line, narration lines) of each block with more than one."""
    text = path.read_text(errors="replace")
    lines = text.splitlines()
    comments = python_comment_lines(text) if path.suffix in {".py", ".pyi"} else None
    if comments is None:
        comments = (
            slash_comment_lines(text, path.suffix)
            if path.suffix in SLASH
            else hash_comment_lines(lines)
        )
    blocks: list[tuple[int, int]] = []
    start, length = 0, 0
    for number in range(1, len(lines) + 2):
        if number in comments:
            if not NEUTRAL.search(comments[number].strip()):
                start, length = (start, length + 1) if length else (number, 1)
            continue
        if length > 1:
            blocks.append((start, length))
        length = 0
    return blocks


def branch_point(root: Path) -> str:
    """Where HEAD left the shipping base, so committed branch changes count; else HEAD."""
    from shipping import ShippingError, load_policy

    try:
        policy = load_policy(root, required=False)
    except ShippingError:
        policy = None
    for reference in (f"origin/{policy['base']}", policy["base"]) if policy else ():
        found = subprocess.run(
            ["git", "merge-base", "HEAD", reference],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if found.returncode == 0:
            return found.stdout.strip()
    return "HEAD"


def validate_comments(root: Path, base: str | None) -> None:
    names = changed_files(root, base or branch_point(root))
    if names is None:
        raise ValueError(
            "Cannot verify comment scope; fetch or supply a valid Git --base"
        )
    sources = sorted(
        name
        for name in names
        if Path(name).suffix in HASH | SLASH
        and not name.startswith(".agents/")
        and (root / name).is_file()
        and not (root / name).is_symlink()
    )
    skipped = generated_sources(root, sources)
    found = [
        f"{name}:{start} holds a {length}-line comment block"
        for name in sources
        if name not in skipped
        for start, length in comment_blocks(root / name)
    ]
    if found:
        raise ValueError(
            "Code comments are none by default: delete each block below, and add one "
            "terse line of why only where naming, types, structure or a test cannot "
            "carry a needed non-obvious constraint. " + "; ".join(found)
        )
