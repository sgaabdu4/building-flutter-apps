---
name: e2e
description: Prove real user journeys across browser, mobile, desktop, API and CLI surfaces using the project's existing test tools. Use for end-to-end verification, runtime UI review or requested visual proof.
---

# E2E

## Routes

Select by actual surface + explicit browser/device requirements. Reuse the project's runner, fixtures and fakes; no fake for an outside service → build one per [test design](../he/references/testing.md); missing runtime/connection → identify the needed capability before setup.

```mermaid
flowchart LR
  S{Surface} -->|Web UI| B[Existing browser E2E]
  B -->|Recorded proof needed| V[Product Walkthrough: recorded E2E]
  S -->|Polished web video requested| D[Product Walkthrough: video delivery]
  S -->|Flutter + Riverpod| F[building-flutter-apps skill]
  S -->|Other Flutter| I[Existing Flutter integration + device tools]
  F -->|Recorded proof needed| G[Recorded proof: references/flutter.md]
  I -->|Recorded proof needed| G
  S -->|Native / React Native / desktop| N[Platform + device runner]
  S -->|API / worker / CLI / pure Dart| A[Real request / event / command boundary]
  click V "../product-walkthrough-video/SKILL.md"
  click D "../product-walkthrough-video/SKILL.md"
  click G "references/flutter.md"
```

OS-owned dialogs → platform control beyond the app tree. Browser exploration → durable regressions in existing tests. API/CLI journeys need UI runtime only when the journey includes it.

## Drive a browser

- A browser step or capture that is not part of the project's own browser tests → `python3 .hooks/hard-eng.py browser`. It installs agent-browser itself, so install or run no other browser tool.
- `browser --session S <step>` runs one plain step. `browser capture` writes whole-page images at 390, 768 and 1280 px. It adds red boxes, hides emails and phone numbers, and writes a record of measured findings next to each image. `python3 .hooks/hard-eng.py look <image>...` opens each image in the other agent CLI ([challenge](../code-review/references/challenge.md)) and judges it against the Usability rules. If that CLI is missing, it uses a fresh session of this agent. Run it on the After images after the last commit. Put its block in the PR body before you run `challenge` and `ship --stage ready`. `browser signin` saves a sign-in for `--state`. It reads the username and password itself, from the environment or from the role's `env_file`. Never open, print or copy that file or those values.
- Every `browser` call needs `--session NAME`. Use one name for all the plain steps of one agent, and a separate name for each `capture` or `signin`. Never `close --all`. Close each session that you opened with plain steps.
- Before the first call, read [the browser command](references/browser.md): capture limits, sign-in roles, and Codex and Linux setup.

## Prove the journey

- Establish requested behavior, environment/build, actors, permissions and starting data. A reused server or app must run this checkout's current build. Exercise the real user path with stable semantic selectors and observable state waits.
- Choose the smallest cases covering the changed behavior and meaningful failures. Shared state needs independent writer/observer proof; persisted changes need source-of-truth readback. Cover denied/revoked access, retries or relaunch when the requirement depends on them.
- Keep cases isolated and repeatable using existing fixtures and cleanup. Do not substitute a mock, direct API mutation or test-only shortcut for the interaction being proved.
- Assert the visible result and relevant durable effects. A completed click, successful request, clean log or zero exit alone is insufficient. Investigate unexpected app/native/network errors and retries that only pass intermittently.
- On failure, preserve the reproduction and useful evidence; distinguish product, fixture, runner and capture defects. With fix authorization, correct the owner, rerun the original case and affected downstream cases, and retain a meaningful regression in the existing suite. Completion requires the corrected journey + affected checks to pass; otherwise report the exact blocker and remaining proof. Retries or weaker assertions do not resolve a defect.
- A user-reported defect reopens the affected journey's verification. Reproduce it, strengthen the assertion or review that missed it, and repeat the fix/retest loop; previous passing evidence cannot close the new report.

## Visual proof and completion

- Capture the smallest useful evidence set. Ordinary regression work does not require video. When screenshots or video are requested or needed, inspect the actual delivered media and confirm its subject, required steps and final state. PR evidence form (red ring, video) = [PR text](../he-ship/references/checks.md#pr-text).
- Recorded proof follows the selected route's owner; backend readback + repeatable journey assertions stay here and media checks alone cannot prove acceptance. Captures outside an owned pipeline → existing artifacts + direct inspection; do not invent a compatible report.
- Keep secrets and personal data out of artifacts. Show requested evidence to the user; treat test artifacts as local unless their inclusion as repository assets is authorized.
- Report tested surfaces, outcomes and exact gaps separately. Assertions, persisted state, deployment identity and visual evidence prove different things. An unavailable device, account, real-service run or unreviewed artifact remains unproven.
