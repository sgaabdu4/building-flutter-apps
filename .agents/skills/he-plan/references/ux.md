# Repository-grounded UX reference

Apply to visible changes; preview only the flow and states needed for the decision.

- Grounding = inspect the actual website/screen, affected flow and token/theme/component owners in `DESIGN.md` + production code. A dashboard shell alone cannot support decisions about unseen workflows. Missing relevant context → expose the gap; never invent a baseline.
- Choose the cheapest useful preview below. Planning may create isolated mocks; production implementation still waits for Ready + authorization. No mandatory video, live-app build or extra visual-testing platform for a mock.

| Surface | Preview + baseline |
| --- | --- |
| `Mock — <actual design-system/component owners>` | Embed proposed changes into the existing website reference, or make a lightweight HTML/image mock using its real design system. Preserve relevant surrounding UI and show decision-bearing states. Label it a mock. Link an inspected baseline when available; otherwise `Before: N/A — <why this mock has no app capture>`. |
| `Existing — <actual route/screen + source owner>` | Capture the unmodified app and render the proposal through that screen in an isolated checkout. Preserve its UI tree; assert route/state before capture. A reconstructed page is a Mock, not an actual-app capture. |
| `New — <new screen + source owner>` | Use repository components/tokens and the nearest existing flow as baseline. Only an app with no prior UI may use `Before: N/A — <reason>`; label assumptions from the brief/assets. |

- Render + inspect = use existing browser/device tools; use [E2E](../../e2e/SKILL.md) for runtime visual inspection. For bitmap concepts/assets, use the available imagegen skill; HTML/CSS or existing vectors are sufficient otherwise. Inspect the rendered proposal at affected sizes/states and show it in the conversation. A path, unopened image or explanatory panel is not a shown workflow. Reuse inspected evidence while it still matches the proposal.
- Record = `Result` + `Evidence`, then `Surface`, `Before`, `Proposed`, `Capture`, `Review` in the existing plan. Proposed is a Markdown image. Capture names the actual rendering/capture method + observed result; Review names the inspected states/devices, comparison and direction. `Result: Passed` means the preview was rendered, inspected and shown; it does not record user approval. Before an approval handoff the direction may await the user's decision; Ready requires that decision settled within the task mode.
- Keep preview source isolated and artifacts in existing ignored/output storage. Link them without new receipts/hashes. Tracked non-Markdown files remain implementation inputs to the completion gate. Nonvisual work uses a concrete N/A reason; unavailable required proof remains blocked.
- User changes direction → update, inspect and show the matching mock/capture. For build verification, compare the actual app with the accepted reference and run the affected journey. A mock does not establish production fidelity or runtime success; recover the real before capture before implementation for PR evidence.

The gate validates declared fields, not image authenticity, design quality or whether the agent actually showed the proposal. Those require inspection; a Passed label cannot replace them.
