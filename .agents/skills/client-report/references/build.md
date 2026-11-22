# Build the report

## Order and content

The starter holds each section in this order. Delete a section that has nothing to say, except "Where it stands", "What is live", "How it was checked", "Not checked" and "Everything left".

1. Title and date. "Where it stands" and "What finishes it": one or two lines each.
2. Box "What is needed before each next stage": name each stage, then numbered items written in full, what does not block it, and its limits.
3. Correction box, only when an earlier report was wrong.
4. "What is live": area, status label, what a person can do and where. Status words are coloured labels: `chip live` (Live), `chip off` (Not built), `chip wait` (Waiting for an answer).
5. Before and after for each change: pictures side by side ([pictures](pictures.md)).
6. "How it was checked": one line for each check that ran. Then "Not checked". Never claim blanket coverage.
7. "Everything left", by who acts: our team; questions for each client person; things only the client can give; client staff. Each item names its stage in words. Each question has "Why we ask" and "Until you answer, we ...".
8. Small gaps, later work, "When it is done", how to undo a release.

Words: about 80% ASD-STE100, sentences of 20 words or fewer, one fact in each sentence.

## Make the file

- First pick the report's own folder `<folder>`: `docs/client-report/<date>`, or `.hard-eng/client-report/<date>` when the audience check below says so. For another report on the same day, pick the first unused suffix (`-2`, `-3` and so on) in the chosen location so an approved folder is never overwritten. Use `<folder>` in every step below. Commit it only after the user approves it, so the last committed folder is the last approved one and the next report takes its "before" pictures from it. Never commit the PDF or the page images unless the user asks.
- Before committing a report or its pictures, find who can read the repository: `gh repo view --json visibility`, and `gh api --paginate repos/{owner}/{repo}/collaborators --jq '.[].login'` for the whole access list. If you cannot read the list, use the private folder. If its readers must not see the content, keep the folder in `.hard-eng/client-report/<date>` (same numbering) instead: it is never tracked. The unchanged starter holds no client data, so the check does not apply to it. A template with client branding gets the same check as a report.
- Copy `docs/client-report/template.html` to `<folder>/report.html`. Change text, rows and picture names only. Add no `style` attribute and no stylesheet link. A new look needs the user's approval and a new template commit.
- First report, no template yet: copy `assets/starter.html` to `docs/client-report/template.html` unchanged, and to the report path. Commit the template and the report only after the user approves the report; the audience check applies to the report and pictures, and to a template that is not the unchanged starter. The template keeps its placeholder text.
- Put the pictures next to `report.html`. Name each file as the report's `img src` says, and copy the saved picture to that name: `cp .hard-eng/browser/<name>-560.png <folder>/<img src name>`.
- Crop a picture: `uv run --no-project --with pillow python -I -c "import sys; from PIL import Image; Image.open(sys.argv[1]).crop(tuple(map(int, sys.argv[3:7]))).save(sys.argv[2])" in.png out.png left top right bottom`.
- Run the check always this way, so the Python version is the same everywhere: `cd "$(git rev-parse --show-toplevel)"`, then `uv run --no-project --python '>=3.12' python -I <skill>/scripts/check_report.py <folder>/report.html`. Outside a git checkout it refuses to run. It finds the template from the git top level. It refuses CSS that differs from the template, codes such as A1, leftover `[...]` text, and a report without the five kept sections. Fix the report, never the check.

## PDF and the page look

- Work from the project root, and write the PDF and page images to a temporary folder outside the repository: `OUT=$(mktemp -d); ROOT=$(git rev-parse --show-toplevel)`.
- Chrome prints the PDF. The path is for macOS; use the installed Chrome on another system:
  `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --no-pdf-header-footer --print-to-pdf="$OUT/report.pdf" "file://$ROOT/<folder>/report.html"`
- The template's print CSS uses block layout, `break-inside: avoid` on table cells, figures and boxes, and `@page` margins. Colour labels print because of `print-color-adjust: exact`.
- Render every page: `pdftoppm -r 90 -png "$OUT/report.pdf" "$OUT/page"` when it exists. Else `uv run --no-project --with pymupdf python -I -c "import sys,pymupdf; [p.get_pixmap(dpi=90).save(f'{sys.argv[2]}-{i+1}.png') for i,p in enumerate(pymupdf.open(sys.argv[1]))]" "$OUT/report.pdf" "$OUT/page"`.
- Open each page image. Look for blank gaps over a quarter of a page, cut-off pictures, text that cannot be read, and a heading alone at the foot of a page. Fix the report, print again, look again. Write down what you saw on each page.
