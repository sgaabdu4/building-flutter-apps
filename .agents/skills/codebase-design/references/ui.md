# UI ownership

Use the existing design system + actual consumers to locate the decision's owner.

| Decision | Closest owner |
| --- | --- |
| Reusable visual value | Existing token/theme |
| Basic control behavior | Primitive / atom |
| Repeated interaction or composition | Component / molecule / organism |
| Page arrangement | Layout / template / page |

- These are responsibilities, not required folders or extraction targets. Keep a true one-off constraint local; component extraction must remove repeated visual/interaction knowledge or establish a meaningful composed contract.
- Check existing variants before adding props or another component. Reuse styling without merging components whose behavior and semantics differ.
- Consolidate touched consumers at the chosen owner; avoid parallel editable values in documentation, theme and components. Follow the project's existing token mechanism rather than introducing generation or synchronization tooling.
- Exercise affected responsive, loading, empty, error, disabled + focus states as applicable. Verify semantic names/roles, keyboard behavior and visual output; component reuse alone proves none of these.
