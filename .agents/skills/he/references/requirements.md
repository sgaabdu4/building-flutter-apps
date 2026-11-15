# Requirements

Each Hard Eng rule is defined once here, under a stable ID. Code, tests, skills and docs name the ID instead of restating the rule. `python3 .hooks/hard-eng.py check` fails on a repeated, unknown or retired ID, a `Proof: check` rule without an enforcing source and a test that name it, a `Proof: guidance` rule without a skill or `AGENTS.md` link, and a definition sentence copied into other Markdown.

A project may add its own rules as `REQ-` IDs in `docs/requirements.md`, in the same format. An ID is a prefix and parts joined by hyphens; each part holds only capital letters and digits. An `HE-` ID has one or more parts, and a `REQ-` ID has two or more. A test names an ID in its name string (JavaScript, Dart) or the first line of its docstring (Python). Never reuse an ID; a retired entry keeps its heading and holds only `Status: Retired — use <ID>`.

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

A changed source file holds no comment block longer than one line. Generated output and scaffold paths are exempt. In the change that installs Hard Eng, blocks that a file held before that change are also exempt. In each later change, every comment block longer than one line in a changed file fails the check.

Proof: check

## HE-NO-SWITCH-OFF

A change fails when its added lines hold any of these: a Python, JavaScript, TypeScript, Dart or Swift suppression; a skipped or focused test (a call such as `it.skip(` counts in every file; a bare skip name such as `it.skip` with no call counts only in a test file); a test retry: a retry setting in a test config, in a command of `package.json` or `hard-eng.gates.json` or in an Xcode test plan or scheme; in a test file, a retry marker or call (`@pytest.mark.flaky`, `@flaky`, Dart `@Retry(`, `jest.retryTimes(`), or a `retry:` / `retries:` option in a test runner call or in a `configure({…})` call; also a Dart `retry:` alone on its line, and a JavaScript or TypeScript line that starts with `{ retry:` or `{ retries:` (the same option passed to another call, or alone on a JavaScript line with no brace, does not count); in any file, an inline ignore marker of Semgrep, Gitleaks, jscpd, Fallow, ShellCheck, zizmor or Dart coverage (`coverage:ignore`); a line that is not a comment in `.gitleaksignore`, `.gitleaks.toml` or `.semgrepignore`. A test argument that skips or focuses (Dart `skip:` or `solo:` with any value but `false`; JavaScript or TypeScript `skip:` set to `true` or a text reason, or `only: true`) is flagged only in a test file. It also fails when it removes more `assert` or `expect(` lines from test files than it adds. Paths under `.hooks/`, `.agents/` and `.claude/` are exempt, lines that existed before the change are not flagged, and there is no allow-list.

Proof: check

## HE-UI-SOURCE

A change fails when its added lines in UI source hold a transition on every property (`transition` or `transition-property` with the value `all`, in a stylesheet or a style object, or the Tailwind class `transition-all`; a transition that names no property, such as `transition: 0.3s`, is not flagged) or one of these colour literals outside a theme or token file: a Tailwind arbitrary colour (a hex value, or an `rgb`, `hsl` or `oklch` function whose first argument is not `var(`); Dart `Color(0x`, `Color.from(`, `Color.fromARGB(`, `Color.fromRGBO(` or a `Colors.` name other than `transparent`; Swift `Color(red:`, `UIColor(red:` or `NSColor(red:`, also with an sRGB or Display P3 colour space before `red:`, or `#colorLiteral(`. No other colour form is flagged. UI source = a file with the suffix `.css`, `.scss`, `.less`, `.html`, `.vue`, `.svelte`, `.astro`, `.jsx`, `.tsx`, `.js`, `.ts`, `.dart` or `.swift`. A theme or token file = a file in a folder named `theme`, `token`, `color`, `colour` or `palette` (or the plural), a file whose name, without its last suffix, has one of those words as its last word (`appTheme.dart`, `brand_colors.ts`, not `colors.module.css`; for a name with `+`, any part between the `+` marks, as in `Color+Brand.swift`), or `tailwind.config.*`. Tests, generated files, comment lines and paths under `.hooks/`, `.agents/` and `.claude/` are exempt, and lines that existed before the change are not flagged. Nothing is flagged when the comparison is with the empty tree (for example a new repository's first commit).

Proof: check

## HE-NO-TEXT-WALLS

On-screen text comes in short blocks: at most 25 words and 3 sentences in a block, and at most 20 words in a sentence. A project may change these three numbers, and limit the checked folders with `paths` (globs ending in `/**`), in the `text_walls` setting of `hard-eng.gates.json`; no setting names one file. Dates, times, names, amounts and counts stand on their own labelled lines, not inside a sentence; review judges this rule, not the check. A stored free-text field, such as a body or a description, renders only inside the `UserContent` component, or in an element clamped to 2 lines or fewer inside a control that opens the full text. The check sees the clamp and a tap target; review judges that the tap opens the full text. `UserContent` takes expressions only, never literal text. The check reads TSX and JSX files and, for each Flutter package listed in `hard-eng.gates.json`, the Dart files under its `lib/` and its template ARB file. An expression or placeholder counts as one word. A change is judged only on blocks it adds or edits; it is never judged on older blocks it leaves alone. Script (also the `Script` component), style, code and pre elements and structured data (`@context` or `@type`) are not judged; tests, stories, generated files and paths under `.hooks/`, `.agents/` and `.claude/` are exempt. `python3 .hooks/hard-eng.py text-walls` lists every current hit; `text-walls --stdin` judges server-built strings, one JSON string per line, against the three limits. Server-built screen text has a test that pipes it through `text-walls --stdin`.

Proof: check

## HE-UNTRUSTED-JSON

In JavaScript and TypeScript, parsed JSON has the type `unknown` until code validates it. TypeScript configurations must load the Hard Eng declarations that set this type.

Proof: check

## HE-ADR-SCOPE

A changed, unsuperseded decision record names the paths it governs on an `Applies to:` line. A change that removes the last file under such a path must update or supersede the record.

Proof: check

## HE-OUTPUT-PLAIN

Agent replies, reports, PR texts and other text for people use plain, simplified technical English: one idea per sentence, active voice and common words. Reports state changes, proof and gaps. Text for agents (skills, AGENTS.md, briefs) keeps the Writing Great Skills style.

Proof: guidance

## HE-NO-FOREGROUND-POLL

An agent starts a long job in the background and reads the host's exit notice when the notice comes. While the job runs, the agent does other work that is ready, and it never ends its turn only to wait when other work is ready. No hook checks those two sentences. The agent never waits in a foreground sleep loop or a long foreground sleep, and in Claude Code a hook enforces that part. The hook denies a foreground shell command of the main session that holds a `while` or `until` loop and a sleep of at least 1 second, or sleeps that add up to at least 30 seconds. The hook ignores comments. It also ignores text in quotes and heredoc bodies, with three exceptions: the text counts when `sh`, `bash`, `zsh`, `python`, `perl`, `ruby`, `node` or `ssh` runs it, when `eval` runs quoted text, or when double-quoted text holds a command substitution. A subagent may wait in the foreground, because nothing watches its background job after its turn ends. Codex has no such hook: it returns a long command early and waits on that command's session, not on a sleep loop.

Proof: check

## HE-REAL-APP-PREVIEW

A proposed change to a screen that exists is shown as before and after captures of the real app, rendered in an isolated checkout, never as a hand-made mock. In Claude Code, a hook adds this note to every Artifact publish or quickstart call; the call always proceeds, because an artifact can be the right way to show other things. Codex has no Artifact tool.

Proof: check

## HE-HOT-PATH

Code must not build a constant regex inside a function, allocate an array of booleans, read whole rows or entities (`SELECT *`, an ORM query without a column list), add an in-process cache, await inside a loop, await independent calls in sequence, parse the same URL on each loop pass or use a JSON column. Every Semgrep `security` gate runs these rules on the whole repository, so old code fails too; only the change that installs Hard Eng can record them as debt. Each rule skips the shapes that need the slow form, such as calls on one database session, async streams, worker loops and loops that stop early; generated and vendored files are not scanned. When Semgrep can parse only part of a file, the gate scans the parsed part and prints the lines it skipped; every other scan error fails. `python3 .hooks/hard-eng.py hot-paths` lists the findings.

Proof: check

## HE-YAGNI

Add a file, dependency, abstraction, configuration or stored state only for a current agreed requirement that existing code or a direct command cannot meet.

Proof: guidance

## HE-PR-COMMITS

A PR holds at most 100 commits; GitHub can refuse to rebase a longer one. `ship` refuses a PR above the cap, and every `check` except `--quick` warns from 80. Above the cap, move the oldest finished commits to a branch and PR of their own. Merge it, then rebase the rest onto the base. Or join neighbour commits on the same base commit; `git diff <old head> <new head>` must then print nothing. Push the joined branch with `--force-with-lease`, and never pull the old commits back in. Only `ship` applies the cap: the Hard Eng update PR and a PR into a branch other than `shipping.base` never reach it.

Proof: check

## HE-SOURCE-COVERAGE

A plan may use material that the user gave, such as a call record, documents or sheets. Material from another party that the user pastes into the chat is a source too. The client is the party that the work is for, when that party is not the user. The `Sources:` line names each source. For each source that you read in full, write "read in full". If you cannot read a part, name that part in the entry of its source on the `Sources:` line. Also name it in Blockers and set `Handoff: Clarification`. After the user excludes the part, add "excluded by the user" to that entry. The `Sources + coverage` section has one row for each item that the sources name. An item is a person or role, team, screen, rule or requested outcome. Build the rows from the sources themselves, not from your notes or summaries of them.

Each row has one of four statuses. An `In scope` row copies exact words from one line of Acceptance + steps. That line names the item and proves its behavior. A `Later` row names who decided and the place of that decision. Write the word `client` or `user`, then a comma and the place. The name of the person can follow the word in brackets. For a `Later` row, the client decides, or the user when the work is for the user. A `Proposal` row holds a rule, a limit or an exclusion that no source decides. It is your idea, or a choice that the user makes for the work of a client. It needs a yes from the user or the client. After the yes, add who answered and the place of the answer. An `Open` row holds a question for the client or the user. Write each open question and each proposal with no answer in Blockers, in the words of its row, and ask the user. The plan is not Ready before the answers. A proposal with a yes stays a `Proposal` row. After a no, or after the answer to an open question, give the row the status that the answer decides.

An acceptance line built on a rule names, in its own text, the place in the sources that states the rule. If no source states it, the rule is a `Proposal` row, and the acceptance line names the item of that row. Never show your own rule as a rule of the client.

A second reader is required before Ready for more than one source, and for one large source such as a call record or a long document. Start a reader and give it only the sources and the plan, not your notes and not this conversation. It lists each item that the plan lacks, each row with a wrong status and each acceptance line whose rule no source states. Repair each one. Then write what the reader found on the `Reviewer:` line. If no reader can start, set `Reviewer: Pending`, write that in Blockers and set `Handoff: Clarification`. Do not write `N/A` then, and do not write a result that no reader gave.

The `Deliverables:` line names each thing that you make for the client outside the repository, such as a walkthrough video, or `None`. Do not make one while a row is `Open` or a `Proposal` has no answer.

Do not tell the user that the plan covers the sources while a row is `Open`, a `Proposal` has no answer or a required second reader has not run. The Participation rules of the [workflow](workflow.md#participation) say what follows when such a claim is later shown false.

When the request is the only source, write `Sources: N/A — reason`, with no `Reviewer:` line and no rows. The `Deliverables:` line can stay. The check reads only the form. It cannot prove that the rows are complete or true.

Proof: check

## HE-REAL-SERVICE-RUN

An outside service is a system that the project's code does not contain and that runs as a separate program. Examples are a hosted database, a payment provider, a message service and a public data API. The project's own hosted backend is an outside service. The code reaches the service over a network, or through a client program of that service, such as the command-line tool of a vendor. A tool that works only on local files, such as a compiler, a test runner or Git on a local repository, is not an outside service. A database server that the tests start on this machine is a test copy, not the real service: the real run uses the test or staging project of the deployed app. A fake of the service can hold the same wrong assumption as the code. Then each test passes and the real service fails.

A change can add or change a call to an outside service, or the code that builds its request or reads its reply. Before the plan is Complete, run the journey through each changed call one time against the real service. Do the run with a one-time command or by hand. Do not add it to the test suite. Run a write as the code runs it: the same order, and the same transaction if the code uses one. Compare the reply with the fake, for each field that the project's code reads. A field also counts as read when other code of the project reads it after the reply is passed on. If the project's code stores the reply whole, or sends it whole to a place outside the project, each field counts as read. Among the fields that are read, find the ones that the service sets by itself, the ones that are empty in the reply, and the ones that the fake has and the reply lacks. If the reply differs from the fake in a field that is read, correct the fake in the same change. A field that no code of the project reads can stay out of the fake.

The changed code can also handle a refusal that it tells apart by its error, such as a duplicate record or a missing record. Cause each such refusal one time in the real run, with test records only. Compare which call the service refuses, and its error, with the fake: a service can accept a wrong write and refuse later, when the transaction commits. If they differ, correct the fake in the same change. Do not cause a refusal that can harm other users of the account, such as a rate limit.

Use only a test account, a sandbox or a staging project that the user or the project's rules name for tests. A key that you find in a file is not an approval. Never run a changed call against a production account or production data. Send a write only to test records and test recipients. Run a payment only in the test mode of the provider. A call that only reads public data, such as a currency rate, needs no test account. After the run, delete the records that the run made, unless the user said to keep them.

The Verification section of the plan has one `Real service:` line, in one of three forms:

- `Required — <service>: <the calls that will run>` is valid until Complete.
- `Passed — <service>: <what ran and what the service returned>` records the run. Say there if the reply matched the fake in the fields that count as read. Name each refusal that you caused. Name each handled refusal that you did not cause, with the reason.
- `N/A — <reason>` is for a change that calls no outside service, or for a skip that the user decided, as below.

A run on a fake, a mock, a stub, a test double or an in-memory copy is not a real run. Such a run is not a reason for `N/A`. A run after the release is too late, so the line has no form for it. If you have no approved test account, keep the line `Required`, set the plan to Draft with that blocker and ask the user. Only the user can decide to skip the real run: write `N/A — user, <place of the decision>: <reason>`.

The check reads only the form of the line. It cannot prove that the run was done, or that the change calls no outside service. A small change has no plan, so it has no `Real service:` line. The rule still applies: run the journey through each changed call one time against the real service, and tell the user what it returned.

Proof: check

## HE-SEND-LIMIT

Unattended code is code that can run again when no person starts each run: a timed job, a queue worker, a webhook handler, an alarm, or a retry that goes on after the request of the person ends. A send is a message to a person (an email, an SMS, a chat message, a push notification, a page or a new issue) or a call that the provider bills or counts against a quota.

Unattended code that can send has a limit: a maximum number of sends for each period. A send that answers one outside event, such as one receipt for each payment, can use one send for each event ID instead of the maximum. This is allowed only when the ID stays the same each time the code runs again for the same event. The count lives outside the run, so the limit holds also when each run fails. An alarm sends one time for a fault, not one time for each failed run. It sends again only after the fault clears or after a set wait, and never more than the maximum for each period. For a change to unattended code or to what starts it, follow the failure path to each send, also to a send in code that the change did not touch.

Test data and staging data cause no real send through an account that a production app uses. They never reach a real person whom the user or the project's rules did not name as a test recipient. Use the capture mode or the sandbox mode of the provider, or an account that no production app shares. A message to a made-up address still counts against the limit of the account that sends it.

Proof: guidance
