"""Comments and literals of slash-comment sources and Python, found by one scanner that skips strings, templates and regexes."""

import io
import re
import tokenize
from bisect import bisect_right
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path, PurePosixPath

CONTROL_KEYWORD_BEFORE = re.compile(r"(?<![.$])\b(if|while|for|with)\s*$")
JAVASCRIPT = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx"}
SLASH = {".dart", ".rs", ".swift", *JAVASCRIPT}
CHARACTER = re.compile(r"'(\\.[^']{0,8}|[^'\\\n])'")
NESTED_BLOCKS = {".dart", ".rs", ".swift"}
NOT_NEWLINE = re.compile(r"[^\n]")
NOT_LINE_BREAK = re.compile(r"[^\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]")
RAW = {".rs": re.compile(r'b?r(#*)"'), ".dart": re.compile(r"r('''|\"\"\"|'|\")")}
INTERPOLATION_STOP = re.compile(r"[{}'\"]|/[/*]")
SCAN_STOP = re.compile(r"[\n/'\"`{}]|b?r#*['\"]")
QUOTE = re.compile(r"'''|\"\"\"|['\"]")
KEYWORD_BEFORE = r"(?<![.$])\b(return|typeof|case|default|do|else|in|of|new|delete|void|throw|yield|await)"
REGEX_BEFORE = re.compile(
    rf"(^|[(,=:\[!&|?{{}};+\-*%<>~^]|\.\.\.|{KEYWORD_BEFORE})\s*$"
)
PREFIX_NOT = re.compile(rf"{KEYWORD_BEFORE}!$")
REGEX = re.compile(r"/(?![/*])(\\.|\[(\\.|[^\]\\\n])*\]|[^/\\\[\n])+/")


def interpolation_end(text: str, index: int, found: list[tuple[int, int]]) -> int:
    """Index just past the `${...}` expression of a Dart string, whose body starts at index; nested strings and braces count, and each comment in it joins found."""
    depth = 1
    while depth and (stop := INTERPOLATION_STOP.search(text, index)):
        at = stop.start()
        if text[at] == "/" and text[at - 1 : at] == "~":
            index = at + 1
            continue
        if text[at] == "/":
            index = comment_end(text, at, ".dart")
            found.append((at, index))
            continue
        raw = (
            string_at(text, at - 1, ".dart", found)
            if text[at - 1 : at] == "r"
            else None
        )
        if (close := raw or string_at(text, at, ".dart", found)) is not None:
            index = close
        else:
            depth += (text[at] == "{") - (text[at] == "}")
            index = at + 1
    return index if depth == 0 else len(text)


def string_end(
    text: str,
    index: int,
    quote: str,
    raw: bool,
    line: bool = False,
    found: list[tuple[int, int]] | None = None,
) -> int:
    """Index just past the string that opens at index with quote; a line string stops at a newline, and an interpolated Dart string skips its `${...}` expressions."""
    while index < len(text):
        if text[index] == "\\" and not raw:
            index += 2
        elif found is not None and text.startswith("${", index):
            index = interpolation_end(text, index + 2, found)
        elif text.startswith(quote, index):
            return index + len(quote)
        elif line and text[index] == "\n":
            return index
        else:
            index += 1
    return len(text)


def string_at(
    text: str, index: int, suffix: str, found: list[tuple[int, int]] | None = None
) -> int | None:
    """Index just past a string or regex literal starting at index, else None; comments inside a Dart `${...}` join found."""
    previous = text[index - 1 : index]
    raw = None if previous.isalnum() or previous == "_" else RAW.get(suffix)
    opened = raw.match(text, index) if raw is not None else None
    if opened is not None:
        closing = '"' + opened.group(1) if suffix == ".rs" else opened.group(1)
        return string_end(text, opened.end(), closing, True)
    quote = QUOTE.match(text, index)
    if quote is not None and (quote.group(0) != "'" or suffix != ".rs"):
        line = len(quote.group(0)) == 1 and suffix != ".rs"
        interpolated = ([] if found is None else found) if suffix == ".dart" else None
        return string_end(text, quote.end(), quote.group(0), False, line, interpolated)
    regex = REGEX.match(text, index) if suffix in JAVASCRIPT else None
    return regex.end() if regex and regex_allowed(text, index) else None


def regex_allowed(text: str, index: int) -> bool:
    """Whether `/` at index starts a regex: after an operator, keyword or control condition; a postfix `++`, `--` or non-null `!` ends a value, so `/` there divides."""
    before = text[max(0, index - 200) : index].rstrip()
    if before.endswith(("++", "--")) or (
        before.endswith("!")
        and (before[-2:-1].isalnum() or before[-2:-1] in "_$)]")
        and not PREFIX_NOT.search(before[-16:])
    ):
        return False
    if not before.endswith(")"):
        return REGEX_BEFORE.search(before[-16:]) is not None
    depth = 0
    for position in range(len(before) - 1, -1, -1):
        depth += {")": 1, "(": -1}.get(before[position], 0)
        if depth == 0:
            return CONTROL_KEYWORD_BEFORE.search(before[:position]) is not None
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


def code_step(
    text: str,
    index: int,
    suffix: str,
    depths: list[int],
    found: list[tuple[int, int]] | None = None,
) -> int | None:
    """Index past a template segment, interpolation brace or literal at index, else None; comments inside a Dart `${...}` join found."""
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
    return string_at(text, index, suffix, found)


def comment_end(text: str, index: int, suffix: str) -> int:
    """Index just past the comment at index; Dart, Rust and Swift block comments nest."""
    if text[index + 1] == "/":
        close = text.find("\n", index + 2)
        return len(text) if close < 0 else close
    depth, at = 1, index + 2
    while depth and at < len(text):
        if text.startswith("*/", at):
            depth, at = depth - 1, at + 2
        elif suffix in NESTED_BLOCKS and text.startswith("/*", at):
            depth, at = depth + 1, at + 2
        else:
            at += 1
    return at if not depth else len(text)


def scanned_spans(text: str, suffix: str) -> tuple[tuple[bool, int, int, bool], ...]:
    """(whether a comment, start, end, whether only blanks precede it on its line) of each comment and literal."""
    return tuple(scan(text, suffix))


def scan(text: str, suffix: str) -> Iterator[tuple[bool, int, int, bool]]:
    index, blank = 0, True
    depths: list[int] = []
    found: list[tuple[int, int]] = []
    while index < len(text):
        stop = SCAN_STOP.search(text, index)
        if stop is None:
            break
        if stop.start() > index:
            blank = blank and not text[index : stop.start()].strip(" \t\r")
            index = stop.start()
        character = text[index]
        if character == "\n":
            index, blank = index + 1, True
        elif character in " \t\r":
            index += 1
        elif text.startswith(("//", "/*"), index) and not (
            suffix == ".dart" and text[index - 1 : index] == "~"
        ):
            close = comment_end(text, index, suffix)
            yield True, index, close, blank
            index, blank = close, False
        elif (close := code_step(text, index, suffix, depths, found)) is not None:
            if character not in "{}" or close > index + 1:
                yield False, index, close, blank
            yield from ((True, start, end, False) for start, end in found)
            found.clear()
            index, blank = close, False
        else:
            literal = CHARACTER.match(text, index) if character == "'" else None
            index, blank = (literal.end() if literal else index + 1), False


def comment_spans(text: str, suffix: str) -> Iterator[tuple[int, int, bool]]:
    """(start, end, whether only blanks precede it on its line) of each comment outside literals."""
    return (
        (start, close, blank)
        for comment, start, close, blank in scanned_spans(text, suffix)
        if comment
    )


def blank_spans(
    text: str, spans: Iterable[tuple[int, int]], kept: re.Pattern[str] = NOT_NEWLINE
) -> str:
    """The text with each span turned to spaces, except the characters that kept leaves."""
    parts: list[str] = []
    last = 0
    for start, close in spans:
        parts += [text[last:start], kept.sub(" ", text[start:close])]
        last = close
    return "".join([*parts, text[last:]])


def code_without_comments(text: str, suffix: str) -> str:
    """The text with each comment turned to spaces, line breaks kept."""
    return blank_spans(
        text, ((start, close) for start, close, _ in comment_spans(text, suffix))
    )


def outside(
    start: int, close: int, comments: list[tuple[int, int]]
) -> Iterator[tuple[int, int]]:
    """Parts of the literal from start to close that no comment inside a Dart `${...}` covers; comments are in file order."""
    at = bisect_right(comments, start, key=lambda comment: comment[0])
    while at < len(comments) and comments[at][0] < close:
        begin, end = comments[at]
        if end < close:
            yield start, begin
            start = end
        at += 1
    yield start, close


def python_literal_spans(text: str) -> list[tuple[int, int]]:
    starts = [0]
    for line in text.split("\n"):
        starts.append(starts[-1] + len(line) + 1)
    template = getattr(tokenize, "TSTRING_MIDDLE", tokenize.STRING)
    kinds = {tokenize.STRING, tokenize.FSTRING_MIDDLE, template}
    try:
        return [
            (
                starts[token.start[0] - 1] + token.start[1],
                starts[token.end[0] - 1] + token.end[1],
            )
            for token in tokenize.generate_tokens(io.StringIO(text).readline)
            if token.type in kinds
        ]
    except (tokenize.TokenError, SyntaxError):
        return []


def without_literals(name: str, text: str) -> str:
    """The text with the inside of each string and regex literal turned to spaces, its first and last character and every line break kept, so a form that names the opening quote still matches."""
    suffix = PurePosixPath(name).suffix
    if suffix in SLASH:
        scanned = scanned_spans(text, suffix)
        comments = [(start, close) for comment, start, close, _ in scanned if comment]
        spans = [
            piece
            for comment, start, close, _ in scanned
            if not comment
            for piece in outside(start, close, comments)
        ]
    elif suffix in {".py", ".pyi"}:
        spans = python_literal_spans(text)
    else:
        return text
    inside = ((start + 1, close - 1) for start, close in spans if close - start > 2)
    return blank_spans(text, inside, NOT_LINE_BREAK)


UNMASKED = {".js", ".jsx", ".tsx", ".swift"}
LITERAL_HINT = re.compile(r"['\"`/]")
MULTI_LINE_OPENERS = {
    ".py": ("'''", '"""', "\\\n"),
    ".pyi": ("'''", '"""', "\\\n"),
    ".dart": ("'''", '"""', "\\\n"),
    **dict.fromkeys(JAVASCRIPT, ("`", "\\\n")),
    ".rs": ('"', "/*"),
}


def literal_free_lines(root: Path, name: str) -> Callable[[int, str, str | None], str]:
    """Each line of the file with its literals blanked; a line that differs on disk stays as given. Tools that read JSX text or Swift raw strings are not read by the scanner, so those files keep the line as given. Given the text before a hit, a line with no quote or slash there and a file with no multi-line opener stays as given without a scan."""
    suffix = PurePosixPath(name).suffix
    openers = MULTI_LINE_OPENERS.get(suffix)
    read: list[tuple[str, list[str], bool]] = []
    blanked: list[list[str]] = []

    def line(number: int, text: str, before: str | None = None) -> str:
        if openers is None or suffix in UNMASKED:
            return text
        if not read:
            try:
                raw = (root / name).read_text(errors="replace")
            except OSError:
                raw = ""
            raw = raw.replace("\r\n", "\n").replace("\r", "\n")
            read.append((raw, raw.splitlines(), any(o in raw for o in openers)))
        raw, lines, multi = read[0]
        if before is not None and not multi and not LITERAL_HINT.search(before):
            return text
        if not blanked:
            code = code_without_comments(raw, suffix) if suffix == ".rs" else raw
            blanked.append(without_literals(name, code).splitlines())
        same = len(blanked[0]) == len(lines) and lines[number - 1 : number] == [text]
        return blanked[0][number - 1] if same else text

    return line
