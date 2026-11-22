# Pictures

Pictures use the [browser command](../../e2e/references/browser.md). Install or run no other browser tool.

- The live app address comes from the project's docs. If they do not name it, ask the user. Never guess it.
- A role with no saved sign-in, or a sign-in that fails: stop and ask the user, unless the user already asked for a test copy: then use one and say so in the report. Never choose a test copy yourself. Build the rest of the report and list the states in "Pictures with no live copy"; send nothing until the user answers, unless they already authorized a test copy.
- "Before" pictures: take them from the last approved report's folder (the newest approved folder, in `docs/client-report/<date>` or `.hard-eng/client-report/<date>`; a private folder counts when the user approved it), only if that report marked them as live. Never reuse a test copy as a live picture. With none, list the state under "Pictures with no live copy".
- Sign in once for each role: `python3 .hooks/hard-eng.py browser signin <role> --session NAME`. Never open, print or copy the sign-in values.
- Per picture, with one `--session` name and the role's `--state` on the first step: `set viewport 560 520`, `open <live url>`, `wait --load networkidle`. Press only tabs and rows. Never save, send, delete or submit.
- Mark each part the text names. Run one `eval` that adds a style to the page, then `wait 600`:
  `#part { outline: 4px solid #e00000 !important; outline-offset: 4px !important; transition: none !important }`
  Do not use `--ring`: it draws a 3 px box.
- Then `browser measure --session NAME --name <name>`. It hides emails and phone numbers and saves `.hard-eng/browser/<name>-<width>.png`. Look at each image: the command misses names and other personal data. Crop or leave out a picture that shows one.
- Width 560 keeps the text readable at half page width. `measure` saves the whole page, so open a page or state that is short, or scroll the part into view and crop the image. A picture taller than about 1,200 px at width 560 does not fit beside another on one printed page.
- Caption each picture with what the red line marks and its source: "live" or "test copy". Under "Pictures with no live copy", list each state with no live picture, with the reason.
