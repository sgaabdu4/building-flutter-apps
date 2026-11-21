"""Refuse a merge that skips ship: a `gh` command that merges, or that the guard cannot read, passes only as one plain `gh pr merge` with a passed ship record."""

import json
import re
import shlex
from itertools import chain, pairwise

METHOD_FLAGS = {
    "--rebase": "rebase",
    "-r": "rebase",
    "--squash": "squash",
    "-s": "squash",
    "--merge": "merge",
    "-m": "merge",
}
VALUE_FLAGS = frozenset(
    ("--match-head-commit", "-R", "--repo", "-b", "--body", "-F", "--body-file")
    + ("-t", "--subject", "-A", "--author-email")
)
SHELL_MARKS = re.compile(r"[;&|<>`$(){}\n]")
PULL_NUMBER = re.compile(r"(?:^|/pull/)(\d+)/?$")
REFUSED_FLAGS = frozenset(("--admin", "--auto", "--disable-auto"))
REBASE_STEP = (
    "A typed rebase merge cannot see that the base moved since `ship ready`, so two "
    "ready PRs can turn the base red. Run `python3 .hooks/hard-eng.py ship --stage "
    "merge --merge-method rebase --pr <PR URL> --plan <plan>`, which checks base "
    "currency right before it merges."
)
STEP = "Merge with `python3 .hooks/hard-eng.py ship --pr <PR URL> --stage merge`."


def record_for(cwd: str, number: int) -> dict[str, object] | None:
    import subprocess
    from pathlib import Path

    done = subprocess.run(
        ["git", "rev-parse", "--git-path", "hard-eng/ship"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode:
        return None
    try:
        record = json.loads(
            (Path(cwd) / done.stdout.strip() / f"{number}.json").read_text()
        )
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def pr_flags(arguments: list[str]) -> tuple[str | None, set[str], str | None]:
    selector, methods, head = None, set[str](), None
    index = 0
    while index < len(arguments):
        word = arguments[index]
        if word == "--match-head-commit" and index + 1 < len(arguments):
            head = arguments[index + 1]
            index += 1
        elif word.startswith("--match-head-commit="):
            head = word.partition("=")[2]
        elif word in VALUE_FLAGS:
            index += 1
        elif word in METHOD_FLAGS:
            methods.add(METHOD_FLAGS[word])
        elif not word.startswith("-") and selector is None:
            selector = word
        index += 1
    return selector, methods, head


def pr_merge_problem(arguments: list[str], cwd: str) -> str | None:
    selector, methods, head = pr_flags(arguments)
    if "rebase" in methods:
        return REBASE_STEP
    found = PULL_NUMBER.search(selector or "")
    if found is None:
        return f"gh pr merge must name the pull request by number or URL. {STEP}"
    record = record_for(cwd, int(found[1]))
    if record is None or record.get("result") != "passed":
        return f"no passed `ship` record for PR {found[1]}. {STEP}"
    if head != record.get("head"):
        return f"gh pr merge needs `--match-head-commit {record.get('head')}`, the head that `ship` passed. {STEP}"
    if methods != {record.get("method")}:
        return f"the passed `ship` record names the method {record.get('method')}; use only that flag. {STEP}"
    return None


MARKS = re.compile(r"[;&|()\n]+")
WORD = re.compile(r"[a-z0-9_]+")
UNSAFE = re.compile(r"[{}$`]")
ASSIGNMENT = re.compile(r"[a-z_][a-z0-9_]*=")
SHELL_MARKS = re.compile(r"[;&|<>`$(){}\n]")
API_WORDS = frozenset(
    ("merge", "merges", "mergebranch", "enqueuepullrequest", "mergepullrequest")
    + ("enablepullrequestautomerge",)
)
SHELLS = frozenset(("bash", "sh", "zsh", "dash", "ksh", "eval", "source", "."))
INTERPRETERS = frozenset(("python", "python3", "node", "ruby", "perl", "php", "deno"))
WRAPPERS = frozenset(
    ("env", "command", "exec", "nice", "nohup", "time", "timeout", "sudo", "xargs")
    + ("caffeinate", "stdbuf", "builtin", "setsid", "ionice")
)
KEYWORDS = frozenset(("{", "}", "!", "if", "then", "do", "else", "elif", "while"))
VALUE_FLAGS_GH = frozenset(
    ("-r", "--repo", "-b", "--body", "--body-file", "-t", "--title", "-f", "--field")
    + ("--raw-field", "-x", "--method", "-h", "--header", "-q", "--jq", "--json")
    + ("--branch", "--base", "--head", "--label", "--search", "--state", "--limit")
)
LOOKUP = re.compile(
    r"\"?(?:\$\(|`)\s*(?:which|command\s+-v|type\s+-p|whence\s+-p)\s+gh\s*(?:\)|`)\"?",
    re.IGNORECASE,
)
GIT_ALIAS = re.compile(r"^(?:alias\.[^=]+=)?!")
PLACEHOLDER = re.compile(r"\{(?:owner|repo|branch)\}")
FIELD_FLAGS = ("-f", "--field", "--raw-field")
PLAIN_REASON = (
    "a `gh` command that merges, or that cannot be read, must be exactly one "
    "plain `gh pr merge`."
)


def literal_dollars(command: str) -> str:
    out, quote, escaped = list[str](), "", False
    for char in command:
        if escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif char in "'\"" and quote in ("", char):
            quote = "" if quote else char
        out.append("" if char == "$" and quote == "'" else char)
    return "".join(out)


def command_segments(command: str) -> list[list[str]]:
    text = LOOKUP.sub("gh", literal_dollars(command.replace("\\\n", "")))
    text = text.replace("`", "$ ; ").replace("$(", "$ ; ( ").replace("<(", "$ ; ( ")
    lexer = shlex.shlex(text.lower(), posix=True, punctuation_chars=";&|()\n")
    vars(lexer).update(whitespace=" \t\r", whitespace_split=True)
    segments, current = list[list[str]](), list[str]()
    for token in lexer:
        if MARKS.fullmatch(token):
            if current:
                segments.append(current)
            current = list[str]()
        else:
            current.append(token)
    return segments + ([current] if current else [])


def words_of(tokens: list[str]) -> set[str]:
    return set(WORD.findall(" ".join(tokens)))


def holds_code(tokens: list[str]) -> bool:
    words = words_of(tokens)
    return "gh" in words and bool(words & API_WORDS)


def reads_only(arguments: list[str], positionals: list[str]) -> bool:
    """A `gh api` call with no method flag, no field and no `--input` only reads."""
    return positionals[:1] == ["api"] and not any(
        word in ("-x", "--method", "--input", *FIELD_FLAGS)
        or word.startswith(("--method=", "-x", "--field=", "--raw-field=", "--input="))
        for word in arguments
    )


def field_values(arguments: list[str]) -> list[str]:
    values = [value for flag, value in pairwise(arguments) if flag in FIELD_FLAGS]
    for word in arguments:
        if word.startswith(("--field=", "--raw-field=")):
            values.append(word.partition("=")[2])
        elif word.startswith("-f") and not word.startswith("--") and len(word) > 2:
            values.append(word[2:])
    return values


def gh_problem(arguments: list[str], later: list[str]) -> str | None:
    positionals, index = list[str](), 0
    while index < len(arguments):
        word = arguments[index]
        if not word.startswith("-"):
            positionals.append(word)
        elif word in VALUE_FLAGS_GH:
            index += 1
        index += 1
    read = reads_only(arguments + later, positionals)
    checked = positionals[:1] if read else positionals[:2]
    if any(UNSAFE.search(PLACEHOLDER.sub("", word)) for word in checked):
        return "a `gh` command word that a shell expands cannot be read."
    if positionals[:1] == ["pr"] and "merge" in positionals[1:]:
        return PLAIN_REASON
    if positionals[:1] == ["api"]:
        opaque = any(
            word == "--input" or word.startswith("--input=") or "=@" in word
            for word in arguments
        )
        opaque = (
            opaque
            or positionals[1:2] == ["graphql"]
            and any("$" in value for value in field_values(arguments))
        )
        if opaque or words_of(arguments) & API_WORDS:
            return "a `gh api` call that merges, or that reads its query from a file, must go through ship."
    if positionals[:1] == ["alias"] and positionals[1:2] not in (["list"], ["delete"]):
        return "a `gh alias` change can hide a merge."
    return None


def effective_command(segment: list[str]) -> tuple[str, list[str]]:
    rest = list(segment)
    while rest and (rest[0] in KEYWORDS or ASSIGNMENT.match(rest[0])):
        rest.pop(0)
    if not rest:
        return "", []
    name = rest[0].rsplit("/", 1)[-1]
    for index, word in enumerate(rest[1:] if name != "gh" else [], 1):
        base = word.rsplit("/", 1)[-1]
        if base == "gh" or (
            name in WRAPPERS
            and (base in SHELLS or base.rstrip("0123456789.") in INTERPRETERS)
        ):
            return base, rest[index:]
    return name, rest


def segment_problem(segment: list[str], later: list[str]) -> tuple[str | None, bool]:
    name, rest = effective_command(segment)
    if name == "gh":
        return gh_problem(
            rest[1:], later if rest[-1:] and rest[-1].endswith("$") else []
        ), False
    if name.startswith("$") and holds_code(["gh", *rest]):
        return PLAIN_REASON, False
    if name == "alias" and "gh" in words_of(rest[1:]):
        return PLAIN_REASON, False
    if name == "git" and any(GIT_ALIAS.match(w) and holds_code([w]) for w in rest):
        return PLAIN_REASON, False
    code = [word for word in rest[1:] if not word.startswith("-")]
    if name in SHELLS or name.rstrip("0123456789.") in INTERPRETERS:
        return (PLAIN_REASON if holds_code(code) else None), name in SHELLS and not code
    return None, False


def merge_problem(command: str, cwd: str) -> str | None:
    """The reason a command with a `gh` word is refused, or None when it is not a merge and holds nothing the guard cannot read, or is one plain `gh pr merge` with a passed record."""
    try:
        segments = command_segments(command)
    except ValueError:
        return f"{PLAIN_REASON} {STEP}"
    plain = len(segments) == 1 and segments[0][:3] == ["gh", "pr", "merge"]
    if plain and not SHELL_MARKS.search(command):
        if REFUSED_FLAGS & set(segments[0]):
            return f"`gh pr merge` with --admin or --auto skips ship. {STEP}"
        return pr_merge_problem(segments[0][3:], cwd)
    reads_stdin = False
    for index, segment in enumerate(segments):
        problem, stdin = segment_problem(
            segment, list(chain.from_iterable(segments[index + 1 :]))
        )
        if problem:
            return f"{problem} {STEP}"
        reads_stdin = reads_stdin or stdin
    if reads_stdin and any(holds_code(segment) for segment in segments):
        return f"{PLAIN_REASON} {STEP}"
    return None
