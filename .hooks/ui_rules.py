"""HE-UI-SOURCE: added UI lines hold no every-property transition and no colour literal outside a theme file."""

import re
from pathlib import Path, PurePosixPath

from gate_config import generated_sources
from plans import _is_test as is_test_path

UNOWNED = (".hooks/", ".agents/", ".claude/")
THEME_WORDS = frozenset(
    ("theme", "token", "color", "colour", "palette")
    + ("themes", "tokens", "colors", "colours", "palettes")
)
NAME_WORDS = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z0-9]+")
COMMENT_LINE = re.compile(r"^\s*(?:\{\s*)?(?://|/\*|<!--|\*(?:\s|/|$))")
TRANSITION_CLASS = re.compile(r"(?<![\w-])transition-all(?![\w-])")
TRANSITION_STYLE = re.compile(
    r"(?<!\w)transition(?:-property|Property)?[\"']?\s*:\s*[\"'`]?(?:[^;\"'`,]*,\s*)?all(?![\w-])"
)
TAILWIND_COLOUR = re.compile(
    r"-\[(?:#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-fA-F\w])"
    r"|(?:rgba?|hsla?|oklch)\((?!\s*var\())"
)
DART_COLOUR = re.compile(
    r"\bColor\(\s*0x|\bColor\.from(?:ARGB|RGBO)?\(|\bColors\.(?!transparent\b)[A-Za-z]"
)
SWIFT_COLOUR = re.compile(
    r"\b(?:UI|NS)?Color\((?:\.(?:sRGB|sRGBLinear|displayP3)\s*,\s*)?red:|#colorLiteral\("
)
TRANSITION_STEP = (
    "List the properties that change, for example transition-[opacity,transform] "
    "or transition: opacity 150ms"
)
COLOUR_STEP = (
    "Use a colour of the theme, or add the colour to a theme or token file "
    "(a folder or file named theme, token, color, colour or palette, or tailwind.config.*)"
)


def is_theme_path(name: str) -> bool:
    path = PurePosixPath(name)
    parts = (NAME_WORDS.findall(part) for part in path.stem.split("+"))
    return (
        path.name.startswith("tailwind.config.")
        or any(part.lower() in THEME_WORDS for part in path.parts[:-1])
        or any(words and words[-1].lower() in THEME_WORDS for words in parts)
    )


def colour_pattern(name: str) -> re.Pattern[str]:
    if name.endswith(".dart"):
        return DART_COLOUR
    return SWIFT_COLOUR if name.endswith(".swift") else TAILWIND_COLOUR


def line_findings(name: str, lines: list[tuple[int, str]]) -> list[str]:
    """Findings for one file, from its path and lines alone: no process starts."""
    if name.startswith(UNOWNED) or is_test_path(PurePosixPath(name)):
        return []
    colours = None if is_theme_path(name) else colour_pattern(name)
    found: list[str] = []
    for number, text in lines:
        if COMMENT_LINE.match(text):
            continue
        if TRANSITION_CLASS.search(text) or TRANSITION_STYLE.search(text):
            found.append(
                f"{name}:{number}: a transition on every property. {TRANSITION_STEP}"
            )
        elif colours is not None and (hit := colours.search(text)):
            found.append(
                f"{name}:{number}: a colour typed in the file ({hit[0].strip()}). {COLOUR_STEP}"
            )
    return found


def ui_findings(root: Path, candidates: dict[str, list[tuple[int, str]]]) -> list[str]:
    """Findings for the marked lines of each UI file; only a file with a finding is looked up as generated."""
    found = {name: line_findings(name, lines) for name, lines in candidates.items()}
    named = sorted(name for name, items in found.items() if items)
    skipped = generated_sources(root, named) if named else set()
    return [item for name in named if name not in skipped for item in found[name]]
