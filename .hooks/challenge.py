"""Run the other agent CLI as a read-only adversarial reviewer and record the outcome."""

import json
import os
import subprocess
from pathlib import Path

from plans import default_branch_point, size_verdict

TIMEOUT_SECONDS = 1800
READ_ONLY_GIT = ("diff", "log", "show", "status", "merge-base", "ls-files")
PROMPT = (
    "Adversarially review the change on this branch: `git diff {point} HEAD` (revision "
    "{revision}). Read .agents/skills/code-review/references/challenge.md if present and "
    "follow its assignment: find the intended outcome (PLAN.md, commit messages), try to "
    "disprove each material claim, report only realistic failures as file:line findings "
    "with the triggering condition and impact, and edit nothing. Finish with one last "
    "line, exactly `VERDICT: clean` or `VERDICT: findings`."
)


def reviewer_for(host: str | None) -> str:
    """The agent that reviews: the one the running host is not."""
    if host is None:
        if os.environ.get("CLAUDECODE") == "1":
            host = "claude"
        elif os.environ.get("CODEX_THREAD_ID"):
            host = "codex"
    if host is None:
        raise ValueError(
            "Cannot tell whether Claude Code or Codex is running; pass --host claude or --host codex"
        )
    return "codex" if host == "claude" else "claude"


def command(reviewer: str, prompt: str, root: Path) -> list[str]:
    if reviewer == "codex":
        return ["codex", "exec", "--sandbox", "read-only", "--cd", str(root), prompt]
    allowed = " ".join(
        ["Read", "Grep", "Glob"] + [f"Bash(git {g} *)" for g in READ_ONLY_GIT]
    )
    return [
        "claude",
        "--print",
        prompt,
        "--safe-mode",
        "--tools",
        "Read,Grep,Glob,Bash",
        "--allowedTools",
        allowed,
        "--permission-mode",
        "dontAsk",
        "--no-session-persistence",
    ]


def store(root: Path, revision: str) -> Path:
    git_path = subprocess.run(
        ["git", "rev-parse", "--git-path", "hard-eng/challenge"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return root / git_path / revision


def review(
    root: Path, reviewer: str, base: str | None, revision: str
) -> tuple[str, str]:
    """Run the reviewer; return its outcome and output."""
    point = base or default_branch_point(root) or "HEAD"
    try:
        result = subprocess.run(
            command(reviewer, PROMPT.format(point=point, revision=revision), root),
            cwd=root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return f"not done: {reviewer} is not installed", ""
    except subprocess.TimeoutExpired:
        return f"not done: {reviewer} timed out after {TIMEOUT_SECONDS}s", ""
    if result.returncode != 0:
        reason = result.stderr.strip().rpartition("\n")[2] or "no error output"
        return f"not done: {reviewer} exited {result.returncode}: {reason}", ""
    lines = result.stdout.strip().splitlines()
    if not lines:
        return f"not done: {reviewer} returned no review", ""
    return (
        "clean" if lines[-1].strip() == "VERDICT: clean" else "findings"
    ), result.stdout


def challenge(root: Path, base: str | None, host: str | None) -> int:
    reviewer = reviewer_for(host)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    outcome, output = review(root, reviewer, base, revision)
    path = store(root, revision)
    path.parent.mkdir(parents=True, exist_ok=True)
    if outcome.startswith("not done") and path.with_suffix(".json").is_file():
        earlier = json.loads(path.with_suffix(".json").read_text())["outcome"]
        if not earlier.startswith("not done"):
            print(f"Independent review by {reviewer} at {revision}: {outcome}")
            print(f"Kept the earlier completed review for this revision: {earlier}")
            return 0
    path.with_suffix(".txt").write_text(output)
    path.with_suffix(".json").write_text(
        json.dumps(
            {
                "reviewer": reviewer,
                "revision": revision,
                "outcome": outcome,
                "output": str(path.with_suffix(".txt")),
            }
        )
    )
    print(f"Independent review by {reviewer} at {revision}: {outcome}")
    print(f"Reviewer output: {path.with_suffix('.txt')}")
    if outcome == "findings":
        print(
            "Verify each finding against source; fix only reachable, realistic defects."
        )
    return 1 if outcome.startswith("not done") else 0


def shipping_note(root: Path, revision: str) -> str | None:
    """The line shipping prints for a big change; raises when its review is missing."""
    small, reason = size_verdict(root)
    if small:
        return None
    path = store(root, revision).with_suffix(".json")
    if not path.is_file():
        raise ValueError(
            f"This change is big ({reason}) and revision {revision} has no independent "
            "review. Run `python3 .hooks/hard-eng.py challenge` first."
        )
    record = json.loads(path.read_text())
    if record["outcome"].startswith("not done"):
        return f"independent review {record['outcome']}"
    return f"Independent review by {record['reviewer']}: {record['outcome']}"
