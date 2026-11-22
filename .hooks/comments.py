"""Code comments are none by default; a changed source file may hold one-line comments only.

Installed agent skills under .agents/ are vendored tooling and are not checked.
"""

import codecs
import io
import os
import re
import subprocess
import tokenize
from pathlib import Path, PurePosixPath

from gate_config import (
    ALL_ZERO_OBJECT_ID,
    changed_files,
    initial_point,
)
from generated_marks import generated_sources
from plans import _is_test as is_test_path
from plans import default_branch_point
from project_files import GIT_LISTING
from source_scan import (
    JAVASCRIPT,
    SLASH,
    code_without_comments,
    comment_spans,
    literal_free_lines,
    string_end,
    without_literals,
)
from workflow_blocking import hard_eng_workflow, workflow_hits

DIRECTIVE_PAIR = re.compile(r"([\w-]+)=(\S*)")
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
DIFF_HUNK_HEADER = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,(\d+))?")
WALL_SUFFIXES = (".tsx", ".jsx", "hard-eng.gates.json")
STRING_LITERAL = re.compile(r'"(?:\\.|[^"\\\n])*"')

HASH = {".py", ".pyi", ".sh", ".bash", ".zsh"}
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


def python_comment_lines(text: str, trailing: bool = False) -> dict[int, str] | None:
    """Full-line comments by tokenizer, so `#` inside strings is not a comment; trailing adds comments after code."""
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        return {
            token.start[0]: token.string
            for token in tokens
            if token.type == tokenize.COMMENT
            and (trailing or token.line.strip().startswith("#"))
        }
    except (tokenize.TokenError, SyntaxError):
        return None


ARITHMETIC = re.compile(r"\$?\(\(.*?\)\)")
HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)\s*((?:'[^']*'|\"[^\"]*\"|[^\s<>|&;()'\"])+)")


def slash_comment_lines(
    text: str, suffix: str, trailing: bool = False
) -> dict[int, str]:
    """Comment text of each line that opens with a comment or lies in a spanning block; trailing adds comments after code."""
    found: dict[int, str] = {}
    line, counted = 1, 0
    for start, close, blank in comment_spans(text, suffix):
        line, counted = line + text.count("\n", counted, start), start
        parts = text[start:close].split("\n")
        if blank or trailing or len(parts) > 1:
            for number, part in enumerate(parts, line):
                found[number] = f"{found[number]} {part}" if number in found else part
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


def hash_comment_lines(lines: list[str], trailing: bool = False) -> dict[int, str]:
    """Full-line `#` comments outside shell strings and heredocs; trailing adds comments after a command."""
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
        if trailing and len(code) < len(line):
            found[number] = line[len(code) :]
        quoted |= {i for m in ARITHMETIC.finditer(code) for i in range(*m.span())}
        heredocs = [
            (QUOTE_OR_BACKSLASH.sub("", opened.group(2)), opened.group(1) == "-")
            for opened in HEREDOC.finditer(code)
            if opened.start() not in quoted
        ]
    return found


def comment_map(path: Path, text: str, trailing: bool = False) -> dict[int, str]:
    """Comment text by line number: full-line comments, and comments after code when trailing."""
    comments = (
        python_comment_lines(text, trailing) if path.suffix in {".py", ".pyi"} else None
    )
    if comments is None:
        comments = (
            slash_comment_lines(text, path.suffix, trailing)
            if path.suffix in SLASH
            else hash_comment_lines(text.splitlines(), trailing)
        )
    return comments


def comment_blocks(path: Path, text: str | None = None) -> list[tuple[int, int, int]]:
    """(first narration line, narration lines, last line) of each block with more than one."""
    text = path.read_text(errors="replace") if text is None else text
    lines = text.splitlines()
    comments = comment_map(path, text)
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


def block_hits(name: str, path: Path, text: str) -> list[str]:
    return [
        f"{name}:{start} holds a {length}-line comment block"
        for start, length, _ in comment_blocks(path, text)
    ]


COMMENT_HEADER = (
    "HE-COMMENT-LINES: Code comments are none by default: fix each block below at its cause, "
    "so that naming, types, structure or a test carry the meaning, then delete the block; "
    "keep one terse line of why only where they cannot carry a needed non-obvious constraint. "
    "A file that a tool writes passes when .gitattributes marks it linguist-generated by its exact path or a .g.dart, .gr.dart or .freezed.dart suffix. "
    "Never suppress it."
)


def comment_refusal(found: list[str]) -> str:
    return f"{COMMENT_HEADER} " + "; ".join(found)


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
    found = [
        hit
        for name in sources
        if name not in skipped
        for hit in block_hits(
            name, root / name, (root / name).read_text(errors="replace")
        )
    ]
    if found:
        raise ValueError(comment_refusal(found))


PYTHON_OFF = re.compile(
    r"#\s*((?:(?:ruff|flake8)\s*:\s*)?(?i:noqa)|type:\s*ignore|pyrefly:\s*ignore"
    r"|pyright:\s*ignore|pyre-(?:ignore|fixme)|pylint:\s*disable"
    r"|ruff:\s*(?:file-ignore|ignore|disable)\["
    r"|(?:ruff:\s*)?isort:\s*(?:skip_file|skip|off)\b|fmt:\s*(?:off|skip)\b|yapf:\s*disable\b)|\b(pytest\.)?mark\.(skip(if)?|xfail)\b|pytest\.(skip|xfail)\("
    r"|\bunittest\.([Ss]kip\w*|expectedFailure)\b|\bskipTest\(|\bimportorskip\("
    r"|^\s*@skip(If|Unless)?\(|^__test__\s*=\s*False\b|\braise\s+SkipTest\b"
    r"|^\s*from\s+pytest\s+import\s[^#]*?\b(skip|xfail|importorskip)\b"
)
SCRIPT_OFF = re.compile(
    r"eslint-disable|@ts-(ignore|expect-error|nocheck)|biome-ignore"
    r"|(?:^\s*(?:\*(?=\s))?\s*|(?://|/\*+(?:\s+\*(?=\s))?)\s*)fallow-override-threshold-next-line\b[\s,]+max(?:Cyclomatic|Cognitive|Crap|UnitSize)\s*="
    r"|\b(it|test|describe|suite)(?:\.(?:concurrent|sequential|shuffle))*\.(skip|only|fixme|todo|fail|failing|fails|if|runIf)(If)?(?:[.(]|\b)"
    r"|\b(xit|xtest|xdescribe|fit|fdescribe)\("
)
DART_OFF = re.compile(r"//\s*ignore(_for_file)?:|@Skip\(")
SWIFT_OFF = re.compile(
    r"swift-format-ignore|\bXCTSkip|<(Skipped|Selected)Tests>"
    r'|"(skipped|selected)Tests"|\bskipped\s*=\s*"YES"|\.enabled\(if:\s*false\)'
)
RUST_OFF = re.compile(
    r"#\s*!?\s*\[\s*(?:allow|expect)\s*\(|#\s*!?\s*\[\s*ignore\b"
    r"|\brustfmt\s*::\s*skip\b"
)
RUST_CFG_ATTR = re.compile(
    r"#\s*!?\s*\[\s*cfg_attr\s*\([^\]]*?\b(?:(?:allow|expect)\s*\(|ignore\b)"
    r"|#\s*!?\s*\[\s*cfg(?:_attr)?\s*\([^\]]*?\bnot\s*\(\s*clippy\s*\)"
)
TEST_OFF = {
    ".dart": r"\b(skip|solo):(?=\s*(?!false\b)\S)",
    **dict.fromkeys(JAVASCRIPT, r"\bskip:\s*(true\b|['\"`])|\bonly:\s*true\b"),
}
SECURITY_OFF = re.compile(
    r"\bno(semgrep|sem)\b|gitleaks:allow|jscpd:ignore|fallow-ignore"
    r"|shellcheck\s+(?:[\w-]+=\S+\s+)*(?:(?:disable|shell)=|source=\S*)|zizmor:\s*ignore|coverage:ignore-",
    re.IGNORECASE,
)
RAW_OFF = {
    ".py": re.compile(
        r"#\s*(?:pragma:\s*no cover|(?:(?:ruff|flake8)\s*:\s*)?(?i:noqa)"
        r"|pyre-(?:ignore|fixme)|type:\s*ignore"
        r"|(?:ruff:\s*)?isort:\s*(?:skip_file|skip|off)\b)"
    ),
    ".dart": re.compile(r"//\s*dart-decimate-ignore-(?:next-line(?![\w-])|file\b)"),
    **dict.fromkeys(JAVASCRIPT, re.compile(r"(/\*|//)\s*(istanbul|c8|v8) ignore")),
}
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
    if suffix == ".rs":
        return RUST_OFF
    return SCRIPT_OFF if suffix in JAVASCRIPT else None


def pattern_switch_offs(
    root: Path, name: str, lines: list[tuple[int, str]], verb: str
) -> list[str]:
    """Suppressions, skips and focus marks in the lines of one source file."""
    pattern = switch_off_pattern(name)
    if pattern is None:
        return []
    in_test = is_test_path(PurePosixPath(name))
    tested = in_test and TEST_OFF.get(Path(name).suffix)

    def off(text: str) -> re.Match[str] | None:
        return off_hit(pattern, text, in_test) or (
            re.search(tested, text) if tested else None
        )

    raw = RAW_OFF.get(Path(name).suffix)
    code = literal_free_lines(root, name)
    wrapped = (
        rust_cfg_attr_hits(root, name, lines, verb) if name.endswith(".rs") else []
    )
    found = []

    def masked(number: int, text: str) -> re.Match[str] | None:
        first = off(text)
        return first and off(code(number, text, text[: first.start()]))

    for number, text in lines:
        if hit := (raw.search(text) if raw else None) or masked(number, text):
            found.append(f"{name}:{number} {verb} {hit[0].strip()!r}")
    return found + wrapped + marks_in_file(root, name, lines)


def rust_cfg_attr_hits(
    root: Path, name: str, lines: list[tuple[int, str]], verb: str
) -> list[str]:
    """A `cfg_attr` that allows or ignores, or a `cfg` or `cfg_attr` that holds `not(clippy)`, read as Rust reads it: across lines, outside comments and strings."""
    try:
        raw = (root / name).read_text(errors="replace")
    except OSError:
        return []
    if "cfg" not in raw:
        return []
    masked = without_literals(name, code_without_comments(raw, ".rs"))
    wanted = {number for number, _ in lines}
    found = []
    for hit in RUST_CFG_ATTR.finditer(masked):
        first = masked.count("\n", 0, hit.start()) + 1
        last = first + hit[0].count("\n")
        if wanted.intersection(range(first, last + 1)):
            found.append(f"{name}:{first} {verb} {' '.join(hit[0].split())!r}")
    return found


SWITCH_OFF_HEADER = (
    "HE-NO-SWITCH-OFF: A change must not switch a check off: fix the cause instead of "
    "suppressing, skipping, retrying or deleting the check. A file that a tool writes "
    "passes when .gitattributes marks it linguist-generated by its exact path or a "
    ".g.dart, .gr.dart or .freezed.dart suffix."
)


def switch_off_refusal(found: list[str]) -> str:
    return f"{SWITCH_OFF_HEADER} " + "; ".join(found)


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
    diff: str, joins: dict[str, list[int]] | None = None
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
            if joins is not None and hunk[3] == "0":
                joins.setdefault(name, []).extend([new, new + 1] if new else [1])
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
    root: Path, base: str, joins: dict[str, list[int]] | None = None
) -> tuple[dict[str, list[tuple[int, str]]], dict[str, list[tuple[int, str]]]]:
    """Added and removed (line number, text) pairs per file; untracked files count as added."""
    diff = subprocess.check_output(
        [*DIFF, base, "--"], cwd=root, text=True, errors="replace"
    )
    added, removed = changed_lines(diff, joins)
    untracked = subprocess.check_output(
        [*GIT_LISTING, "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=root,
        text=True,
    )
    for other in filter(None, untracked.split("\0")):
        if (root / other).is_symlink():
            added[other] = [(1, os.readlink(root / other))]
        elif (root / other).is_file():
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
        [*GIT_LISTING, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
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


def entry_file(root: Path, name: str, names: set[str]) -> bool:
    """A file of ignore entries that every line refuses; a regular root .gitleaksignore is judged by the full check's scan instead."""
    return PurePosixPath(name).name in names and (
        name != ".gitleaksignore" or (root / name).is_symlink()
    )


SHELLCHECK_FIX = "read the file without a dynamic `source`"


def followed_source(root: Path, name: str, marker: str) -> bool:
    """A shellcheck directive that hides nothing: no `disable=` or `shell=` key, and every `source=` names a file in the project, which shellcheck then reads; /dev/null and a missing path hide the finding."""
    keys = DIRECTIVE_PAIR.findall(marker)
    if any(key in {"disable", "shell"} for key, _ in keys):
        return False
    sources = [value for key, value in keys if key == "source"]
    return bool(sources) and all(
        any(
            (base / value).is_file()
            for base in (root / PurePosixPath(name).parent, root)
        )
        for value in sources
    )


def security_hits(
    root: Path,
    name: str,
    lines: list[tuple[int, str]],
    verb: str,
    entries: bool,
) -> list[str]:
    """Inline markers, ignore entries and test retries in the lines of one file; entries marks a file of ignore entries."""
    found: list[str] = []
    for number, text in lines:
        entry = text.strip()
        if (hit := SECURITY_OFF.search(text)) and not followed_source(
            root, name, hit[0]
        ):
            fix = (
                f"; {SHELLCHECK_FIX}"
                if "shellcheck" in hit[0] and "disable=" not in hit[0]
                else ""
            )
            if PurePosixPath(name).name == "gradlew":
                fix += "; Gradle generates this wrapper: mark its exact path `<path> linguist-generated=true` in .gitattributes"
            found.append(f"{name}:{number} {verb} {hit[0]!r}{fix}")
        elif entries and entry and not entry.startswith("#"):
            found.append(f"{name}:{number} {verb} {entry!r}")
        elif any(word in text for word in RETRY_WORDS):
            from retry_forms import retry_form, table_retry

            if form := retry_form(name, text) or table_retry(root / name, number, text):
                found.append(f"{name}:{number} {verb} {form!r}")
    return found


def security_switch_offs(
    root: Path, added: dict[str, list[tuple[int, str]]]
) -> list[str]:
    names = sorted(name for name in added if not name.startswith(UNOWNED))
    skipped = generated_sources(root, names)
    found = [
        hit
        for name in names
        if name not in skipped
        for hit in security_hits(
            root, name, added[name], "adds", entry_file(root, name, SCAN_IGNORES)
        )
    ]
    for name in names:
        if hard_eng_workflow(name) and (root / name).is_file():
            found += workflow_hits(name, (root / name).read_text())
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


def scoped_names(
    added: dict[str, list[tuple[int, str]]], removed: dict[str, list[tuple[int, str]]]
) -> list[str]:
    return sorted(
        name
        for name in added.keys() | removed.keys()
        if not name.startswith(UNOWNED) and switch_off_pattern(name) is not None
    )


def assertion_balance(
    root: Path,
    added: dict[str, list[tuple[int, str]]],
    removed: dict[str, list[tuple[int, str]]],
    skipped: set[str],
) -> tuple[list[str], int]:
    gained = 0
    blocks: list[tuple[str, list[tuple[int, str]]]] = []
    for name in scoped_names(added, removed):
        if name not in skipped and is_test_path(PurePosixPath(name)):
            gained += len(assertion_lines(name, added.get(name, [])))
            blocks += [(name, b) for b in removed_blocks(removed.get(name, []))]
    recorded = recorded_removals(added)
    lost = lost_assertions(blocks, (set(), set()), recorded)
    if len(lost) > gained:
        lost = lost_assertions(blocks, retired_names(root, removed), recorded)
    return lost, gained


def is_ancestor(root: Path, older: str, newer: str) -> bool:
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", older, newer],
            cwd=root,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def whole_branch_balance(root: Path, point: str) -> tuple[str, list[str], int] | None:
    """The assertion balance from the branch point, when it lies before the judged range."""
    whole = default_branch_point(root)
    if not whole or whole == point or not is_ancestor(root, whole, point):
        return None
    added, removed = diff_lines(root, whole)
    skipped = generated_sources(root, scoped_names(added, removed))
    return whole, *assertion_balance(root, added, removed, skipped)


def flutter_changed(root: Path, names: list[str]) -> bool:
    if not any(name.endswith((".dart", ".arb")) for name in names):
        return False
    from flutter_screens import screen_files

    return bool(screen_files(root, names))


def text_walls_check(
    root: Path,
    point: str,
    joins: dict[str, list[int]],
    added: dict[str, list[tuple[int, str]]],
    removed: dict[str, list[tuple[int, str]]],
) -> None:
    names = [*joins, *added, *removed]
    if any(name.endswith(WALL_SUFFIXES) for name in names) or flutter_changed(
        root, names
    ):
        from text_walls import wall_check

        wall_check(root, added, removed, joins, point)


def added_switch_offs(
    root: Path,
    added: dict[str, list[tuple[int, str]]],
    names: list[str],
    skipped: set[str],
) -> list[str]:
    found = security_switch_offs(root, added)
    for name in names:
        if name not in skipped:
            found += pattern_switch_offs(root, name, added.get(name, []), "adds")
    return found


def whole_refusals(root: Path) -> list[str]:
    from whole_project import validate_whole_project

    try:
        validate_whole_project(root)
    except ValueError as error:
        return [str(error)]
    return []


def validate_rules(
    root: Path, base: str | None, screens: bool = True, full: bool = False
) -> None:
    """The full check leaves changed-line findings to the whole-project pass, which holds them all, so one run lists everything."""
    if not full:
        validate_comments(root, base)
    validate_suppressions(root, base, screens, full)


def validate_suppressions(
    root: Path, base: str | None, screens: bool = True, full: bool = False
) -> None:
    joins: dict[str, list[int]] = {}
    try:
        point, empty = diff_base(root, base or default_branch_point(root) or "HEAD")
        added, removed = diff_lines(root, point, joins)
    except subprocess.CalledProcessError as error:
        raise ValueError(
            "Cannot verify suppression scope; fetch or supply a valid Git --base"
        ) from error
    names = scoped_names(added, removed)
    skipped = generated_sources(root, names)
    lost, gained = assertion_balance(root, added, removed, skipped)
    if len(lost) > gained and base and (whole := whole_branch_balance(root, point)):
        point, lost, gained = whole
    found = [] if full else added_switch_offs(root, added, names, skipped)
    if len(lost) > gained:
        found.append(
            f"tests lose {len(lost) - gained} assertion lines net "
            f"({len(lost)} removed, {gained} added) since {point[:12]}; "
            f"removed at {', '.join(lost)}. "
            "To remove a whole test, add `Removed test: <path> :: <test name> :: "
            "<what still proves it or why it is unneeded>` to the plan; the test name "
            "is the function name for a Python test and the text between the quotes "
            "for it(), test() and testWidgets(). An assertion in a test that stays "
            "must stay or get an equal check"
        )
    refusals = [switch_off_refusal(found)] if found else []
    refusals += whole_refusals(root) if full else []
    if refusals:
        raise ValueError("\n".join(refusals))
    if not empty:
        ui_source_check(root, added)
        if screens:
            text_walls_check(root, point, joins, added, removed)
