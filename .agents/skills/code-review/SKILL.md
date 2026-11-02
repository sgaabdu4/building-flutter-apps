---
name: code-review
description: Review PR, branch, commit or working-tree changes for concrete defects and fidelity to intended behavior. Also use when explicitly asked to independently challenge a prepared plan, diagnosis or verification claim.
---

# Code Review

Load the review method; load the independent-challenge branch only when requested.

```mermaid
flowchart LR
  R[references/review.md] -->|Independent / adversarial review requested| C[references/challenge.md]
  R -->|Diff touches sign-in, permissions, API keys, payments, uploads or personal data| S[Security Review]
  click R "references/review.md"
  click C "references/challenge.md"
  click S "../security-review/SKILL.md"
```
