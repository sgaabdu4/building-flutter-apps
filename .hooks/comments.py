"""Code comments are none by default; a changed source file may hold one-line comments only.

Installed agent skills under .agents/ are vendored tooling and are not checked.
"""

import codecs
import io
import re
import subprocess
import tokenize
from pathlib import Path, PurePosixPath

from debt import git_file
from gate_config import (
    ALL_ZERO_OBJECT_ID,
    changed_files,
    generated_sources,
    initial_point,
)
from plans import _is_test as is_test_path
from plans import default_branch_point

DISABLED_CALL = re.compile(r"\.disabled\(")
QUOTE_OR_BACKSLASH = re.compile(r"[\\'\"]")
UI_SUFFIXES = (
    ".css",
    ".scss",
    ".less",
    ".html",
    ".vue",
    ".svelte",
    ".astro",
    ".jsx",
    ".tsx",
    ".js",
    ".ts",
    ".dart",
    ".swift",
)
UI_MARKS = (
    "-[#",
    "-[rgb",
    "-[hsl",
    "-[oklch",
    "Color(0x",
    "Color.from",
    "Colors.",
    "Color(red",
    "Color(.sRGB",
    "Color(.displayP3",
    "colorLiteral",
)
TEST_ATTRIBUTE = re.compile(r"@(?:Test|Suite)\s*\(")
DIFF_HUNK_HEADER = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)")
CONTROL_KEYWORD_BEFORE = re.compile(r"\b(if|while|for|with)\s*$")
STRING_LITERAL = re.compile(r'"(?:\\.|[^"\\\n])*"')

HASH = {".py", ".pyi", ".sh", ".bash", ".zsh"}
JAVASCRIPT = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx"}
SLASH = {".dart", ".rs", ".swift", *JAVASCRIPT}
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
            (QUOTE_OR_BACKSLASH.sub("", opened.group(2)), opened.group(1) == "-")
            for opened in HEREDOC.finditer(code)
            if opened.start() not in quoted
        ]
    return found


def comment_blocks(path: Path, text: str | None = None) -> list[tuple[int, int, int]]:
    """(first narration line, narration lines, last line) of each block with more than one."""
    text = path.read_text(errors="replace") if text is None else text
    lines = text.splitlines()
    comments = python_comment_lines(text) if path.suffix in {".py", ".pyi"} else None
    if comments is None:
        comments = (
            slash_comment_lines(text, path.suffix)
            if path.suffix in SLASH
            else hash_comment_lines(lines)
        )
    blocks: list[tuple[int, int, int]] = []
    start, length, last = 0, 0, 0
    for number in range(1, len(lines) + 2):
        if number in comments:
            if not NEUTRAL.search(comments[number].strip()):
                start, length = (start, length + 1) if length else (number, 1)
            last = number if length else last
            continue
        if length > 1:
            blocks.append((start, length, last))
        length = 0
    return blocks


def installed_blocks(root: Path, base: str, name: str) -> set[tuple[str, ...]]:
    """Blocks a file held before the change that installs Hard Eng: old code its tools may touch."""
    text = git_file(root, base, name)
    if text is None:
        return set()
    lines = text.splitlines()
    return {
        tuple(lines[start - 1 : last])
        for start, _, last in comment_blocks(root / name, text)
    }


def validate_comments(root: Path, base: str | None) -> None:
    base = base or default_branch_point(root) or "HEAD"
    names = changed_files(root, base)
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
    installing = (root / ".hooks/hard-eng.py").is_file() and (
        git_file(root, base, ".hooks/hard-eng.py") is None
    )
    found: list[str] = []
    for name in sources:
        if name in skipped:
            continue
        older = installed_blocks(root, base, name) if installing else set()
        lines = (root / name).read_text(errors="replace").splitlines()
        found += [
            f"{name}:{start} holds a {length}-line comment block"
            for start, length, last in comment_blocks(root / name)
            if tuple(lines[start - 1 : last]) not in older
        ]
    if found:
        raise ValueError(
            "HE-COMMENT-LINES: Code comments are none by default: delete each block below, and add one "
            "terse line of why only where naming, types, structure or a test cannot "
            "carry a needed non-obvious constraint. " + "; ".join(found)
        )


PYTHON_OFF = re.compile(
    r"#\s*((?:(?:ruff|flake8)\s*:\s*)?(?i:noqa)|type:\s*ignore|pyrefly:\s*ignore"
    r"|pyright:\s*ignore|pyre-(?:ignore|fixme)|pylint:\s*disable|pragma:\s*no cover"
    r"|ruff:\s*(?:file-ignore|ignore|disable)\["
    r"|(?:ruff:\s*)?isort:\s*(?:skip_file|skip|off)\b|fmt:\s*(?:off|skip)\b|yapf:\s*disable\b)|\b(pytest\.)?mark\.(skip(if)?|xfail)\b|pytest\.(skip|xfail)\("
    r"|\bunittest\.([Ss]kip\w*|expectedFailure)\b|\bskipTest\(|\bimportorskip\("
    r"|^\s*@skip(If|Unless)?\(|^__test__\s*=\s*False\b|\braise\s+SkipTest\b"
    r"|^\s*from\s+pytest\s+import\s[^#]*?\b(skip|xfail|importorskip)\b"
)
SCRIPT_OFF = re.compile(
    r"eslint-disable|@ts-(ignore|expect-error|nocheck)|biome-ignore"
    r"|\b(it|test|describe|suite)(?:\.(?:concurrent|sequential|shuffle))*\.(skip|only|fixme|todo|fail|failing|fails|if|runIf)(If)?(?:[.(]|\b)"
    r"|\b(xit|xtest|xdescribe|fit|fdescribe)\("
    r"|(/\*|//)\s*(istanbul|c8|v8) ignore"
)
DART_OFF = re.compile(r"//\s*ignore(_for_file)?:|@Skip\(")
SWIFT_OFF = re.compile(
    r"swift-format-ignore|\bXCTSkip|<(Skipped|Selected)Tests>"
    r'|"(skipped|selected)Tests"|\bskipped\s*=\s*"YES"|\.enabled\(if:\s*false\)'
)
TEST_OFF = {
    ".dart": r"\b(skip|solo):(?=\s*(?!false\b)\S)",
    **dict.fromkeys(JAVASCRIPT, r"\bskip:\s*(true\b|['\"`])|\bonly:\s*true\b"),
}
SECURITY_OFF = re.compile(
    r"\bno(semgrep|sem)\b|gitleaks:allow|jscpd:ignore|fallow-ignore"
    r"|shellcheck\s+disable=|zizmor:\s*ignore|coverage:ignore-",
    re.IGNORECASE,
)
RETRY_WORDS = ("retry", "Retry", "retries", "rerun", "flaky")
SCAN_IGNORES = {".gitleaksignore", ".semgrepignore", ".gitleaks.toml"}
UNOWNED = (".hooks/", ".agents/", ".claude/")


def disabled_traits(text: str) -> set[int]:
    """Lines of `.disabled(` inside @Test(...) and @Suite(...), however the formatter wraps them."""
    lines = set()
    for attribute in TEST_ATTRIBUTE.finditer(text):
        depth, end = 1, attribute.end()
        while end < len(text) and depth:
            if text[end] == '"':
                end = string_end(text, end + 1, '"', False, True)
                continue
            depth += (text[end] == "(") - (text[end] == ")")
            end += 1
        span = STRING_LITERAL.sub(
            lambda string: " " * len(string[0]), text[attribute.start() : end]
        )
        lines |= {
            text.count("\n", 0, attribute.start() + hit.start()) + 1
            for hit in DISABLED_CALL.finditer(span)
        }
    return lines


def disabled_classes(root: Path, name: str, added: list[tuple[int, str]]) -> list[str]:
    """Indented `__test__ = False` marks whose class body holds a test function."""
    marks = [
        n
        for n, t in added
        if "__test__" in t
        and t[:1] in (" ", "\t")
        and "".join(t.split()) == "__test__=False"
    ]
    if not marks:
        return []
    lines = (root / name).read_text(errors="replace").splitlines()
    found = []
    for number in marks:
        indent = len(lines[number - 1]) - len(lines[number - 1].lstrip())
        head = number - 2
        while head >= 0 and (
            not lines[head].strip()
            or len(lines[head]) - len(lines[head].lstrip()) >= indent
        ):
            head -= 1
        if head < 0 or not lines[head].lstrip().startswith("class "):
            continue
        size = len(lines[head]) - len(lines[head].lstrip())
        body = []
        for line in lines[head + 1 :]:
            if line.strip() and len(line) - len(line.lstrip()) <= size:
                break
            body.append(line.strip())
        if any(line.startswith(("def test", "async def test")) for line in body):
            found.append(f"{name}:{number} adds '__test__ = False'")
    return found


def off_hit(pattern: re.Pattern[str], text: str, in_test: bool) -> re.Match[str] | None:
    """The first match, leaving out a skip name used as a bare value outside a test file."""
    for hit in pattern.finditer(text):
        bare = pattern is SCRIPT_OFF and hit[2] and hit[0][-1:] not in "(."
        if in_test or not bare:
            return hit
    return None


def marks_in_file(root: Path, name: str, added: list[tuple[int, str]]) -> list[str]:
    """Switch-offs that only the whole file shows: Swift traits and Python test classes."""
    if name.endswith(".py"):
        marked = any("__test__" in text for _, text in added)
        return (
            disabled_classes(root, name, added)
            if marked and (root / name).is_file()
            else []
        )
    if not name.endswith(".swift") or not (root / name).is_file():
        return []
    traits = disabled_traits((root / name).read_text(errors="replace"))
    return [
        f"{name}:{number} adds '.disabled('" for number, _ in added if number in traits
    ]


def switch_off_pattern(name: str) -> re.Pattern[str] | None:
    suffix = Path(name).suffix
    if suffix == ".py":
        return PYTHON_OFF
    if suffix == ".dart":
        return DART_OFF
    if suffix in {".swift", ".xcscheme", ".xctestplan"}:
        return SWIFT_OFF
    return SCRIPT_OFF if suffix in JAVASCRIPT else None


def diff_base(root: Path, base: str) -> tuple[str, bool]:
    head = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "HEAD"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    unborn = base == "HEAD" and head.returncode == 1
    if unborn or ALL_ZERO_OBJECT_ID.fullmatch(base):
        return initial_point(root)
    return base, False


def header_path(text: str) -> str:
    """Git ends a name holding a space with a tab and C-quotes unusual names."""
    text = text.removesuffix("\t")
    if len(text) > 1 and text[0] == text[-1] == '"':
        text = codecs.escape_decode(text[1:-1].encode())[0].decode(errors="replace")
    return text[2:]


DIFF = (
    "git",
    "-c",
    "core.quotepath=off",
    "diff",
    "-U0",
    "--no-color",
    "--no-ext-diff",
    "--src-prefix=a/",
    "--dst-prefix=b/",
)


def changed_lines(
    diff: str,
) -> tuple[dict[str, list[tuple[int, str]]], dict[str, list[tuple[int, str]]]]:
    """Added and removed (line number, text) pairs per file of a zero-context diff."""
    added: dict[str, list[tuple[int, str]]] = {}
    removed: dict[str, list[tuple[int, str]]] = {}
    name, old, new, in_hunk = "", 0, 0, False
    for line in diff.splitlines():
        hunk = DIFF_HUNK_HEADER.match(line)
        if line.startswith("diff --git "):
            in_hunk = False
        elif hunk:
            old, new, in_hunk = int(hunk[1]), int(hunk[2]), True
        elif in_hunk and line[:1] == "+":
            added.setdefault(name, []).append((new, line[1:]))
            new += 1
        elif in_hunk and line[:1] == "-":
            removed.setdefault(name, []).append((old, line[1:]))
            old += 1
        elif (
            not in_hunk
            and line.startswith(("+++ ", "--- "))
            and line[4:] != "/dev/null"
        ):
            name = header_path(line[4:])
    return added, removed


def diff_lines(
    root: Path, base: str
) -> tuple[dict[str, list[tuple[int, str]]], dict[str, list[tuple[int, str]]]]:
    """Added and removed (line number, text) pairs per file; untracked files count as added."""
    diff = subprocess.check_output(
        [*DIFF, base, "--"], cwd=root, text=True, errors="replace"
    )
    added, removed = changed_lines(diff)
    untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=root,
        text=True,
    )
    for other in filter(None, untracked.split("\0")):
        if (root / other).is_file() and not (root / other).is_symlink():
            text = (root / other).read_text(errors="replace")
            added[other] = list(enumerate(text.splitlines(), 1))
    return added, removed


def assertion_lines(name: str, lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    words = (
        ("assert",)
        if name.endswith(".py")
        else ("assert", "expect(", "XCTAssert", "#require(")
    )
    mark = "#" if name.endswith(".py") else "//"
    return [
        (n, text)
        for n, text in lines
        if any(word in text for word in words) and not text.lstrip().startswith(mark)
    ]


WORD = re.compile(r"[A-Za-z_]\w*")
LITERAL = re.compile(r"\"(\\.|[^\"\\\n])*\"|'(\\.|[^'\\\n])*'|`(\\.|[^`\\\n])*`")
TEST_START = re.compile(
    r"^\s*((async\s+)?def\s|class\s|(it|test|testWidgets|describe|group)(\.\w+)?\()"
)
PYTHON_FUNCTION = re.compile(r"^\s*(?:async\s+)?def\s")
PYTHON_BLOCK = re.compile(r"^\s*(?:(?:async\s+)?def|class)\s")
IMPORT = re.compile(r"^\s*(import|from|export|use)\b|\brequire\(")


def import_or_empty(text: str) -> bool:
    """A line with no text, or an import line that names no test (a Swift `@testable` prefix aside)."""
    if any(mark in text for mark in (".spec", ".test", "_test", " test_", "Test")):
        return not text.strip()
    return not text.strip() or bool(IMPORT.search(text.replace("@testable ", "", 1)))


SYNTAX = {"import", "from", "as", "export", "use", "require", "const", "let", "var"}
DEFINITION = re.compile(
    r"\b(?:def|class|function|fn|struct|enum|trait|interface|mixin|extension)\s+(\w+)"
    r"|^(?:export\s+)?(?:const|let|var|final|type)\s+(?:(?:[\w<>?\[\]]|,\s*)+\s+)?(\w+)\s*(?=[=:;<])"
    r"|^(\w+)\s*(?::[^=]*)?=(?!=)|^(\w+)\s*\(\)\s*\{"
    r"|^[A-Za-z_][\w<>?,\[\] ]*\s(\w+)\s*\("
)


def is_code(name: str) -> bool:
    return Path(name).suffix in HASH | SLASH and not is_test_path(PurePosixPath(name))


def defined_names(text: str) -> list[str]:
    found = DEFINITION.findall(LITERAL.sub(" ", text))
    return [name for groups in found for name in groups if name]


def removed_blocks(lines: list[tuple[int, str]]) -> list[list[tuple[int, str]]]:
    blocks: list[list[tuple[int, str]]] = []
    for number, text in lines:
        if blocks and blocks[-1][-1][0] == number - 1:
            blocks[-1].append((number, text))
        else:
            blocks.append([(number, text)])
    return blocks


def retired_names(
    root: Path, removed: dict[str, list[tuple[int, str]]]
) -> tuple[set[str], set[str]]:
    names = {
        word
        for name, lines in removed.items()
        if is_code(name)
        for _, text in lines
        for word in defined_names(text)
    }
    modules = {
        word
        for name in removed
        if is_code(name) and not (root / name).exists()
        for word in WORD.findall(PurePosixPath(name).stem)
    }
    names |= modules
    remaining = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        text=True,
    )
    for name in filter(None, remaining.split("\0")):
        path = root / name
        if names and is_code(name) and path.is_file() and not path.is_symlink():
            names -= set(WORD.findall(path.read_text(errors="replace")))
    return names, modules & names


def split_tests(block: list[tuple[int, str]]) -> list[list[tuple[int, str]]]:
    tests: list[list[tuple[int, str]]] = [[]]
    function: int | None = None
    for number, text in block:
        level = len(text) - len(text.lstrip())
        code = text.strip() and not text.lstrip().startswith(("#", ")", "]", "}"))
        if code and function is not None and level <= function:
            function = None
        helper = function is not None and level > function and PYTHON_BLOCK.match(text)
        if TEST_START.match(text) and not helper:
            if tests[-1]:
                tests.append([])
            function = level if PYTHON_FUNCTION.match(text) else None
        tests[-1].append((number, text))
    return tests


REMOVAL = re.compile(
    r"^\s*(?:[-*]\s+)?Removed test:\s*(.+?)\s*::\s*(.+?)\s*::\s*(\S.*)$"
)


TEST_NAME = re.compile(
    r"\s*(?:async\s+)?(?:def|class)\s+(\w+)"
    r"|\s*[\w.]+(?:\.each\b.*?\)\s*)?\(\s*(['\"`])(.*?)\2",
    re.DOTALL,
)


def test_name(test: list[tuple[int, str]]) -> str | None:
    if not test or not TEST_START.match(test[0][1]):
        return None
    match = TEST_NAME.match("\n".join(text for _, text in test))
    return match and (match[1] or match[3])


def recorded_removals(added: dict[str, list[tuple[int, str]]]) -> set[tuple[str, str]]:
    return {
        (match[1].strip("`"), match[2].strip("`'\""))
        for name, lines in added.items()
        if PurePosixPath(name).name == "PLAN.md"
        for _, text in lines
        if (match := REMOVAL.match(text))
    }


def lost_assertions(
    blocks: list[tuple[str, list[tuple[int, str]]]],
    retired: tuple[set[str], set[str]],
    recorded: set[tuple[str, str]],
) -> list[str]:
    names, modules = retired
    imported: dict[str, set[str]] = {}
    for name, block in blocks:
        imported.setdefault(name, set()).update(
            word
            for _, text in block
            if IMPORT.search(text) and modules.intersection(WORD.findall(text))
            for word in WORD.findall(text)
        )
    lost: list[str] = []
    for name, block in blocks:
        gone = names | imported[name] - SYNTAX
        for test in split_tests(block):
            text = "\n".join(t for _, t in test)
            if (name, test_name(test)) in recorded:
                continue
            if not gone.intersection(WORD.findall(text)):
                lost += [f"{name}:{n}" for n, _ in assertion_lines(name, test)]
    return lost


def security_switch_offs(
    root: Path, added: dict[str, list[tuple[int, str]]]
) -> list[str]:
    """Inline markers, ignore entries and test retries in any file hide a failing check."""
    names = sorted(name for name in added if not name.startswith(UNOWNED))
    skipped = generated_sources(root, names)
    found: list[str] = []
    for name in (name for name in names if name not in skipped):
        ignore = PurePosixPath(name).name in SCAN_IGNORES
        for number, text in added[name]:
            entry = text.strip()
            if hit := SECURITY_OFF.search(text):
                found.append(f"{name}:{number} adds {hit[0]!r}")
            elif ignore and entry and not entry.startswith("#"):
                found.append(f"{name}:{number} adds {entry!r}")
            elif any(word in text for word in RETRY_WORDS):
                from retry_forms import retry_form, table_retry

                if form := retry_form(name, text) or table_retry(
                    root / name, number, text
                ):
                    found.append(f"{name}:{number} adds {form!r}")
    return found


def ui_candidate(text: str) -> bool:
    return ("transition" in text and "all" in text) or any(
        mark in text for mark in UI_MARKS
    )


def ui_source_check(root: Path, added: dict[str, list[tuple[int, str]]]) -> None:
    marked = {
        name: [(n, t) for n, t in lines if ui_candidate(t)]
        for name, lines in added.items()
        if name.endswith(UI_SUFFIXES)
    }
    if candidates := {name: lines for name, lines in marked.items() if lines}:
        from ui_rules import ui_findings

        if found := ui_findings(root, candidates):
            raise ValueError(
                "HE-UI-SOURCE: Added UI lines must hold no transition on every property "
                "and no colour literal outside a theme or token file. "
                + "; ".join(found)
            )


def validate_suppressions(root: Path, base: str | None) -> None:
    try:
        point, empty = diff_base(root, base or default_branch_point(root) or "HEAD")
        added, removed = diff_lines(root, point)
    except subprocess.CalledProcessError as error:
        raise ValueError(
            "Cannot verify suppression scope; fetch or supply a valid Git --base"
        ) from error
    names = sorted(
        name
        for name in added.keys() | removed.keys()
        if not name.startswith(UNOWNED) and switch_off_pattern(name) is not None
    )
    skipped = generated_sources(root, names)
    found = security_switch_offs(root, added)
    gained = 0
    blocks: list[tuple[str, list[tuple[int, str]]]] = []
    for name in names:
        pattern = switch_off_pattern(name)
        if name in skipped or pattern is None:
            continue
        in_test = is_test_path(PurePosixPath(name))
        tested = in_test and TEST_OFF.get(Path(name).suffix)
        found += [
            f"{name}:{number} adds {hit[0].strip()!r}"
            for number, text in added.get(name, [])
            if (
                hit := off_hit(pattern, text, in_test)
                or (tested and re.search(tested, text))
            )
        ]
        found += marks_in_file(root, name, added.get(name, []))
        if is_test_path(PurePosixPath(name)):
            gained += len(assertion_lines(name, added.get(name, [])))
            blocks += [(name, b) for b in removed_blocks(removed.get(name, []))]
    recorded = recorded_removals(added)
    lost = lost_assertions(blocks, (set(), set()), recorded)
    if len(lost) > gained:
        lost = lost_assertions(blocks, retired_names(root, removed), recorded)
    if len(lost) > gained:
        found.append(
            f"tests lose {len(lost) - gained} assertion lines net "
            f"({len(lost)} removed, {gained} added); removed at {', '.join(lost)}. "
            "To remove a whole test, add `Removed test: <path> :: <test name> :: "
            "<what still proves it or why it is unneeded>` to the plan; the test name "
            "is the function name for a Python test and the text between the quotes "
            "for it(), test() and testWidgets(). An assertion in a test that stays "
            "must stay or get an equal check"
        )
    if found:
        raise ValueError(
            "HE-NO-SWITCH-OFF: A change must not switch a check off: fix the cause instead of "
            "suppressing, skipping, retrying or deleting the check. " + "; ".join(found)
        )
    if not empty:
        ui_source_check(root, added)
