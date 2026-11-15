"""HE-NO-TEXT-WALLS: screen text comes in short blocks, counted by one measure and one settings reader."""

import json
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Sequence
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from comments import is_test_path
from flutter_screens import screen_files
from gate_config import generated_sources
from project_files import GIT_LISTING
from text_readers import Block, FileBlocks, read

SLOT = ""
WORD = re.compile(r"\S+")
HAS_LETTER_OR_DIGIT = re.compile(r"[^\W_]")
CLOSERS = "\"')]}”’»"
OPENERS = "\"'“‘("
SENTENCE_ENDS = (".", "!", "?", "…")
CJK_ENDS = ("。", "！", "？")
ABBREVIATIONS = frozenset(
    ("e.g.", "i.e.", "etc.", "vs.", "mr.", "mrs.", "ms.", "dr.", "st.", "no.")
    + ("approx.", "incl.", "min.", "max.", "a.m.", "p.m.")
)
DOTTED = re.compile(r"^(?:[^\W\d_]\.)+$")
CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿]+")
CJK_END = re.compile(r"([。！？])")
KEYS = {
    "words_per_block": 25,
    "sentences_per_block": 3,
    "words_per_sentence": 20,
}
DEFAULT_NUMBERS = (25, 3, 20)
INLINE = ("strong", "em", "b", "i", "span", "a", "Link", "sup", "sub", "u", "small") + (
    "mark",
    "abbr",
    "time",
    "q",
    "cite",
    "s",
    "del",
    "ins",
    "kbd",
    "var",
)
TEXT_PROPS = (
    "title",
    "label",
    "description",
    "body",
    "message",
    "subtitle",
    "hint",
) + ("helperText", "note", "text", "details", "summary", "caption", "lead")
SKIP = ("script", "Script", "style", "code", "pre")
STORED = ("body", "content", "description", "details", "notes") + (
    "note",
    "summary",
    "comment",
    "bio",
    "about",
)
TAP_NAMES = (
    "button",
    "a",
    "Link",
    "summary",
    "Pressable",
    "TouchableOpacity",
    "TouchableHighlight",
)
TAP_ATTRS = ("onClick", "onPress", "href")
USER_CONTENT = "UserContent"
DART_PROPS = ("labelText", "hintText", "errorText", "tooltip")
DART_TAP_NAMES = ("ExpansionTile",)
DART_TAP_ATTRS = ("onTap", "onPressed", "onLongPress")


class SettingsError(ValueError):
    pass


class Caps(NamedTuple):
    words: int
    sentences: int
    sentence_words: int
    paths: tuple[str, ...]


def flatten(parts: list[object]) -> str:
    out: list[str] = []
    for part in parts:
        if isinstance(part, str):
            out.append(part)
        elif isinstance(part, dict) and "alt" in part:
            branches = [flatten(branch) for branch in part["alt"]]
            out.append(max(branches, key=lambda text: measure_line(text)[:2]))
        else:
            out.append(SLOT)
    return "".join(out)


def word_weight(token: str) -> int:
    if SLOT in token:
        return 1
    if not HAS_LETTER_OR_DIGIT.search(token):
        return 0
    runs = CJK.findall(token)
    if not runs:
        return 1
    rest = HAS_LETTER_OR_DIGIT.search(CJK.sub("", token))
    return sum((len(run) + 1) // 2 for run in runs) + bool(rest)


def ends_sentence(token: str, following: str | None) -> bool:
    core = token.rstrip(CLOSERS)
    if core.endswith(CJK_ENDS):
        return True
    if not core.endswith(SENTENCE_ENDS):
        return False
    if following is None:
        return True
    if core.lower() in ABBREVIATIONS or DOTTED.match(core):
        return False
    head = following.lstrip(CLOSERS + OPENERS)[:1]
    return head == SLOT or head.isupper() or head.isdigit() or not head.isalpha()


def measure_line(text: str) -> tuple[int, int, int]:
    tokens = WORD.findall(text)
    words = sentences = longest = current = 0
    for index, token in enumerate(tokens):
        weight = word_weight(token)
        words += weight
        current += weight
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        if current and ends_sentence(token, following):
            sentences += 1
            longest = max(longest, current)
            current = 0
    if current:
        sentences += 1
        longest = max(longest, current)
    return words, sentences, longest


def measure(parts: list[object]) -> tuple[int, int, int]:
    """Words, sentences and the longest sentence of one block; a line break ends a sentence."""
    lines = [
        measure_line(CJK_END.sub(r"\1 ", line)) for line in flatten(parts).split("\n")
    ]
    return (
        sum(line[0] for line in lines),
        sum(line[1] for line in lines),
        max(line[2] for line in lines),
    )


def settings(root: Path) -> Caps:
    """The caps of a project; each key is optional, so a project can change a number, never a file."""
    try:
        data = json.loads((root / "hard-eng.gates.json").read_text())
    except (OSError, ValueError):
        data = None
    raw = data.get("text_walls") if isinstance(data, dict) else None
    if raw is None:
        return Caps(*DEFAULT_NUMBERS, ())
    if not isinstance(raw, dict):
        raise SettingsError(
            "HE-NO-TEXT-WALLS: `text_walls` in hard-eng.gates.json must be an object; "
            "remove it or give it the keys " + ", ".join([*KEYS, "paths"])
        )
    unknown = sorted(set(raw) - {*KEYS, "paths"})
    if unknown:
        raise SettingsError(
            f"HE-NO-TEXT-WALLS: `text_walls` has the unknown key {unknown[0]!r}; "
            "remove it or use " + ", ".join([*KEYS, "paths"])
        )
    numbers: list[int] = []
    for key, default in KEYS.items():
        value = raw.get(key, default)
        if type(value) is not int or value < 1:
            raise SettingsError(
                f"HE-NO-TEXT-WALLS: `text_walls.{key}` must be a whole number of 1 or more; "
                "set it in hard-eng.gates.json or remove it to use " + str(default)
            )
        numbers.append(value)
    paths = raw.get("paths", [])
    if not isinstance(paths, list) or not all(
        isinstance(path, str) and path.endswith("/**") for path in paths
    ):
        raise SettingsError(
            "HE-NO-TEXT-WALLS: `text_walls.paths` must be a list of folder globs that "
            "end in /**, for example app/**; it narrows the folders and never exempts a file"
        )
    return Caps(numbers[0], numbers[1], numbers[2], tuple(paths))


def reader_query(
    files: Sequence[tuple[str, str, Sequence[int] | None]], kind: str = "js"
) -> dict[str, object]:
    """The query that every reader takes: the word lists and each file with its touched lines."""
    dart = kind == "dart"
    return {
        "inline": INLINE,
        "text_props": (*TEXT_PROPS, *DART_PROPS) if dart else TEXT_PROPS,
        "skip": SKIP,
        "user": USER_CONTENT,
        "stored": STORED,
        "tap_names": DART_TAP_NAMES if dart else TAP_NAMES,
        "tap_attrs": DART_TAP_ATTRS if dart else TAP_ATTRS,
        "files": [
            {"path": path, "source": source, "touched": touched}
            for path, source, touched in files
        ],
    }


PLAIN_WORD = re.compile(r"[A-Za-z]+(?:'[a-z]+)?")
SCREEN_SUFFIXES = (".tsx", ".jsx")
UNOWNED_FOLDERS = (".hooks/", ".agents/", ".claude/")
USER_LITERAL = "UserContent holds literal text. Pass the text as an expression, for example {item.text}"
STORED_TEXT = (
    "Stored text `{field}` shows in full. Render it inside UserContent, or clamp it "
    "to 2 lines or fewer inside a control that opens the full text"
)
IMPORT_LINE = re.compile(r"\s*(?:import|export|part)\b")
DART_MARKS = ('"', "'", "Text", "TextSpan", "maxLines", "UserContent")
DART_MARKS += ("onTap", "onPressed", "onLongPress", "ExpansionTile")
ICU_CHOICE = re.compile(
    r"\s*[\w.]+\s*,\s*(plural|select|selectordinal)\s*,(?:\s*offset:\d+)?"
)
ICU_BRANCH = re.compile(r"\s*[^\s{}]+\s*\{")
ARB_KEY = re.compile(r'\s*"((?:[^"\\]|\\.)*)"\s*:')
FIX = "Split it into blocks of one idea each, with dates, names and amounts on their own labelled lines"


def is_prose(parts: list[object]) -> bool:
    """A copy constant is prose when it starts like a sentence and most of its words are plain words."""
    words = flatten(parts).split()
    if not words:
        return False
    plain = sum(bool(PLAIN_WORD.fullmatch(word.strip(".,;:!?\"'()"))) for word in words)
    starts = words[0][:1].isupper() or any(
        word.rstrip(CLOSERS).endswith(SENTENCE_ENDS) for word in words
    )
    return starts and plain * 10 >= len(words) * 7


def literal_text(parts: list[object]) -> bool:
    return any(
        bool(HAS_LETTER_OR_DIGIT.search(part))
        if isinstance(part, str)
        else isinstance(part, dict)
        and any(literal_text(b) for b in part.get("alt", []))
        for part in parts
    )


def stored_field(parts: list[object]) -> str:
    return next(
        (
            str(part["field"])
            for part in parts
            if isinstance(part, dict) and "field" in part
        ),
        "",
    )


def over_caps(parts: list[object], caps: Caps) -> str:
    words, sentences, longest = measure(parts)
    over = []
    if words > caps.words:
        over.append(f"{words} words, at most {caps.words}")
    if sentences > caps.sentences:
        over.append(f"{sentences} sentences, at most {caps.sentences}")
    if longest > caps.sentence_words:
        over.append(f"a sentence of {longest} words, at most {caps.sentence_words}")
    return "; ".join(over)


def problems(block: Block, caps: Caps) -> str:
    parts = block["parts"]
    if block["user"]:
        return USER_LITERAL if literal_text(parts) else ""
    found = over_caps(parts, caps)
    found += f". {FIX}" if found else ""
    field = stored_field(parts)
    clamp, tap = block["clamp"], block["tap"]
    if field and not (clamp is not None and clamp <= 2 and tap):
        found += (" " if found else "") + STORED_TEXT.format(field=field)
    return found


class Finding(NamedTuple):
    name: str
    line: int
    lines: tuple[int, ...]
    text: str
    reason: str

    def key(self) -> tuple[str, str]:
        return self.text, self.reason

    def describe(self) -> str:
        return f"{self.name}:{self.line}: {self.reason}"


def unreadable(name: str, error: str) -> str:
    return f"{name}: the text cannot be read, {error}. Fix the syntax of the file"


def judged(name: str, blocks: list[Block], caps: Caps) -> list[Finding]:
    """One finding for each block over a cap, with its flattened text and its reason."""
    out = []
    for block in blocks:
        if block["kind"] == "const" and not is_prose(block["parts"]):
            continue
        if found := problems(block, caps):
            text = " ".join(flatten(block["parts"]).split())
            out.append(Finding(name, block["line"], tuple(block["lines"]), text, found))
    return out


def in_scope(name: str, caps: Caps, flutter: set[str]) -> bool:
    return (
        (name.endswith(SCREEN_SUFFIXES) or name in flutter)
        and not name.startswith(UNOWNED_FOLDERS)
        and ".stories." not in name
        and not is_test_path(PurePosixPath(name))
        and (not caps.paths or any(fnmatchcase(name, glob) for glob in caps.paths))
    )


def base_sources(
    root: Path, point: str, names: list[str]
) -> list[tuple[str, str, None]]:
    """The text of each file at the base, from one git process."""
    wanted = [f"{point}:{name}\n" for name in names]
    data = subprocess.check_output(
        ["git", "cat-file", "--batch"],
        cwd=root,
        input="".join(wanted).encode(),
    )
    out: list[tuple[str, str, None]] = []
    for name in names:
        end = data.index(b"\n")
        header = data[:end].split()
        data = data[end + 1 :]
        if header[-1] == b"missing":
            continue
        size = int(header[2])
        out.append((name, data[:size].decode(errors="replace"), None))
        data = data[size + 1 :]
    return out


def read_all(
    files: Sequence[tuple[str, str, Sequence[int] | None]],
) -> list[FileBlocks]:
    """Each file goes to the reader of its language; a message catalog is read here."""
    kinds: dict[str, list[tuple[str, str, Sequence[int] | None]]] = {
        "js": [],
        "dart": [],
        "arb": [],
    }
    for item in files:
        kinds[
            "arb"
            if item[0].endswith(".arb")
            else "dart"
            if item[0].endswith(".dart")
            else "js"
        ].append(item)
    results = [arb_blocks(*item) for item in kinds["arb"]]
    for kind in ("js", "dart"):
        if kinds[kind]:
            results += read(kind, reader_query(kinds[kind], kind))
    return results


def old_names(root: Path, point: str) -> dict[str, str]:
    """The base name of each renamed file, from one git call made only when a finding exists."""
    listing = subprocess.check_output(
        ["git", "diff", "-M", "--name-status", "-z", point, "--"], cwd=root, text=True
    ).split("\0")
    names: dict[str, str] = {}
    index = 0
    while index < len(listing) - 1:
        if listing[index].startswith("R"):
            names[listing[index + 2]] = listing[index + 1]
            index += 3
        else:
            index += 2
    return names


def old_findings(
    root: Path, point: str, names: list[str], caps: Caps
) -> Counter[tuple[str, str]]:
    """How many times each finding stood in the changed files at the base."""
    moved = old_names(root, point)
    return Counter(
        finding.key()
        for result in read_all(
            base_sources(root, point, [moved.get(name, name) for name in names])
        )
        for finding in judged(result["path"], result["blocks"], caps)
    )


def untouched_findings(
    files: list[tuple[str, str, list[int]]], caps: Caps
) -> Counter[tuple[str, str]]:
    """How many times each finding stands in lines that the change did not touch."""
    touched = {name: set(lines) for name, _, lines in files}
    return Counter(
        finding.key()
        for result in read_all([(name, text, None) for name, text, _ in files])
        for finding in judged(result["path"], result["blocks"], caps)
        if not touched[finding.name] & set(finding.lines)
    )


def text_lines(
    added: dict[str, list[tuple[int, str]]],
    removed: dict[str, list[tuple[int, str]]],
    name: str,
) -> bool:
    """Whether a changed Dart line can hold screen text: a quote or a text widget, outside an import line."""
    return any(
        not IMPORT_LINE.match(text) and any(mark in text for mark in DART_MARKS)
        for _, text in (*added.get(name, []), *removed.get(name, []))
    )


def wall_check(
    root: Path,
    added: dict[str, list[tuple[int, str]]],
    removed: dict[str, list[tuple[int, str]]],
    joins: dict[str, list[int]],
    point: str,
) -> None:
    caps = settings(root)
    changed = [*added, *removed, *joins]
    flutter = set(screen_files(root, changed))
    names = sorted(name for name in set(changed) if in_scope(name, caps, flutter))
    files = [
        (
            name,
            (root / name).read_text(errors="replace"),
            sorted(
                {number for number, _ in added.get(name, [])} | set(joins.get(name, []))
            ),
        )
        for name in names
        if (root / name).is_file()
        and (name in added or name in joins)
        and (not name.endswith(".dart") or text_lines(added, removed, name))
    ]
    if not files:
        return
    found: list[Finding] = []
    lines: list[str] = []
    for result in read_all(files):
        if result["error"]:
            lines.append(unreadable(result["path"], result["error"]))
        else:
            found += judged(result["path"], result["blocks"], caps)
    if found:
        skipped = generated_sources(root, sorted({item.name for item in found}))
        found = [item for item in found if item.name not in skipped]
    if found:
        excused = old_findings(root, point, names, caps) - untouched_findings(
            files, caps
        )
        for item in found:
            if excused[item.key()] > 0:
                excused[item.key()] -= 1
            else:
                lines.append(item.describe())
    if lines:
        raise ValueError(
            f"HE-NO-TEXT-WALLS: Screen text comes in short blocks of at most {caps.words} "
            f"words and {caps.sentences} sentences, and a sentence of at most "
            f"{caps.sentence_words} words. " + "; ".join(lines)
        )


def listed_screens(root: Path, paths: list[str], caps: Caps) -> list[str]:
    if paths:
        flutter = set(screen_files(root, paths))
        return sorted(path for path in paths if in_scope(path, caps, flutter))
    listing = subprocess.check_output(
        [
            *GIT_LISTING,
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "*.tsx",
            "*.jsx",
            "*.dart",
            "*.arb",
        ],
        cwd=root,
        text=True,
    )
    listed = set(filter(None, listing.split("\0")))
    flutter = set(screen_files(root, sorted(listed)))
    return sorted(name for name in listed if in_scope(name, caps, flutter))


def stdin_walls(caps: Caps) -> list[str]:
    found = []
    for number, line in enumerate(sys.stdin, 1):
        if line.strip() and (over := over_caps([json.loads(line)], caps)):
            found.append(f"line {number}: {over}. {FIX}")
    return found


def listed_walls(root: Path, paths: list[str], caps: Caps) -> list[str]:
    names = [
        name for name in listed_screens(root, paths, caps) if (root / name).is_file()
    ]
    if not names:
        return []
    files = [(name, (root / name).read_text(errors="replace"), None) for name in names]
    results = read_all(files)
    hits = {
        result["path"]: judged(result["path"], result["blocks"], caps)
        for result in results
    }
    skipped = generated_sources(
        root, sorted(name for name, items in hits.items() if items)
    )
    return [
        unreadable(result["path"], result["error"])
        for result in results
        if result["error"]
    ] + [
        item.describe()
        for name, items in hits.items()
        if name not in skipped
        for item in items
    ]


def walls_command(root: Path, paths: list[str], stdin: bool) -> int:
    """Print each text block over the caps; with stdin, judge one JSON string for each line."""
    caps = settings(root)
    if not stdin:
        from basic_mode import screen_stacks
        from gate_config import repository_files

        for stack in screen_stacks(root, repository_files(root)):
            print(f"Gap: No text wall check for {stack}")
    found = stdin_walls(caps) if stdin else listed_walls(root, paths, caps)
    print("\n".join(found))
    return int(bool(found))


def matching(text: str, start: int) -> int:
    """The index of the brace that closes the brace at start, or -1."""
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def icu_branches(inner: str, hashes: bool) -> list[list[object]]:
    """The measured branches of a plural, select or selectordinal argument; none for a simple argument."""
    head = ICU_CHOICE.match(inner)
    if not head:
        return []
    body = inner[head.end() :]
    branches: list[list[object]] = []
    position = 0
    while found := ICU_BRANCH.match(body, position):
        close = matching(body, found.end() - 1)
        if close < 0:
            return []
        branches.append(
            icu_message(body[found.end() : close], hashes or head[1] != "select")
        )
        position = close + 1
    return branches


def icu_message(message: str, hashes: bool) -> list[object]:
    parts: list[object] = []
    index = start = 0
    while index < len(message):
        char = message[index]
        if char == "#" and hashes:
            parts += [message[start:index], {"x": 1}]
            start = index + 1
        elif char == "{":
            end = matching(message, index)
            parts.append(message[start:index])
            branches = icu_branches(message[index + 1 : end], hashes)
            if branches:
                rest = icu_message(message[end + 1 :], hashes)
                return [*parts, {"alt": [[*branch, *rest] for branch in branches]}]
            parts.append({"x": 1})
            index, start = end, end + 1
        index += 1
    parts.append(message[start:])
    return parts


def icu_parts(message: str) -> list[object]:
    """A message as parts: a simple argument is one slot, a plural or select argument is an alternative of its branches; unbalanced braces make plain text."""
    depth = 0
    for char in message:
        depth += (char == "{") - (char == "}")
        if depth < 0:
            return [message]
    return icu_message(message, False) if depth == 0 else [message]


def arb_blocks(name: str, text: str, touched: Sequence[int] | None) -> FileBlocks:
    """One block for each message of a template ARB file; keys that start with @ are skipped."""
    try:
        data = json.loads(text)
    except ValueError as error:
        line = getattr(error, "lineno", 1)
        return {"path": name, "error": f"line {line}: {error}", "blocks": []}
    lines = {}
    for number, row in enumerate(text.splitlines(), 1):
        if key := ARB_KEY.match(row):
            lines.setdefault(key[1], number)
    blocks: list[Block] = []
    for key, value in data.items() if isinstance(data, dict) else []:
        line = lines.get(key, 1)
        if key.startswith("@") or not isinstance(value, str):
            continue
        if touched is not None and line not in touched:
            continue
        blocks.append(
            {
                "line": line,
                "lines": [line],
                "kind": "key",
                "name": key,
                "parts": icu_parts(value),
                "clamp": None,
                "tap": False,
                "user": False,
            }
        )
    return {"path": name, "error": None, "blocks": blocks}
