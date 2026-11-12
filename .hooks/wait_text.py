"""Foreground waits in a shell command (HE-NO-FOREGROUND-POLL); loaded only when one is named."""

import re

INTERPRETER_WORD = (
    r"(?:^|[\s;&|(/])(?:(?:ba|z|s)?sh|python[\d.]*|perl|ruby|node)(?=\s|$)"
)
QUOTE_TEXT = r"""(?:"(?:[^"\\]|\\.)*"|'[^']*')"""
LOOP = re.compile(
    r"(?:^|[;&|({`]|\b(?:do|then|else)\s)\s*(?:while|until)\b", re.MULTILINE
)
SHELL_SLEEP = re.compile(r"\bsleep\s+(\d+(?:\.\d+)?)([smhd]?)\b")
HIDDEN_SLEEP = re.compile(
    r"\btime\.sleep\(\s*(\d+(?:\.\d+)?)|\bselect\(\s*undef\s*,\s*undef\s*,\s*undef\s*,\s*(\d+(?:\.\d+)?)"
)
INTERPRETER = re.compile(INTERPRETER_WORD)
QUOTE = re.compile(QUOTE_TEXT)
HEREDOC = re.compile(
    r"^([^\n]*?)<<-?\s*(['\"]?)(\w+)\2([^\n]*)\n(.*?)^\s*\3$", re.MULTILINE | re.DOTALL
)
COMMENT_OR_QUOTE = re.compile(
    r"(?:^|(?<=\s))#[^\n]*"
    rf"|((?:{INTERPRETER_WORD}[^;&|\n'\"]*?\s-\w*[ce]"
    r"|(?:^|[\s;&|(])(?:ssh|eval)\b[^;&|\n'\"]*?)\s+)?"
    rf"({QUOTE_TEXT})",
    re.MULTILINE,
)
UNIT = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


def shell_text(found: re.Match[str]) -> str:
    quote = found[2]
    if quote is None:
        return ""
    runs = found[1] or (quote[0] == '"' and ("$(" in quote or "`" in quote))
    return f"\n{quote[1:-1]}\n" if runs else " "


def run_text(command: str) -> str:
    """The text a shell or interpreter runs: no comments, quoted data or unrun heredoc bodies."""
    bodies: list[str] = []

    def heredoc(doc: re.Match[str]) -> str:
        head = doc[1] + doc[4]
        if INTERPRETER.search(QUOTE.sub("", head)):
            bodies.append(doc[5])
        return head

    text = COMMENT_OR_QUOTE.sub(shell_text, HEREDOC.sub(heredoc, command))
    return "\n".join([text, *bodies])


def polls(command: str) -> bool:
    text = run_text(command)
    waits = [float(value) * UNIT[unit] for value, unit in SHELL_SLEEP.findall(text)]
    waits += [float(a or b) for a, b in HIDDEN_SLEEP.findall(text)]
    looped = max(waits, default=0) >= 1 and LOOP.search(text)
    return bool(looped) or sum(waits) >= 30
