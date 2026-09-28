---
name: codebase-design
description: Design or review module ownership, public interfaces and abstractions; UI token/component ownership; or domain-driven models, bounded contexts and invariants. Use for structural decisions, not routine edits within an established owner.
---

# Codebase Design

Load the shared structure reference + matching conditional references.

```mermaid
flowchart LR
  S[references/structure.md] -->|UI tokens / components / composition| U[references/ui.md]
  S -->|Domain model / business rules / context boundaries| D[references/domain.md]
  click S "references/structure.md"
  click U "references/ui.md"
  click D "references/domain.md"
```
