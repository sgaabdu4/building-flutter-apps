# Brief + script

Load for a new video, or when a script line changes.

## Brief

Collect before writing:

- audience + goal: buyers (marketing, default 2–2.5 min) or users learning the product (explainer, as long as every function needs, typically 3–4 min);
- where it plays; sound off likely → `subtitles: true`;
- brand owner's display font file, logos for every party, colours;
- approved design source for graphics (deck, site section);
- screens: recordings or a way to render the app over made-up data;
- product's own claims (deck, site, docs); the script says nothing they do not support;
- music: human picks/supplies the track, accepts its licence and says how loud ("very light" ≈ `music.volume` 0.12; default 0.42). Never lift a track from another project. Licence unknown → say so on delivery. Agent never accepts terms or ticks licence attestations.

## Scene types

| Type | Fields | Use |
| --- | --- | --- |
| `intro` | `title` + `kicker` (one brand), or none (logo `a` × `b`) | Opening |
| `statement` | `title`, optional `sub`, `cards` `[{tag, text}]`, `bands` | Problem, offer, why |
| `title` | `text`, optional `card: true` + `kicker` | Bridge or section title |
| `app` | `num`, `label`, optional `who`, `clips` or `groups` | One chapter per journey |
| `flow` | `text`, `nodes` `[{name, note, hero, logo, rows, badge}]` | How data or work moves (2–4 nodes) |
| `loop` | `text`, `nodes` (strings), `you` (index), `badge` | Repeating cycle |
| `collage` | `text`, `shots` (paths relative to the work folder) | Recap |
| `outro` | `title` + `kicker` or logos; `text`, `cta` | Close |

## Shape + wording

- Marketing = intro → problem → offer → bridge title → 6–9 chapters → collage → outro.
- Explainer = intro → why → flow → one chapter per function under section titles → loop or recap → outro.
- Short (≤ 90 s) = intro → flow → 3–4 chapters → outro; drop the problem statement and collage.
- Each scene adds something new: statement, flow and voice never list the same steps twice.
- Outro = brand + next step (`cta`). Gaps in what the demo shows go in the delivery note, never on screen.
- One line per non-app scene (key = `line` or scene id), ≤ 25 words. Clip chapter = one line; staged chapter = one line per group.
- Text-only scene ≤ ~8 s (`build.mjs` prints `CHECK` above). Longer thought → `cards`, `bands` or a `flow` revealing with the voice, or move it into a chapter.
- Open on something specific ("This is the Acme claims desk. It's where…"); "A and B, working together" = filler.
- No hype words (seamless, powerful, smarter, magic). Integrations + features named exactly as shipped. Captions name the action ("Take this claim").
- Voice, caption + screen say the same thing; change them together.
- Full script → human before any voice work.
