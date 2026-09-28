---
name: he
description: Apply Hard Eng's planning, project context, verification and gate-adaptation guidance when implementing or reviewing code in an installed project.
---

# Hard Eng

Select the matching route automatically from the task and current stage; no explicit skill invocation is required. Load only matching routes and continue to the next authorized stage when its prerequisites pass.

```mermaid
flowchart LR
  T{Task} -->|Plan new work / changed scope| P[../he-plan/SKILL.md]
  T -->|Implement / fix / resume build| B[../he-build/SKILL.md]
  T -->|Ship / PR / merge / deploy| S[../he-ship/SKILL.md]
  T -->|Repeated failures / lasting decisions| L[../he-learn/SKILL.md]
  T -->|Task context / review| W[references/workflow.md]
  T -->|Adapt / repair checks| G[references/gates.md]
  T -->|Bulk / async / performance| E[references/efficiency.md]
  T -->|Design / change / review tests| Q[references/testing.md]
  click W "references/workflow.md"
  click P "../he-plan/SKILL.md"
  click B "../he-build/SKILL.md"
  click S "../he-ship/SKILL.md"
  click L "../he-learn/SKILL.md"
  click G "references/gates.md"
  click E "references/efficiency.md"
  click Q "references/testing.md"
```
