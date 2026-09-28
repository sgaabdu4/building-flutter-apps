# Voice

Load after the script is approved, or when a line's text changes.

1. `takes.mjs <work> 01` → send that one take to the human; wait for their verdict on voice, pace + name pronunciation.
2. All lines: six seeds each, whole line per generation, at `storyboard.voice` (default `{ "exaggeration": 0.7, "cfg": 0.4 }`). Change settings only after the human hears a sample.
3. `pick.mjs <work>` = Whisper per take → lowest word-error take per line (tie → take that fits its scene). `REGENERATE` = no clean take: check the wording, then `takes.mjs <work> <id> 7` (seeds 7–12) and pick again.
4. Names = plain spelling. Whisper keeps hearing a close variant of a correctly spoken name → `vo/heard-as.json` (`{"heard": "script"}`). Respell only after the human hears it wrong; sample 2–3 spellings first.
5. Liked take stays in `vo/takes/` (any `<id>_<label>.wav` competes); regenerate only changed lines.

| Mistake | Replacement |
| --- | --- |
| Lines split per sentence, higher exaggeration, "livelier" takes by pitch | Whole-line takes at approved settings; human judges by ear |
| Phonetic respelling by default | Plain spelling + `heard-as.json` |
