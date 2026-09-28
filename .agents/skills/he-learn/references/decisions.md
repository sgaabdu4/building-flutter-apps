# Decisions + steering

Load when a user or authorized workflow makes, changes or questions a lasting project decision. Writing style = [Writing Great Skills](../../writing-great-skills/SKILL.md): minimal prose, explicit meaning, one owner, conditional detail only when needed.

- Durable = a choice that constrains future architecture, interfaces, data, checks or working practice; retain its reason + material consequence. Routine progress, tentative ideas and one-task sequencing stay in the existing plan. Do not turn every user message into an ADR.
- Location = `docs/adr/NNNN-short-name.md`; inspect existing records and preserve their numbering/conventions. Default to the next unused four-digit number. No separate index is needed while filenames + relevant links suffice. Product-wide current facts still belong in PRODUCT/DESIGN or their existing owner.
- Authority = distinguish the user's accepted choice from a proposal, inferred preference or unverified assumption. A request to investigate is not acceptance. Existing authorization covers routine implementation choices; a record adds no new authority.
- Capture = inspect source evidence, compare existing decisions, then write the smallest record below. Include only alternatives that explain the choice. Link the source decision/task and applicable proof; pending verification stays pending. Never copy secrets or raw transcripts.
- Change = fix factual errors in place; a materially different accepted decision gets a new ADR and marks the previous record Superseded with a link. Preserve why the earlier choice existed. Uncertain drift → investigate; do not silently rewrite an active requirement to match possibly broken code.
- Use = read the relevant Accepted record at the next affected planning/design/review step. Verify referenced paths + actual scope; an obsolete version or different project may invalidate applicability. Briefly record that use in the existing task evidence when validating a new learning route.

```markdown
# NNNN — Decision

Status: Proposed | Accepted | Superseded by [NNNN](NNNN-name.md)

## Context
Constraint or evidence that made the choice necessary.

## Decision
The choice, its scope and material exception.

## Consequences
Benefit, tradeoff and any required follow-up.

## Evidence
Decision source + actual verification, or the precise pending check.
```

Select one Status. Use short paragraphs or parallel bullets; use a small Mermaid diagram only when it clarifies a real flow or relationship. Do not fill space with generic rationale or certify implementation from an Accepted decision.
