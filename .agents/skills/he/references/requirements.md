# Requirements

Each Hard Eng rule is defined once here, under a stable ID. Code, tests, skills and docs name the ID instead of restating the rule. `python3 .hooks/hard-eng.py check` fails on a repeated, unknown or retired ID, a `Proof: check` rule without an enforcing source and a test that name it, a `Proof: guidance` rule without a skill or `AGENTS.md` link, and a definition sentence copied into other Markdown.

A project may add its own rules as `REQ-` IDs in `docs/requirements.md`, in the same format. A test names an ID in its name string (JavaScript, Dart) or the first line of its docstring (Python). Never reuse an ID; a retired entry keeps its heading and holds only `Status: Retired — use <ID>`.

## HE-REQUIREMENT-REGISTRY

Every rule has one definition in a requirement registry, under an ID that is never reused. Other files name the ID instead of repeating the rule.

Proof: check

## HE-COVERAGE-MIN

A language package's tests cover at least 70% of its executable lines. The tests gate fails when its coverage report shows less.

Proof: check

## HE-FILE-LENGTH

A handwritten source or test file holds at most 1000 physical lines. A larger file needs an exact, reviewed file-size exception with a reason and evidence.

Proof: check

## HE-PERFORMANCE-SUITE

Each language package runs a performance suite with a real workload, a time budget and a native report. A package without a meaningful workload records a nonblank, reviewed `performance_exception` instead.

Proof: check

## HE-DEBT-SHRINK-ONLY

Findings that existing code fails with when Hard Eng is installed may be recorded once, by `python3 .hooks/hard-eng.py adopt`, in `hard-eng.debt.json`. A gate with recorded lines fails on any output line beyond them, and when a recorded line is gone but still listed. Only the change that installs Hard Eng can add the file; later changes only remove lines. Tests, lockfiles and secrets never carry debt.

Proof: check

## HE-COMMENT-LINES

A changed source file holds no comment block longer than one line. Generated output and scaffold paths are exempt.

Proof: check

## HE-NO-SWITCH-OFF

A change fails when its added lines hold a Python, JavaScript, TypeScript, Dart or Swift suppression or a skipped or focused test, a Semgrep or Gitleaks inline marker in any file, or an entry in `.gitleaksignore` or `.semgrepignore`. It also fails when it removes more `assert` or `expect(` lines from test files than it adds. Paths under `.hooks/`, `.agents/` and `.claude/` are exempt, lines that existed before the change are not flagged, and there is no allow-list.

Proof: check

## HE-UNTRUSTED-JSON

In JavaScript and TypeScript, parsed JSON has the type `unknown` until code validates it. TypeScript configurations must load the Hard Eng declarations that set this type.

Proof: check

## HE-ADR-SCOPE

A changed, unsuperseded decision record names the paths it governs on an `Applies to:` line. A change that removes the last file under such a path must update or supersede the record.

Proof: check

## HE-OUTPUT-PLAIN

Agent replies and reports use plain, simplified technical English: one idea per sentence, active voice and common words. Reports state changes, proof and gaps.

Proof: guidance

## HE-NO-FOREGROUND-POLL

An agent starts a long job in the background and waits for the host's exit notice; it never waits in a foreground sleep loop or a long sleep. In Claude Code, a hook denies a main-session shell command that sleeps at least 1 second inside a `while` or `until` loop, or at least 30 seconds at once. A subagent may wait in the foreground, because nothing watches its background job after its turn ends. Codex returns a long command early and waits on that command's session, not on a sleep loop.

Proof: check

## HE-YAGNI

Add a file, dependency, abstraction, configuration or stored state only for a current agreed requirement that existing code or a direct command cannot meet.

Proof: guidance
