---
name: product-walkthrough-video
description: Record and check real web journeys for E2E proof or polished walkthrough delivery. Reuse one recorder and mechanical/visual review pipeline; add MP4 conversion and final review for video delivery.
disable-model-invocation: true
---

# Product Walkthrough Video

Use the bundled recorder + review scripts for both routes; conversion belongs to video delivery. Recording changes pacing and may bridge reload paint: raw rendering or timing claims need separate evidence. [E2E](../e2e/SKILL.md#prove-the-journey) owns product assertions, durable-state proof + defect reopening.

Load matching README sections; commands run from this skill's directory.

```mermaid
flowchart LR
  T{Task} -->|Missing runtime dependencies| S[README: Setup]
  T -->|E2E recorded web proof| E[README: Recorded E2E]
  T -->|Polished video requested| V[README: Video delivery]
  T -->|Configure actions / fixtures| C[README: Configuration]
  click S "README.md#setup"
  click E "README.md#recorded-e2e"
  click V "README.md#video-delivery"
  click C "README.md#important-configuration"
```

Completion = selected route's [completion gate](README.md#completion-gate) on the exact reviewed artifact. Mechanical success without actual visual review remains incomplete.
