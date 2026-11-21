"""Refuse Rust settings that allow lints: compiler flags and Clippy limits above their defaults (the numeric keys of Clippy 0.1.99 whose raise relaxes a lint, from its lint configuration book)."""

import re
import tomllib
from pathlib import Path, PurePosixPath

from command_words import assigns_variables

CLIPPY_FILES = {"clippy.toml", ".clippy.toml"}
CLIPPY_DEFAULTS = {
    "absolute-paths-max-segments": 2,
    "array-size-threshold": 16384,
    "cognitive-complexity-threshold": 25,
    "const-literal-digits-threshold": 30,
    "enum-variant-name-threshold": 3,
    "enum-variant-size-threshold": 200,
    "future-size-threshold": 16384,
    "large-error-threshold": 128,
    "literal-representation-threshold": 16384,
    "max-fn-params-bools": 3,
    "max-include-file-size": 1000000,
    "max-struct-bools": 3,
    "max-suggested-slice-pattern-length": 3,
    "max-trait-bounds": 3,
    "pass-by-value-size-limit": 256,
    "single-char-binding-names-threshold": 4,
    "stack-size-threshold": 512000,
    "struct-field-name-threshold": 3,
    "too-large-for-stack": 200,
    "too-many-arguments-threshold": 7,
    "too-many-lines-threshold": 100,
    "type-complexity-threshold": 250,
    "unnecessary-box-size": 128,
    "vec-box-size-threshold": 4096,
    "verbose-bit-mask-threshold": 1,
}
FLAG_SPLIT = re.compile(r"[\s,=:'\"\[\]]+")
ASSIGNMENT = re.compile(r"rustflags[\"']?\s*[:=]", re.IGNORECASE)


def allows(flags: str) -> str | None:
    """The flag that allows lints or caps them below a warning, or None."""
    tokens = [token for token in FLAG_SPLIT.split(flags) if token]
    for index, token in enumerate(tokens):
        if token.startswith(("-A", "--allow")):
            return token
        value = "".join(tokens[index + 1 : index + 2])
        if token == "--cap-lints" and value in {"allow", "warn"}:
            return f"--cap-lints {value}"
    return None


def flag_hits(name: str, text: str) -> list[str]:
    """Each line that assigns RUSTFLAGS or rustflags a flag that allows lints."""
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        match = ASSIGNMENT.search(line)
        flag = allows(line[match.end() :]) if match else None
        if flag and not line.lstrip().startswith("#"):
            found.append(
                f"{name}:{number} sets rustflags to {flag}, which allows lints"
            )
    return found


def alias_hits(name: str, lines: list[str], config: dict[str, object]) -> list[str]:
    """An alias named like the judged subcommand runs another command in place of `cargo clippy`."""
    aliases = config.get("alias")
    if not (isinstance(aliases, dict) and "clippy" in aliases):
        return []
    number = next((n for n, line in enumerate(lines, 1) if "clippy" in line), 1)
    return [
        f"{name}:{number} defines the alias `clippy`, which runs in place of `cargo clippy`; rename or remove the alias"
    ]


def cargo_config_hits(name: str, text: str) -> list[str]:
    """Rust flags of a Cargo config, also when the list runs over several lines."""
    found = flag_hits(name, text)
    if found:
        return found
    try:
        config = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    lines = text.splitlines()

    def walk(table: object) -> list[str]:
        hits: list[str] = []
        if isinstance(table, dict):
            for key, value in table.items():
                joined = " ".join(value) if isinstance(value, list) else str(value)
                if key.lower() == "rustflags" and (flag := allows(joined)):
                    number = next(
                        (n for n, line in enumerate(lines, 1) if key in line), 1
                    )
                    hits.append(
                        f"{name}:{number} sets rustflags to {flag}, which allows lints"
                    )
                hits += walk(value)
        return hits

    return [*walk(config), *alias_hits(name, lines, config)]


def clippy_hits(name: str, text: str) -> list[str]:
    try:
        config = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    lines = text.splitlines()
    found = []
    for key, default in CLIPPY_DEFAULTS.items():
        value = config.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if value > default:
            number = next((n for n, line in enumerate(lines, 1) if key in line), 1)
            found.append(
                f"{name}:{number} sets {key} to {value}, above Clippy's default {default}"
            )
    return found


LINT_LEVEL_FLAGS = {"-D", "--deny", "-W", "--warn", "-F", "--forbid"}


def unlisted_lint_flags(rest: list[str]) -> list[str]:
    """Words after `--` of a clippy command that are not a deny, warn or forbid level with its lint."""
    found = []
    skip = False
    for word in rest:
        if skip:
            skip = False
            continue
        flag = word.split("=", 1)[0]
        if flag in LINT_LEVEL_FLAGS:
            skip = "=" not in word
        elif not (len(word) > 2 and word[:2] in LINT_LEVEL_FLAGS):
            found.append(word)
    return found


def command_hits(parts: list[list[str]]) -> list[str]:
    """Words of a cargo command that allow lints: a flag after `--`, a Rust flags config value or a variable."""
    found: list[str] = []
    for segment in parts:
        names = [Path(word).name for word in segment]
        if "cargo" in names:
            rest = segment[segment.index("--") + 1 :] if "--" in segment else []
            if "clippy" in segment:
                found += unlisted_lint_flags(rest)
            elif flag := allows(" ".join(rest)):
                found.append(flag)
        found += [
            word
            for word in segment
            if (match := ASSIGNMENT.search(word)) and allows(word[match.end() :])
        ]
    return found


def validate_rust_command(parts: list[list[str]]) -> None:
    if found := command_hits(parts):
        raise ValueError(
            "HE-NO-SWITCH-OFF: A Rust gate must not allow lints: fix each finding at its cause "
            f"instead; the gate holds {', '.join(found)}"
        )


def rust_file_hits(name: str, text: str) -> list[str]:
    """The Rust switch-offs of one file: flags it assigns, a Cargo config and Clippy limits."""
    if name.endswith((".cargo/config", ".cargo/config.toml")):
        return cargo_config_hits(name, text)
    if PurePosixPath(name).name == "config.toml":
        try:
            config = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return []
        return alias_hits(name, text.splitlines(), config)
    found = flag_hits(name, text) if assigns_variables(name) else []
    if PurePosixPath(name).name in CLIPPY_FILES:
        found += clippy_hits(name, text)
    return found
