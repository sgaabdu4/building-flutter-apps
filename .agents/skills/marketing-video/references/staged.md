# Staged screenshots route

Load when real data is private or no recordings exist.

Group shape in an `app` scene: `groups: [{ "line": "06-1", "shots": [{ "file", "caption", "click", "zoom", "dur" }] }]`.

## Capture

- Render the real app over made-up records at 2×: a widget/component test that paints the whole app (e.g. Flutter `RepaintBoundary.toImage(pixelRatio: 2)` at 1440×900), or Playwright screenshots of a local build seeded with fake data.
- Harness runs from a temporary copy; nothing stays in the repository.
- Before each capture: wait for that step's own content to be visible, then `document.fonts.ready` + every `img` `complete && naturalWidth > 0`. Client-side steps render after `networkidle`, and an empty image list passes the check → photos captured blank.
- Harness writes `shots/manifest.json` = `[{ "file", "targets": [{ "label", "x", "y", "w", "h" }] }]` in logical pixels. `shotFrame` = logical width (1440 for 2880-px PNGs).
- Contact sheet of every shot before building: menu open, right tab, the state the caption names.

## Motion

- `click` / `zoom` = a target label (`"click": "Sign in"`) or a box.
- `click` glides the cursor to the target, presses, ripples.
- `zoom` pushes in up to 2.2×, whole box in frame; box too large to gain 1.15× → no zoom.
- Shot ≥ 2.6 s (more with click or zoom); shots stretch so the group's line fits.
- Same `file` + new `zoom` = camera move, no cut.
