# [TODO: Effort]

Status: Draft

## Outcome + scope

[TODO: One sentence: result + non-goals.]

## Sources + coverage

Sources: [TODO: HE-SOURCE-COVERAGE. On this one line: each source the user gave, separated by `;`, each with "read in full", or the part not read + "excluded by the user". Request is the only source → `N/A — reason`, and delete the `Reviewer:` line and the row line below.]
Reviewer: [TODO: More than one source, or one large source → what a second reader found. It read only the sources + this plan, not your notes or this conversation. Else `N/A — reason`.]
Deliverables: [TODO: Each thing you make for the client outside the repository (video, document), or `None`. Make none while a row is `Open` or a `Proposal` has no answer.]

- [TODO: One line for each person or role, team, screen, rule and requested outcome that the sources name, no sub-bullets: `<item>: In scope — <exact words from the Acceptance + steps line that names and proves it>`, `<item>: Later — user|client, <place of the decision: call time, page or user reply>` (a name goes in brackets: `client (head teacher), call minute 18`), `<item>: Proposal — <your own rule, limit or exclusion>; yes — user|client, <place of the answer>` (no answer yet → no `; yes` part, and the same words go in Blockers as a question) or `<item>: Open — <question>` (the same words also in Blockers)]

## Repository context

Owners: [TODO: Relevant paths + decisive evidence links]
Same cause: [TODO: Fix → earlier fixes of this cause (plan/issue + helped, hurt, no effect or confounded) + every other place it can occur, searched + fixed; else N/A — reason]
Single source: [TODO: For each rule, value or type this change touches (constants, types, UI text, config, validation, queries): its one owner; the paths searched for other copies; each copy found, merged in this change. A copy you cannot merge in this change → Blockers; the plan cannot be Ready or Complete until that copy is merged. Else N/A — reason]

## Decisions + authorization

Blockers: [TODO: None or concrete unresolved decisions]
Handoff: [TODO: Clarification or Approval]
Authority: [TODO: Task mode + user's actual scope/approval; pending if absent]

## Acceptance + steps

- [ ] [TODO: Observable behavior. If it is built on a rule, add the place in the sources that states the rule, or the item of its `Proposal` row. → `path::test name` or requirement ID + expected result, or N/A — why no test can prove it; repeat only for distinct requirements.]

## Baseline + execution

Result: Pending
Evidence: [TODO: Starting command + actual result]
Execution: [TODO: Builder/reviewer + first slice; dependencies if parallel]

## Risks + recovery

[TODO: Material risk + recovery, or N/A — specific reason.]

## ux_reference

Result: Pending
Evidence: [TODO: Preview shown + inspected; nonvisual work replaces this section body with N/A — reason]
Surface: [TODO: Existing, New or Mock — actual route/design-system owners]
Before: [TODO: Markdown image; only Mock or no-prior-UI New may explain N/A — reason]
Proposed: [TODO: Markdown image of rendered proposal]
Capture: [TODO: Rendering/capture method + observed result]
Review: [TODO: Inspected flow/states/devices + direction]
Rules:

- [TODO: one line per Usability rule of references/ux.md, as `- <rule>: Pass|Fail|N/A — text`; fix every Fail before showing the design]

## Verification

Result: Pending
Evidence: [TODO: Actual commands/results + limits before Complete]
E2E: Required — [TODO: Journey + E2E test + expected proof; Complete needs Passed evidence or N/A — reason; deployment-only proof uses Delivery plus configured Deploy verifier]
Real service: Required — [TODO: <name of the service>: the changed calls that will run one time against the real service, per HE-REAL-SERVICE-RUN; Complete needs Passed — <service>: what ran + what it returned; no outside service called → N/A — reason; no approved test account → keep Required, set the plan to Draft + ask the user; only the user can approve a skip: N/A — user, <place of the decision>: <reason>]
Retro: [TODO: Required on Complete plans; write it at task end per HE Learn's Retro section, before setting Status: Complete]

[TODO: If shipping: Delivery target: PR, Merge or Deploy; Delivery: Pending — required remote proof.]
