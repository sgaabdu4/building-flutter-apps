# Render, review + deliver

Load once scenes + lines exist, and after every revision.

## Build + render

- `build.mjs` times scenes from clips, shots + lines → `render/scenes.js` + `audio/placement.json`. Fails on a reused, unplaced or overlapping line, or a group line absent from `lines.json`; a scene whose own line is absent builds unvoiced.
- Options: `subtitles: true` (sentence subtitles), `transitions: "fade"` (0.4 s crossfade; default `"cut"`), `backdrop: true` (dot grid + slow blurred blobs in `tint`), `music.volume`.
- `brand` sets colours, fonts + `displayWeight` (default 800; lower for a lighter display face).
- Stills first: every graphic scene, chapter card, click + zoom. Fix layout before a full render.
- `render.mjs` = deterministic 30 fps from the paused GSAP timeline; fails on page error or missing asset.
- `mix.mjs` = looped music with crossfades, ducked under the voice, faded, linear gain to −14 LUFS (quiet music stays quiet).

## Review

On the exact file to deliver:

1. `audit.mjs` → open every contact sheet (1 frame/s). Look for sign-in or secret screens, spinners, cropped content, overlaps, typed logos, zooms cutting off the named thing.
2. Flat-frame runs = deliberate only (first ~0.25 s of a scene before its text reveals).
3. Stills at every click, zoom + graphic scene: nothing cut off, headings clear, logos crisp.
4. Mix transcript: every line present, in order, names recognisable. Timing → trust `audio/placement.json`; Whisper timestamps drift.
5. Report per artifact what was and was not checked; voice quality = the human's.

## Deliver

- Name `<Title> – product demo (draft N).mp4`; keep earlier drafts.
- Chat apps cap near 30 MB → also send `ffmpeg -i final.mp4 -vf scale=1280:-2 -c:v libx264 -crf 28 -preset slow -c:a aac -b:a 128k -movflags +faststart final-small.mp4`.
- Note = changes since the previous draft, checks run, what the human must confirm (music licence, claims).
