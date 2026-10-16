"""Prove omitted TypeScript and Swift files have no runtime content without executing them."""

import json
import re
import subprocess
from pathlib import Path


def erased_typescript(files: set[Path]) -> set[Path]:
    candidates = sorted(
        file for file in files if file.suffix in {".ts", ".tsx", ".mts", ".cts"}
    )
    if not candidates:
        return set()
    script = """
const sources = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
console.log(JSON.stringify(sources.map(([loader, source]) => {
  try { return new Bun.Transpiler({ loader }).transformSync(source); }
  catch { return null; }
})));
"""
    result = subprocess.run(
        ["bun", "-e", script],
        input=json.dumps(
            [
                ["tsx" if file.suffix == ".tsx" else "ts", file.read_text()]
                for file in candidates
            ]
        ),
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    outputs = json.loads(result.stdout)
    if not isinstance(outputs, list) or len(outputs) != len(candidates):
        raise ValueError("Invalid native TypeScript stripping result")
    # Only whitespace, comments, empty statements and an empty export remain.
    empty = (
        r"(?:\s|;|//[^\r\n\u2028\u2029]*|"
        r"/\*(?:[^*]|\*(?!/))*\*/|export\s*\{\s*\})*"
    )
    return {
        file
        for file, output in zip(candidates, outputs, strict=True)
        if isinstance(output, str) and re.fullmatch(empty, output)
    }


COUNTER_NODES = ("brace_stmt", "closure_expr", "original_init", "top_level_code_decl")


def erased_swift(files: set[Path]) -> set[Path]:
    """Parse-only proof: no body, closure or initial value, so Xcode lists no counters."""
    erased = set()
    for file in sorted(files):
        if re.search(r"(?m)^\s*#if\b", file.read_text()):
            continue  # The parse drops code inside conditional compilation.
        parsed = subprocess.run(
            ["swiftc", "-frontend", "-dump-parse", str(file)],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if parsed.returncode == 0 and not any(
            f"({node}" in parsed.stdout for node in COUNTER_NODES
        ):
            erased.add(file)
    return erased
