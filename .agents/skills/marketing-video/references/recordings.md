# Recordings route

Load when chapters are cut from product recordings. Run `clips.mjs` after every clip edit.

Clip fields in an `app` scene's `clips`: `video`, `from`/`to` (source s), `speed`, `caption`, optional `focus`, `hold`. Storyboard-level `blankCrop` + `blankInk` apply to every clip.

- Pick the moment that proves the step: form filled → confirmation. Skip navigation, spinners, empty states.
- Speed: typing + scrolling 3–4.5×; decisions + confirmations 1.6–2.5×. Speed tag shows from 3×.
- Chapter ends on a confirmation state; too short to read → `hold` ≈ 1.4 s.
- `blankCrop` = content region in source pixels, excluding persistent navigation → loading frames are dropped (`blankInk` default 0.012).
- `focus` = `{ "from", "to", "box": [x, y, w, h] }` in source s + pixels, last 1–3 s of a payoff state. Zoom capped 1.45, eased; rest plays full frame.
- Tall phone footage (width < 0.8 × height) plays large on the right; chapter name + captions sit in a left column. Landscape plays centred, full width.
