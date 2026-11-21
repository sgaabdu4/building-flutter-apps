"""The one owner of which files `linguist-generated` or `linguist-vendored` marks hide: an exact path with a folder, a fixed generator suffix, or a folder that is a byte copy of a judged package; never a catch-all."""

import re
import subprocess
import sys
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from project_files import GIT_LISTING

GENERATED_KEYS = {"linguist-generated", "linguist-vendored"}
PROOFS: dict[tuple[Path, str], str | None] = {}
SOURCES: dict[tuple[Path, str], str] = {}
ON_DISK: dict[tuple[Path, str], bool] = {}
INDEXES: dict[Path, dict[str, str]] = {}
PUBSPECS: dict[Path, dict[str, bytes]] = {}
MARKED_PACKAGES: dict[Path, dict[str, bool]] = {}
MARKS: dict[tuple[Path, int, int, frozenset[str]], list[str]] = {}
TOPS: dict[Path, Path] = {}
CLAIMED: dict[Path, tuple[list[str], set[str]]] = {}
LISTED: dict[Path, tuple[frozenset[str], set[str]]] = {}
LISTINGS: dict[Path, str] = {}
ASKED: dict[Path, tuple[set[str], set[str]]] = {}
GENERATOR_SUFFIXES = (".g.dart", ".gr.dart", ".freezed.dart")


def has_glob(text: str) -> bool:
    return any(char in text for char in "*?[")


def generator_name(name: str) -> bool:
    return all(char.isalnum() or char in "_*-" for char in name)


def mark_kind(pattern: str) -> str | None:
    plain = pattern.strip("/")
    if not has_glob(plain):
        return "exact" if "/" in plain or pattern.startswith("/") else None
    last = plain.split("/")[-1]
    if any(
        last.endswith(suffix) and generator_name(last.removesuffix(suffix))
        for suffix in GENERATOR_SUFFIXES
    ):
        return "suffix"
    return "folder" if last == "**" and plain != "**" else None


def regex(pattern: str) -> re.Pattern[str]:
    anchored = pattern.startswith("/") or "/" in pattern.strip("/")
    text = ""
    parts = pattern.strip("/").split("/")
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        if part == "**":
            text += ".*" if last else "(?:.*/)?"
            continue
        text += re.escape(part).replace(r"\*", "[^/]*").replace(r"\?", "[^/]") + (
            "" if last else "/"
        )
    return re.compile(text if anchored else f"(?:.*/)?{text}")


def marks(attribute_file: Path, keys: set[str]) -> list[str]:
    try:
        seen = attribute_file.stat()
    except OSError:
        return []
    token = (attribute_file, seen.st_mtime_ns, seen.st_size, frozenset(keys))
    if token not in MARKS:
        MARKS[token] = read_marks(attribute_file, keys)
    return MARKS[token]


def read_marks(attribute_file: Path, keys: set[str]) -> list[str]:
    import shlex

    found = []
    for line in attribute_file.read_text(errors="replace").splitlines():
        try:
            words = shlex.split(line, comments=True)
        except ValueError:
            words = line.split()
        if len(words) < 2:
            continue
        if any(
            word.split("=")[0] in keys and word.split("=")[-1] != "false"
            for word in words[1:]
        ):
            found.append(words[0])
    return found


def repository_top(root: Path) -> Path:
    if root not in TOPS:
        folder = root.resolve()
        TOPS[root] = next(
            (
                parent
                for parent in (folder, *folder.parents)
                if (parent / ".git").exists()
            ),
            folder,
        )
    return TOPS[root]


def package_name(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("name:"):
            return line.partition(":")[2].strip() or None
    return None


def reset() -> None:
    PROOFS.clear()
    SOURCES.clear()
    INDEXES.clear()
    PUBSPECS.clear()
    MARKED_PACKAGES.clear()
    MARKS.clear()
    TOPS.clear()
    CLAIMED.clear()
    LISTINGS.clear()
    ASKED.clear()


def listed_with_blobs(root: Path) -> list[str]:
    """The tracked and unignored untracked paths, in one `ls-files -s` call whose blob ids the derived-copy proof reuses, so the proof asks Git for no second listing."""
    listed = subprocess.check_output(
        [
            *GIT_LISTING,
            "ls-files",
            "-s",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        cwd=root,
        text=True,
    )
    top = repository_top(root)
    if root.resolve() == top:
        LISTINGS[top] = listed
        INDEXES.pop(top, None)
    return sorted(
        {entry.partition("\t")[2] or entry for entry in listed.split("\0")} - {""}
    )


def tracked_index(top: Path) -> dict[str, str]:
    """Every tracked path with its blob id, read once from the index so that a file deleted from disk and not staged changes nothing."""
    if top not in INDEXES:
        listed = LISTINGS.get(top)
        if listed is None:
            listed = subprocess.run(
                [*GIT_LISTING, "ls-files", "-s", "-z"],
                cwd=top,
                capture_output=True,
                check=False,
            ).stdout.decode(errors="replace")
        INDEXES[top] = {
            path: meta.split()[1]
            for meta, _, path in (entry.partition("\t") for entry in listed.split("\0"))
            if path
        }
    return INDEXES[top]


def ancestors(name: str) -> list[str]:
    """The folders above a tracked path, nearest first, ending in `.`."""
    found = []
    while "/" in name:
        name = name.rpartition("/")[0]
        found.append(name)
    return [*found, "."]


def folder_prefix(folder: str) -> str:
    return "" if folder in {"", "."} else folder.rstrip("/") + "/"


def tracked_under(top: Path, folder: str) -> list[str]:
    prefix = folder_prefix(folder)
    return [name for name in tracked_index(top) if name.startswith(prefix)]


def pubspec_texts(top: Path) -> dict[str, bytes]:
    """The committed text of every tracked pubspec.yaml, from one `git cat-file --batch`."""
    if top not in PUBSPECS:
        index = tracked_index(top)
        names = [
            name
            for name in index
            if name == "pubspec.yaml" or name.endswith("/pubspec.yaml")
        ]
        wanted = "".join(f"{index[name]}\n" for name in names).encode()
        batch = subprocess.run(
            [*GIT_LISTING, "cat-file", "--batch"],
            cwd=top,
            input=wanted,
            capture_output=True,
            check=False,
        ).stdout
        texts: dict[str, bytes] = {}
        at = 0
        for name in names:
            end = batch.index(b"\n", at)
            size = int(batch[at:end].split()[2])
            texts[name] = batch[end + 1 : end + 1 + size]
            at = end + size + 2
        PUBSPECS[top] = texts
    return PUBSPECS[top]


def marked_packages(top: Path, packages: set[str]) -> set[str]:
    """Which of the package folders hold a file that a mark exempts: one `git check-attr` for every folder not asked about yet."""
    known = MARKED_PACKAGES.setdefault(top, {})
    fresh = sorted(packages - known.keys())
    if fresh:
        wanted = set(fresh)
        files = [
            name for name in tracked_index(top) if wanted.intersection(ancestors(name))
        ]
        asked, marked = ASKED.get(top, (set(), set()))
        fresh_files = [name for name in files if name not in asked]
        held = {
            parent
            for name in [
                *(name for name in files if name in marked),
                *(
                    marked_by_git(top, fresh_files, GENERATED_KEYS)
                    if fresh_files
                    else ()
                ),
            ]
            for parent in ancestors(name)
        }
        known.update({package: package in held for package in fresh})
    return {package for package in packages if known[package]}


def claims(top: Path) -> tuple[list[str], set[str]]:
    """The folders that marks of the root `.gitattributes` claim, and the package folders outside them that share a pubspec name with one: the only sources a proof can ask about."""
    if top not in CLAIMED:
        texts = pubspec_texts(top)
        folders = [
            folder
            for pattern in marks(top / ".gitattributes", GENERATED_KEYS)
            if mark_kind(pattern) == "folder"
            for folder in marked_folders(top, pattern)
        ]
        names = {
            package_name(data.decode(errors="replace"))
            for path, data in texts.items()
            if inside(path, folders)
        }
        sources = {
            PurePosixPath(path).parent.as_posix()
            for path, data in texts.items()
            if package_name(data.decode(errors="replace")) in names
            and not inside(path, folders)
        }
        marked_packages(top, sources)
        CLAIMED[top] = (folders, sources)
    return CLAIMED[top]


def inside(path: str, folders: list[str]) -> bool:
    return any(path.startswith(folder_prefix(folder)) for folder in folders)


def runtime_text(relative: str, data: bytes) -> bytes:
    """The bytes of a file as a deployed copy keeps them: a `pubspec.yaml` without its `dev_dependencies`, which tests need and a function does not ship."""
    if relative != "pubspec.yaml":
        return data
    kept: list[bytes] = []
    skip = False
    for line in data.splitlines(keepends=True):
        if line.strip() and not line[:1].isspace() and not line.startswith(b"#"):
            skip = line.startswith(b"dev_dependencies:")
        if not skip:
            kept.append(line)
    return b"".join(kept).rstrip(b"\r\n") + b"\n"


def derived_copy(top: Path, folder: str) -> str | None:
    """None when the tracked files under the folder are byte copies of a tracked package of the same pubspec name that no mark exempts (a `pubspec.yaml` is compared without its `dev_dependencies`, and a `pubspec.lock` that the copy adds is pub's own output); otherwise what is wrong, naming the first file that differs. It reads the index, never the disk."""
    index = tracked_index(top)
    pubspecs = pubspec_texts(top)
    prefix = folder_prefix(folder)
    own = pubspecs.get(f"{prefix}pubspec.yaml")
    name = package_name(own.decode(errors="replace")) if own is not None else None
    if name is None:
        return "it holds no pubspec.yaml, so no package is its source"
    folders, _ = claims(top)
    candidates = {
        PurePosixPath(path).parent.as_posix()
        for path, data in pubspecs.items()
        if not path.startswith(prefix)
        and not inside(path, folders)
        and package_name(data.decode(errors="replace")) == name
    }
    sources = sorted(candidates - marked_packages(top, candidates))
    if not sources:
        return f"no unmarked tracked package is named {name}"
    first = ""
    for source in sources:
        for path in tracked_under(top, folder):
            relative = path[len(prefix) :]
            there = index.get(folder_prefix(source) + relative)
            if relative == "pubspec.lock":
                continue
            if there is None or (
                there != index[path]
                and (
                    relative != "pubspec.yaml"
                    or runtime_text(
                        relative, pubspecs[folder_prefix(source) + relative]
                    )
                    != runtime_text(relative, pubspecs[path])
                )
            ):
                first = first or f"{path} differs from {source}/{relative}"
                break
        else:
            SOURCES[top, folder] = source
            return None
    return first


def same_on_disk(top: Path, held: str, source: str) -> bool:
    """The index proof holds on disk too: each file that git reports as changed under the copy or its source has the same bytes at both places, by the proof's own rules."""
    if (top, held) not in ON_DISK:
        status = [*GIT_LISTING, "status", "-z", "--porcelain", "-uall", "--no-renames"]
        changed = subprocess.check_output(
            [*status, "--", held, source], cwd=top, text=True
        ).split("\0")
        ON_DISK[top, held] = all(
            same_file(top, held, source, entry[3:]) for entry in changed if entry
        )
    return ON_DISK[top, held]


def same_file(top: Path, held: str, source: str, path: str) -> bool:
    relative = PurePosixPath(path).relative_to(
        held if PurePosixPath(path).is_relative_to(held) else source
    )
    copied, original = top / held / relative, top / source / relative
    if relative.as_posix() == "pubspec.lock" or not copied.is_file():
        return True
    return original.is_file() and runtime_text(
        relative.as_posix(), copied.read_bytes()
    ) == runtime_text(relative.as_posix(), original.read_bytes())


def proven_copy(top: Path, folder: str) -> str | None:
    if (top, folder) not in PROOFS:
        PROOFS[top, folder] = derived_copy(top, folder)
    return PROOFS[top, folder]


def may_hold_copies(top: Path, folder: Path) -> bool:
    """Whether a folder mark of the root attributes file could name a folder below this one; it reads the marks alone, so a project whose attributes file holds no `**` pays one small read and no parse."""
    try:
        text = (top / ".gitattributes").read_text(errors="replace")
    except OSError:
        return False
    if "**" not in text:
        return False
    folder_marks = [
        pattern
        for pattern in marks(top / ".gitattributes", GENERATED_KEYS)
        if mark_kind(pattern) == "folder"
    ]
    if not folder_marks:
        return False
    parts = folder.resolve().relative_to(top).parts
    for pattern in folder_marks:
        named = pattern.strip("/").removesuffix("/**").split("/")
        if "**" in named or (
            len(named) > len(parts)
            and all(fnmatchcase(part, name) for part, name in zip(parts, named))
        ):
            return True
    return False


def proven_copies(root: Path, folder: Path) -> dict[str, str]:
    """The folders below this folder that a mark claims and the proof accepts, each with the package folder it copies; every path is relative to the repository top."""
    top = repository_top(root)
    if not may_hold_copies(top, folder):
        return {}
    prefix = folder_prefix(folder.resolve().relative_to(top).as_posix())
    return {
        held: SOURCES[top, held]
        for held in claims(top)[0]
        if held.startswith(prefix) and proven_copy(top, held) is None
    }


def folder_of(pattern: str, name: str) -> str | None:
    parts = pattern.strip("/").removesuffix("/**")
    pieces = name.split("/")
    for end in range(1, len(pieces)):
        if regex(parts).fullmatch("/".join(pieces[:end])):
            return "/".join(pieces[:end])
    return None


def hidden_by_exact_marks(root: Path, name: str, keys: set[str]) -> bool:
    top = repository_top(root)
    full = PurePosixPath((root.resolve() / name).relative_to(top).as_posix())
    folder = full.parent
    patterns = [
        (pattern, str(full.relative_to(base)))
        for base in (*reversed(folder.parents), folder)
        for pattern in marks(top / base / ".gitattributes", keys)
    ]
    patterns += [
        (pattern, str(full))
        for pattern in marks(top / ".git" / "info" / "attributes", keys)
    ]
    for pattern, relative in patterns:
        kind = mark_kind(pattern)
        if kind is None or not regex(pattern).fullmatch(relative):
            continue
        if kind != "folder":
            return True
        held = folder_of(pattern, relative)
        prefix = str(full)[: len(str(full)) - len(relative)]
        if held is not None and proven_copy(top, prefix + held) is None:
            return True
    return False


def marked_folders(top: Path, pattern: str) -> list[str]:
    """The tracked folders that a folder mark names: the one folder, or each folder that its glob matches."""
    folder = pattern.strip("/").removesuffix("/**")
    if not has_glob(folder):
        return [folder]
    folders = {parent for name in tracked_index(top) for parent in ancestors(name)[:-1]}
    matcher = regex(pattern.removesuffix("/**"))
    return sorted(held for held in folders if matcher.fullmatch(held))


def copy_findings(root: Path) -> list[str]:
    """A folder mark that claims a derived copy whose files differ from their source."""
    top = repository_top(root)
    found = []
    for pattern in marks(top / ".gitattributes", GENERATED_KEYS):
        if mark_kind(pattern) != "folder":
            continue
        for folder in marked_folders(top, pattern):
            reason = proven_copy(top, folder)
            if reason and " differs from " in reason:
                found.append(
                    f".gitattributes marks {folder} as a copy: {reason}; a vendored copy must equal its source, so run the project's sync"
                )
    return found


def marked_by_git(root: Path, names: list[str], keys: set[str]) -> set[str]:
    import tempfile

    # A live stdin pipe deadlocked against git's per-path output on macOS (issue 375).
    with tempfile.TemporaryFile() as paths:
        paths.write(("\0".join(names) + "\0").encode())
        paths.seek(0)
        listed = subprocess.run(
            [*GIT_LISTING, "check-attr", "-z", "--all", "--stdin"],
            cwd=root,
            capture_output=True,
            text=True,
            stdin=paths,
            check=False,
        )
    if listed.returncode:
        repository = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=root,
            capture_output=True,
            check=False,
        )
        if repository.returncode:
            return set()  # Standalone source directories have no Git attributes.
        sys.stderr.write(listed.stderr)
        listed.check_returncode()
    attributes = listed.stdout.split("\0")
    return {
        name
        for name, key, value in zip(attributes[::3], attributes[1::3], attributes[2::3])
        if key in keys and value in {"set", "true"}
    }


def generated_sources(
    root: Path, names: list[str], generated_only: bool = False
) -> set[str]:
    if not names:
        return set()
    listed, generated = LISTED.get(root, (frozenset(), set()))
    if listed.issuperset(names) and not generated_only:
        return generated.intersection(names)
    keys = {"linguist-generated"} if generated_only else GENERATED_KEYS
    marked = marked_by_git(root, names, keys)
    if keys == GENERATED_KEYS and root.resolve() == repository_top(root):
        ASKED[root.resolve()] = (set(names), set(marked))
    return {name for name in marked if hidden_by_exact_marks(root, name, keys)}
