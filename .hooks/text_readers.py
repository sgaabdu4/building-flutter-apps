"""HE-NO-TEXT-WALLS: run the reader of a screen language; the reader returns the text parts and never counts."""

import fcntl
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict

from text_reader_programs import DART_READER, JS_READER

HOOKS = Path(__file__).resolve().parent
LIMIT = 120
JS_MANIFEST = '{"private": true, "dependencies": {"oxc-parser": "0.158.0"}}\n'
NEEDS_BUN = (
    "HE-NO-TEXT-WALLS: reading the changed TSX or JSX screens needs Bun. Install Bun, "
    "or in CI add an oven-sh/setup-bun step before the check"
)
INSTALL_FAILED = (
    "HE-NO-TEXT-WALLS: installing the {kind} reader failed: {error}. "
    "Run the check once with network access"
)
NEEDS_DART = (
    "HE-NO-TEXT-WALLS: reading the changed Flutter screens needs the Dart SDK 3.11 or newer "
    "once, to build its reader. Install Dart or Flutter, or in CI add the Dart SDK before the check"
)
LABELS = {"js": "TSX and JSX", "dart": "Dart"}
READY = {"js": "node_modules/oxc-parser/package.json", "dart": "reader.exe"}
READ_FAILED = "HE-NO-TEXT-WALLS: the {kind} reader failed: {error}"


class Block(TypedDict):
    line: int
    lines: list[int]
    kind: str
    name: str
    parts: list[object]
    clamp: int | None
    tap: bool
    user: bool


class FileBlocks(TypedDict):
    path: str
    error: str | None
    blocks: list[Block]


def tool_folder() -> Path:
    from tool_setup import shared_tool_folder

    return shared_tool_folder()


def install_js(staging: Path) -> None:
    environment = dict(os.environ)
    environment.setdefault(
        "BUN_INSTALL_CACHE_DIR", str(tool_folder() / "bun" / "cache")
    )
    (staging / "package.json").write_text(JS_MANIFEST)
    (staging / "bun.lock").write_bytes((HOOKS / "text_walls.bun.lock").read_bytes())
    (staging / "reader.mjs").write_text(JS_READER)
    done = subprocess.run(
        ["bun", "install", "--frozen-lockfile", "--ignore-scripts"],
        cwd=staging,
        env=environment,
        capture_output=True,
        text=True,
        timeout=LIMIT,
        check=False,
    )
    if done.returncode:
        raise ValueError(
            INSTALL_FAILED.format(kind=LABELS["js"], error=done.stderr.strip())
        )


def compile_dart(staging: Path) -> None:
    from dart_coverage import run_dart

    if shutil.which("dart") is None:
        raise ValueError(NEEDS_DART)
    for suffix in ("yaml", "lock"):
        name = f"dart_declarations.pubspec.{suffix}"
        target = "pubspec." + suffix
        (staging / target).write_bytes((HOOKS / name).read_bytes())
    (staging / "reader.dart").write_text(DART_READER)
    resolve = ["pub", "get", "--enforce-lockfile"]
    try:
        try:
            run_dart([*resolve, "--offline"], staging, LIMIT)
        except ValueError:
            run_dart(resolve, staging, LIMIT)
        run_dart(["compile", "exe", "reader.dart", "-o", "reader.exe"], staging, 600)
    except ValueError as error:
        raise ValueError(READ_FAILED.format(kind="Dart", error=error)) from error


def reader_folder(
    prefix: str, parts: list[bytes], build: Callable[[Path], None]
) -> Path:
    """The folder with an installed reader, built once for each pin and program."""
    digest = hashlib.sha256()
    for part in parts:
        digest.update(hashlib.sha256(part).digest())
    root = tool_folder() / "text-readers"
    folder = root / f"{prefix}-{digest.hexdigest()[:12]}"
    if (folder / READY[prefix]).is_file():
        return folder
    root.mkdir(parents=True, exist_ok=True)
    with (root / "install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not (folder / READY[prefix]).is_file():
            shutil.rmtree(folder, ignore_errors=True)
            staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=root))
            try:
                build(staging)
                staging.rename(folder)
            except (subprocess.SubprocessError, OSError) as error:
                shutil.rmtree(staging, ignore_errors=True)
                raise ValueError(
                    INSTALL_FAILED.format(kind=LABELS[prefix], error=error)
                ) from error
            except BaseException:
                shutil.rmtree(staging, ignore_errors=True)
                raise
    return folder


def run_reader(
    command: list[str], folder: Path, query: dict[str, object], kind: str
) -> list[FileBlocks]:
    try:
        done = subprocess.run(
            command,
            cwd=folder,
            input=json.dumps(query),
            capture_output=True,
            text=True,
            timeout=LIMIT,
            check=True,
        )
        files: list[FileBlocks] = json.loads(done.stdout)["files"]
    except subprocess.CalledProcessError as error:
        raise ValueError(
            READ_FAILED.format(kind=kind, error=error.stderr.strip())
        ) from error
    except (subprocess.SubprocessError, OSError, ValueError, KeyError) as error:
        raise ValueError(READ_FAILED.format(kind=kind, error=error)) from error
    return files


def read(kind: str, query: dict[str, object]) -> list[FileBlocks]:
    """One reader process reads every file of the query."""
    if kind == "dart":
        folder = reader_folder(
            "dart",
            [
                (HOOKS / "dart_declarations.pubspec.yaml").read_bytes(),
                (HOOKS / "dart_declarations.pubspec.lock").read_bytes(),
                DART_READER.encode(),
                f"{platform.system()} {platform.machine()}".encode(),
            ],
            compile_dart,
        )
        return run_reader([str(folder / "reader.exe")], folder, query, "Dart")
    if kind != "js":
        raise ValueError(READ_FAILED.format(kind=kind, error="no such reader"))
    if shutil.which("bun") is None:
        raise ValueError(NEEDS_BUN)
    folder = reader_folder(
        "js",
        [
            JS_MANIFEST.encode(),
            (HOOKS / "text_walls.bun.lock").read_bytes(),
            JS_READER.encode(),
        ],
        install_js,
    )
    return run_reader(["bun", str(folder / "reader.mjs")], folder, query, "TSX and JSX")
