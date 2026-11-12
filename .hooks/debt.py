"""Shrink-only adoption debt: findings the existing code had when Hard Eng was installed."""

import json
import re
import subprocess
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from gate_config import SOURCE_FILE, Gate, Group, JsonObject
from project_files import read_project_file

WORD_CHARACTER = re.compile(r"\w")
DIGIT_RUN = re.compile(r"\d+")
COUNTED_WORDS = re.compile(r"(?<!\w)N((?: \w+){1,2})")
WORD = re.compile(r"\w+")
SPACE_RUN = re.compile(r"[ \t]+")
TIME = re.compile(r"(?<!\w)N(?:\.N)?(?:ns|[µu]s|ms|s)(?!\w)")
RULE_FOLDER = re.compile(r"[\w.-]*hard-eng-rules\.")
CODE_FRAME = re.compile(r"[> ]*(?:N[ ]*)*[│|]")

SUMMARY = re.compile(r"\W*Some (?:errors|warnings) were emitted while running checks")
# Ruff's fix advice for a finding, and its count of fixes: they change with the code near an old finding.
RUFF_HINT = re.compile(
    r"help: |note: |- |N \+ |N (?:\w+ )?fix |\[\*\] N fixabl|No fixes available"
)
DEBT_FILE = "hard-eng.debt.json"
GATE_OUTPUT_LIMIT = 8000
DEBT_LINE = re.compile(r"(?m)^DEBT (\S+) @ (\S+):.*$")
# Failing tests, broken installs and leaked secrets are never old findings to keep.
NEVER = {"tests", "lockfiles", "secrets-files", "secrets-history"}
MISSING_SUITE = "HE-PERFORMANCE-SUITE"
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
RUNNER_LINES = re.compile(
    r"^(warning: (The `UV_|`VIRTUAL_ENV=)|mise |(Downloading|Downloaded|Installed|Uninstalled"
    r"|Resolved|Prepared|Audited|Building|Built) )"
)


def osv_findings(path: Path) -> list[str]:
    report = json.loads(path.read_text())
    return [
        f"{item['package']['name']} {item['package']['version']} "
        + ",".join(
            sorted(vulnerability["id"] for vulnerability in item["vulnerabilities"])
        )
        for result in report["results"]
        for item in result["packages"]
        if item.get("vulnerabilities")
    ]


def semgrep_findings(path: Path) -> list[str]:
    report = json.loads(path.read_text())
    return [
        f"{result['check_id']} {result['path']} {result['extra'].get('lines', '')}"
        for result in report["results"]
    ]


def jscpd_findings(path: Path) -> list[str]:
    report = json.loads(path.read_text())
    return [
        f"{clone['firstFile']['name']} {clone['secondFile']['name']} {clone.get('fragment', '')}"
        for clone in report["duplicates"]
    ]


def deptry_findings(path: Path) -> list[str]:
    report = json.loads(path.read_text())
    return [
        f"{issue['error']['code']} {issue['module']} {issue['location']['file']}"
        for issue in report
    ]


# Report types whose findings live in the report file; findings of the others are in the output.
REPORT_FINDINGS: dict[str, Callable[[Path], list[str]]] = {
    "osv": osv_findings,
    "semgrep": semgrep_findings,
    "jscpd": jscpd_findings,
    "deptry": deptry_findings,
}
OUTPUT_REPORTS = {None, "import-linter", "performance-junit"}
OUTPUTS: dict[str, str] = {}
UNREADABLE = "unreadable report"


def remember(group: Group, gate: Gate, text: str) -> str:
    """Keep a gate's output for the debt comparison and pass it on."""
    key = f"{group['path']}/{gate['name']}"
    OUTPUTS[key] = f"{OUTPUTS.get(key, '')}\n{text}"
    return text


def lacks_suite(gate: Gate, output: str) -> bool:
    return gate.get("role") == "performance" and MISSING_SUITE in output


def recordable(gate: Gate) -> bool:
    kind = gate.get("report", {}).get("type")
    return gate.get("role") not in NEVER and (
        kind in REPORT_FINDINGS or kind in OUTPUT_REPORTS
    )


def real_lines(root: Path, group: Group, gate: Gate, output: str) -> list[str]:
    report = gate.get("report", {})
    path = root / group["path"] / report.get("path", "")
    lines = output.splitlines()
    if report.get("stdout") is True and path.is_file():
        lines += path.read_text().splitlines()
    cleaned = [ANSI.sub("", line).replace(str(root), ".").strip() for line in lines]
    return [line for line in cleaned if line and not RUNNER_LINES.match(line)]


def stable_rules(line: str) -> str:
    """Semgrep names a rule from the folder of its rules file; the temp folder is no part of the rule."""
    return RULE_FOLDER.sub("agents.skills.he.semgrep.", line)


def fingerprints(root: Path, group: Group, gate: Gate, output: str) -> Counter[str]:
    """Output lines with line numbers, counts and the checkout path made neutral."""
    report = gate.get("report", {})
    path = root / group["path"] / report.get("path", "")
    found: Counter[str] = Counter(
        DIGIT_RUN.sub("N", stable_rules(line))
        for line in real_lines(root, group, gate, output)
    )
    extract = REPORT_FINDINGS.get(str(report.get("type")))
    if extract is not None and path.is_file():
        try:
            found.update(map(stable_rules, extract(path)))
        except (ValueError, KeyError, TypeError, AttributeError):
            found[UNREADABLE] += 1
    return found


def neutral(line: str) -> str:
    """The line with the words after a count in one form, so 1 error and 2 errors match."""

    def singular(word: re.Match[str]) -> str:
        return word.group().removesuffix("s").removesuffix("e")

    return COUNTED_WORDS.sub(
        lambda counted: "N" + WORD.sub(singular, counted.group(1)),
        TIME.sub("Ntime", ANSI.sub("", stable_rules(SPACE_RUN.sub(" ", line)))),
    )


def real_forms(lines: list[str]) -> dict[str, list[str]]:
    forms: dict[str, list[str]] = {}
    for line in lines:
        forms.setdefault(neutral(DIGIT_RUN.sub("N", line)), []).append(line)
    return forms


def ruff_check(command: list[str]) -> int:
    """The place of the tool word in a `ruff check` command, or -1; only that command prints fix advice."""
    tool = next(
        (i for i, part in enumerate(command) if part.split("@")[0] == "ruff"), -1
    )
    return tool if tool >= 0 and command[tool + 1 : tool + 2] == ["check"] else -1


def by_form(lines: Counter[str], ruff: bool = False) -> Counter[str]:
    forms: Counter[str] = Counter()
    for line, count in lines.items():
        form = neutral(line)
        advice = CODE_FRAME.match(form) or SUMMARY.match(form)
        if not (advice or (ruff and RUFF_HINT.match(form))):
            forms[form] += count
    return forms


def still_found(old: Counter[str], current: Counter[str]) -> Counter[str]:
    """Recorded lines whose form the current run still has, in their recorded spelling."""
    available = by_form(current)
    kept: Counter[str] = Counter()
    for line, count in old.items():
        taken = min(count, available[neutral(line)])
        if taken:
            kept[line] = taken
            available[neutral(line)] -= taken
    return kept


def load(root: Path) -> dict[str, Counter[str]]:
    path = root / DEBT_FILE
    if not path.is_file():
        return {}
    debt = read_project_file(path, root)
    gates = debt.get("gates") if isinstance(debt, dict) else None
    if (
        not isinstance(debt, dict)
        or debt.get("version") != 1
        or not isinstance(gates, dict)
        or not all(
            isinstance(lines, dict)
            and all(type(count) is int and count > 0 for count in lines.values())
            for lines in gates.values()
        )
    ):
        raise ValueError(
            f"{DEBT_FILE} must hold version 1 and positive counts per gate"
        )
    return {key: Counter(lines) for key, lines in gates.items()}


def print_new(
    new: Counter[str], recorded: Counter[str], spelling: dict[str, list[str]]
) -> None:
    """Lines of forms with no recorded line first, then the doubtful ones; 20 lines in all."""

    def ordered(forms: list[str]) -> list[str]:
        return sorted(
            (line for form in forms for line in spelling[form]),
            key=lambda line: not WORD_CHARACTER.search(line),
        )

    surely = ordered([form for form in new if not recorded[form]])
    doubtful = [form for form in new if recorded[form]]
    candidates = ordered(doubtful)
    lines = [f"  {line}" for line in surely[:20]]
    if candidates and len(lines) < 20:
        sure_new = sum(new[form] for form in doubtful)
        lines.append(
            f"  {sure_new} of these {len(candidates)} lines are new; the others are recorded:"
        )
        lines.append(
            "  The debt file has no line numbers. Run the tool of this check on the files of this change to find the new ones."
        )
        lines += [f"  {line}" for line in candidates[: 20 - len(surely)]]
    cut = len(surely) + len(candidates) - 20
    print("\n".join(lines + ([f"  {cut} more lines not shown"] if cut > 0 else [])))


def judge(root: Path, group: Group, gate: Gate, failed: bool, output: str) -> bool:
    """A gate with debt fails only on findings beyond it, or when listed ones are fixed."""
    debt = load(root).get(f"{group['path']}/{gate['name']}")
    if debt is None or gate.get("role") in NEVER or lacks_suite(gate, output):
        return failed
    current = fingerprints(root, group, gate, output) if failed else Counter()
    ruff = ruff_check(gate["command"]) >= 0
    old = by_form(debt, ruff)
    if new := by_form(current, ruff) - old:
        print(f"FAIL {gate['name']} @ {group['path']}: findings beyond {DEBT_FILE}:")
        spelling = {neutral(line): [line] for line in current}
        spelling.update(real_forms(real_lines(root, group, gate, output)))
        print_new(new, old, spelling)
        return True
    if fixed := old - by_form(current, ruff):
        print(
            f"FAIL {gate['name']} @ {group['path']}: {fixed.total()} recorded lines are fixed; run "
            f"`python3 .hooks/hard-eng.py adopt` to drop them from {DEBT_FILE}"
        )
        return True
    print(
        f"DEBT {gate['name']} @ {group['path']}: the failure above holds only the "
        f"{debt.total()} lines recorded in {DEBT_FILE}; no new finding"
    )
    return False


def worktree(root: Path) -> bytes:
    """Tracked changes plus untracked, unignored file contents."""
    untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=root
    ).split(b"\0")
    files = [root / name.decode() for name in untracked if name]
    return subprocess.check_output(["git", "diff"], cwd=root) + b"".join(
        bytes(path) + path.read_bytes() for path in files if path.is_file()
    )


def settled_run(root: Path, run: Callable[[], object]) -> None:
    """Run the gates; when they fixed files, record what the fixed code still fails with."""
    refuse_new_debt(root, None)
    before = worktree(root)
    run()
    if worktree(root) != before:
        OUTPUTS.clear()
        run()


def record(
    root: Path, groups: list[Group], failed: set[str], outputs: dict[str, str]
) -> int:
    """Write the debt once; later runs only drop lines that are gone."""
    old = load(root) if (root / DEBT_FILE).is_file() else None
    gates: JsonObject = {}
    refused = []
    left_out: Counter[str] = Counter()
    for group in groups:
        for gate in group["checks"]:
            key = f"{group['path']}/{gate['name']}"
            if key not in failed:
                continue
            current = fingerprints(root, group, gate, outputs.get(key, ""))
            if (
                not recordable(gate)
                or not current
                or UNREADABLE in current
                or lacks_suite(gate, outputs.get(key, ""))
            ):
                refused.append(key)
                continue
            if old is not None:
                ruff = ruff_check(gate["command"]) >= 0
                kept = still_found(old.get(key, Counter()), current)
                if fresh := by_form(current, ruff) - by_form(kept, ruff):
                    left_out[key] = fresh.total()
                current = kept
            if current:
                gates[key] = dict(sorted(current.items()))
    if refused and old is None:
        print(
            f"These checks must pass before adoption; fix them first: {', '.join(refused)}"
        )
        return 1
    (root / DEBT_FILE).write_text(
        json.dumps({"version": 1, "gates": gates}, indent=2) + "\n"
    )
    print(
        f"Recorded {len(gates)} checks with old findings in {DEBT_FILE}; it can only shrink."
    )
    if left_out:
        print(
            f"Did not record {left_out.total()} new findings in {', '.join(left_out)}; "
            "`check` fails until they are fixed."
        )
    return 0


def git_file(root: Path, base: str, name: str) -> str | None:
    from plans import _git_output

    try:
        return _git_output(root, "show", f"{base}:{name}")
    except subprocess.CalledProcessError:
        return None


def local_base_branch(root: Path) -> str:
    """The local branch that `default_branch_point` took the base from; empty when it is not a local branch."""
    from plans import _git_output, release_references

    for reference in release_references(root):
        try:
            _git_output(root, "merge-base", "HEAD", reference)
        except (subprocess.CalledProcessError, OSError):
            continue
        try:
            _git_output(root, "rev-parse", "--verify", "-q", f"refs/heads/{reference}")
        except (subprocess.CalledProcessError, OSError):
            return ""
        return reference
    return ""


def lone_install_step(root: Path, base: str) -> str:
    """The step that lets `adopt` pass when a local base branch that no remote holds is the install commit."""
    from plans import _git_output

    if (
        _git_output(root, "rev-parse", "HEAD").strip() != base
        or git_file(root, "HEAD~1", SOURCE_FILE) is not None
        or not (target := local_base_branch(root))
        or _git_output(root, "for-each-ref", f"refs/remotes/*/{target}").strip()
    ):
        return ""
    start = f"; the base branch `{target}` is not on a remote yet, so the install commit is the base"
    if _git_output(root, "rev-list", "--parents", "-n1", "HEAD").split()[1:]:
        undo = "git reset --soft HEAD~1"
    elif _git_output(root, "branch", "--show-current").strip() == target:
        undo = "git update-ref -d HEAD"
    else:
        moved = _git_output(root, "branch", "--show-current").strip()
        after = (
            f"; after the commit move your branch with `git branch -f {moved} {target}`"
            if moved
            else ""
        )
        return f"{start} and holds only the install commit: switch to `{target}`, then run `adopt` again for the next step{after}"
    return f"{start}: run `{undo}`, then `adopt`, then commit the install and the debt file together"


def refuse_new_debt(root: Path, base: str | None) -> str | None:
    """HE-DEBT-SHRINK-ONLY: only the change that installs Hard Eng can add the debt file."""
    from plans import default_branch_point

    given = base is not None
    base = base or default_branch_point(root)
    if (
        base is not None
        and git_file(root, base, DEBT_FILE) is None
        and git_file(root, base, SOURCE_FILE) is not None
    ):
        raise ValueError(
            f"HE-DEBT-SHRINK-ONLY: only the change that installs Hard Eng can add {DEBT_FILE}; repair the findings that `check` prints instead"
            + ("" if given else lone_install_step(root, base))
        )
    return base


def require_shrink(root: Path, base: str | None) -> None:
    """HE-DEBT-SHRINK-ONLY: debt appears only with the install and never grows."""
    current = load(root)
    if not current:
        return
    base = refuse_new_debt(root, base)
    before = git_file(root, base, DEBT_FILE) if base is not None else None
    if before is None:
        return
    old = {key: Counter(lines) for key, lines in json.loads(before)["gates"].items()}
    if grown := sorted(
        key for key, lines in current.items() if lines - old.get(key, Counter())
    ):
        raise ValueError(
            f"HE-DEBT-SHRINK-ONLY: {DEBT_FILE} grew for {', '.join(grown)}; repair the new findings instead"
        )


def bounded(text: str, *, tail: bool = False) -> str:
    if len(text := ANSI.sub("", text)) <= GATE_OUTPUT_LIMIT:
        return text
    note = "\n[gate output cut; rerun check for the full log]\n"
    return note + text[-GATE_OUTPUT_LIMIT:] if tail else text[:GATE_OUTPUT_LIMIT] + note


def keep_debt_lines(shown: str, log: str) -> str:
    """Put each DEBT line of the log right after the FAIL line of its gate, where shown has it."""
    for note in DEBT_LINE.finditer(log):
        failed = re.search(
            rf"(?m)^FAIL {re.escape(note[1])} \(exit \d+;[^\n]* @ {re.escape(note[2])}(?!\S)[^\n]*\n",
            shown,
        )
        if failed:
            shown = shown[: failed.end()] + note[0] + "\n" + shown[failed.end() :]
    return shown
