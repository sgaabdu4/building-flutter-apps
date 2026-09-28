"""Prove omitted TypeScript has no runtime content without executing it."""

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
const { readFileSync } = require('node:fs');
const { stripTypeScriptTypes } = require('node:module');
if (typeof stripTypeScriptTypes !== 'function') throw Error('Node type stripping required');
const sources = JSON.parse(readFileSync(0, 'utf8'));
console.log(JSON.stringify(sources.map(source => {
  try { return stripTypeScriptTypes(source); }
  catch { return null; }
})));
"""
    result = subprocess.run(
        ["node", "-e", script],
        input=json.dumps([file.read_text() for file in candidates]),
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
