"""Every setting `ruff check --show-settings` prints has a class; a setting without one is refused."""

import re

KEY = re.compile(r"^([a-z_][\w.]*) = (.*)$")
CODE = re.compile(r"\((\w+)\)")
COMPLEXITY_CODES = {"C901", "PLR0912", "PLR0915"}

RUFF_KEYS = {
    "cache_dir": "free",
    "fix": "equal",
    "fix_only": "equal",
    "output_format": "free",
    "output_prefer_rule_codes": "free",
    "show_fixes": "free",
    "unsafe_fixes": "free",
    "linter.project_root": "free",
    "linter.rules.enabled": "rules",
    "linter.rules.should_fix": "free",
    "linter.per_file_ignores": "equal",
    "linter.exclude": "equal",
    "linter.unresolved_target_version": "version",
    "linter.per_file_target_version": "version",
    "linter.preview": "free",
    "linter.explicit_preview_rules": "free",
    "linter.extension": "equal",
    "linter.src": "free",
    "linter.tab_size": "equal",
    "linter.line_length": "free",
    "linter.task_tags": "equal",
    "linter.allowed_confusables": "equal",
    "linter.builtins": "equal",
    "linter.dummy_variable_rgx": "equal",
    "linter.external": "equal",
    "linter.ignore_init_module_imports": "equal",
    "linter.logger_objects": "equal",
    "linter.namespace_packages": "equal",
    "linter.typing_modules": "equal",
    "linter.typing_extensions": "equal",
    "linter.flake8_tidy_imports.banned_api": "holds",
    "linter.mccabe.max_complexity": "limit",
    "linter.pycodestyle.max_line_length": "free",
    "linter.pycodestyle.max_doc_length": "free",
    "linter.pylint.max_args": "limit",
    "linter.pylint.max_positional_args": "limit",
    "linter.pylint.max_returns": "limit",
    "linter.pylint.max_bool_expr": "limit",
    "linter.pylint.max_branches": "limit",
    "linter.pylint.max_statements": "limit",
    "linter.pylint.max_statements_in_try": "limit",
    "linter.pylint.max_public_methods": "limit",
    "linter.pylint.max_locals": "limit",
    "linter.pylint.max_nested_blocks": "limit",
}
RUFF_PREFIXES = {
    "file_resolver.": "free",
    "formatter.": "free",
    "analyze.": "free",
    "linter.safety_table.": "free",
    "linter.isort.": "free",
    "linter.flake8_quotes.": "free",
    "linter.flake8_pytest_style.": "free",
    "linter.flake8_tidy_imports.": "free",
    "linter.flake8_import_conventions.": "free",
    "linter.flake8_annotations.": "equal",
    "linter.flake8_copyright.": "equal",
    "linter.flake8_bandit.": "equal",
    "linter.flake8_bugbear.": "equal",
    "linter.flake8_builtins.": "equal",
    "linter.flake8_comprehensions.": "equal",
    "linter.flake8_errmsg.": "equal",
    "linter.flake8_gettext.": "equal",
    "linter.flake8_implicit_str_concat.": "equal",
    "linter.flake8_self.": "equal",
    "linter.flake8_type_checking.": "equal",
    "linter.flake8_unused_arguments.": "equal",
    "linter.pep8_naming.": "equal",
    "linter.pycodestyle.": "equal",
    "linter.pyflakes.": "equal",
    "linter.pylint.": "equal",
    "linter.pyupgrade.": "equal",
    "linter.ruff.": "equal",
}


def classify(key: str) -> str | None:
    """The class of a printed key: its own entry, else the entry of its longest section prefix."""
    if key in RUFF_KEYS:
        return RUFF_KEYS[key]
    found = [prefix for prefix in RUFF_PREFIXES if key.startswith(prefix)]
    return RUFF_PREFIXES[max(found, key=len)] if found else None


def parse(text: str) -> dict[str, list[str]]:
    """Each printed setting with its value lines; a block is read to its closing line, nested blocks included."""
    found: dict[str, list[str]] = {}
    key = ""
    depth = 0
    for line in text.splitlines():
        stripped = line.strip()
        if depth == 0:
            match = KEY.match(line)
            if not match:
                continue
            key, rest = match[1], match[2]
            if rest in ("[]", "{}"):
                found[key] = []
            elif rest in ("[", "{"):
                found[key] = []
                depth = 1
            else:
                found[key] = [rest]
        elif stripped in ("]", "}"):
            depth -= 1
        else:
            if stripped.endswith(("[", "{")):
                depth += 1
            found[key].append(stripped.rstrip(","))
    return found


def enabled(entries: list[str]) -> set[str]:
    return {found[1] for line in entries if (found := CODE.search(line))}


def lacking(lost: set[str], what: str) -> str:
    names = sorted(lost)
    more = f" and {len(names) - 3} more" if len(names) > 3 else ""
    return (
        f"the resolved rule set lacks {len(names)} {what}: {', '.join(names[:3])}{more}"
    )


def number_of(entries: list[str]) -> float | None:
    try:
        return float(entries[0])
    except (IndexError, ValueError):
        return None


VERSION = re.compile(r"(\d+)\.(\d+)")


def entry_names(lines: list[str]) -> set[str]:
    """The key of each printed entry; the message after it changes no finding."""
    return {line.split(" = ")[0] for line in lines}


def version_hits(key: str, value: list[str], minimum: tuple[int, int]) -> list[str]:
    """A target version other than the requires-python minimum hides findings: a lower one hides pyupgrade rules, a higher one lets Ruff accept syntax that the minimum does not allow."""
    per_file = "per_file" in key
    lines = (
        [line for line in value if line.startswith("data = ")] if per_file else value
    )
    what = "per-file target version" if per_file else "target version"
    least = f"{minimum[0]}.{minimum[1]}"
    for found in (match for line in lines for match in VERSION.findall(line)):
        now = (int(found[0]), int(found[1]))
        if now != minimum:
            way, harm = (
                ("below", "a lower target hides pyupgrade findings")
                if now < minimum
                else ("above", "a higher target hides the syntax errors of the minimum")
            )
            return [
                f"the resolved {what} {found[0]}.{found[1]} is {way} the requires-python minimum {least}: {harm}; set it to {least} or remove the entry"
            ]
    return []


def judge(
    key: str,
    value: list[str],
    default: list[str],
    context: tuple[object, tuple[int, int] | None],
) -> list[str]:
    """What one printed setting does wrong, by its class."""
    role, minimum = context
    kind = classify(key)
    if kind is None:
        if value == default:
            return []
        return [
            f"{key} is set to {value[:1]}, not its default {default[:1]}, and no table classes it: remove it from the project's Ruff config or set it back to its default"
        ]
    if kind == "equal" and value != default:
        return [f"the resolved {key} differs from Ruff's default {default or '[]'}"]
    if kind == "limit":
        now, base = number_of(value), number_of(default)
        if now is None or base is None or now > base:
            return [f"the resolved {key} is {value[:1]}, above the limit {default[:1]}"]
    if kind == "rules":
        return rule_hits(enabled(value), enabled(default), role)
    if kind == "holds" and (
        missing := [
            line for line in default if line.split(" = ")[0] not in entry_names(value)
        ]
    ):
        return [
            f"the resolved {key} lacks {missing[0]!r}: the annotations gate keeps every banned import of the template; set one `--config` banned-api table that lists {', '.join(line.split(' = ')[0] for line in default)} (separate `--config` lines for each entry keep only one)"
        ]
    if kind == "version" and minimum:
        return version_hits(key, value, minimum)
    return []


def rule_hits(codes: set[str], defaults: set[str], role: object) -> list[str]:
    hits = []
    if role == "lint" and (lost := defaults - codes):
        hits.append(lacking(lost, "of Ruff's default rules"))
    if role == "complexity" and (lost := COMPLEXITY_CODES - codes):
        hits.append(lacking(lost, "of the complexity rules"))
    if role == "annotations" and (lost := defaults - codes):
        hits.append(lacking(lost, "of the annotation rules"))
    return hits


def ruff_hits(
    settings: str, defaults: str, role: object, minimum: tuple[int, int] | None = None
) -> list[str]:
    """What the resolved settings of one gate drop, key by key, compared with Ruff's own defaults."""
    printed, base = parse(settings), parse(defaults)
    context = (role, minimum)
    return [
        hit
        for key, value in printed.items()
        for hit in judge(key, value, base.get(key, []), context)
    ]
