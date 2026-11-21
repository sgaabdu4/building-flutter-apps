"""Measured screen limits for web pages: one table, one page script, one record per image."""

import hashlib
import json
import subprocess
from pathlib import Path

LIMITS = {
    "text_px": 11,
    "control_px": 44,
    "link_px": 24,
    "accent_colours": 2,
    "secondary_words": 20,
    "frame_ratio": 1.1,
}
PROOF_KINDS = {
    "Mistake-proof": ("judgement",),
    "Least effort": ("judgement",),
    "Observe": ("judgement",),
    "Undo": ("judgement",),
    "No clutter": ("measured", "judgement"),
    "Hierarchy": ("measured", "judgement"),
    "Alignment": ("measured", "judgement"),
    "Spacing": ("judgement",),
    "Design system": ("judgement",),
    "Messages": ("judgement",),
    "States": ("test",),
    "Time": ("test",),
    "Audit": ("test",),
    "Accessibility": ("measured",),
    "Widths": ("measured",),
    "Performance": ("test",),
}
DECORATION = '[aria-hidden="true"],[role=img]'
COLOUR_JS = (
    "const rgb = (() => { const cv = Object.assign(document.createElement('canvas'), { width: 1, height: 1 }).getContext('2d', { willReadFrequently: true }); "
    "return (c) => { cv.clearRect(0, 0, 1, 1); cv.fillStyle = 'rgba(0, 0, 0, 0)'; cv.fillStyle = c; cv.fillRect(0, 0, 1, 1); const d = cv.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; }; })(); "
)
DECORATED_JS = (
    "((el) => { const root = el.closest(DECORATION_JSON); if (!root) return false; "
    "const fill = (c) => { const v = rgb(c); return v.length >= 3 && (v.length < 4 || v[3] > 0.1); }; "
    "const lum = ([r, g, b]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); }; "
    "const covers = (s, r) => { const q = s.getBoundingClientRect(); return q.left <= r.left + 1 && q.top <= r.top + 1 && q.right >= r.right - 1 && q.bottom >= r.bottom - 1; }; "
    "const behind = (e) => { const r = e.getBoundingClientRect(); for (let n = e; n.parentElement; n = n.parentElement) { for (let s = n.previousElementSibling; s; s = s.previousElementSibling) { const c = getComputedStyle(s).backgroundColor; if (fill(c) && covers(s, r)) return c; } const c = getComputedStyle(n.parentElement).backgroundColor; if (fill(c)) return c; } return 'rgb(255, 255, 255)'; }; "
    "const apart = (c, e) => { if (!fill(c)) return false; const a = lum(rgb(c)), b = lum(rgb(behind(e))); return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) >= LIMITS.frame_ratio; }; "
    "const boxed = (e) => { const s = getComputedStyle(e); return e.namespaceURI === 'http://www.w3.org/2000/svg' "
    "|| apart(s.backgroundColor, e) || /\\d+px \\d+px [1-9]/.test(s.boxShadow) "
    "|| (parseFloat(s.borderTopWidth) >= 1 && s.borderTopStyle !== 'none' && apart(s.borderTopColor, e)); }; "
    "for (let n = el; n; n = n.parentElement) { if (boxed(n)) return true; if (n === root) return false; } return false; })"
)
AXE_TAGS = "wcag2a,wcag2aa,wcag21a,wcag21aa,wcag22aa"
AXE_NAMES = {
    "color-contrast": "contrast",
    "target-size": "link-size",
    "button-name": "label",
    "input-button-name": "label",
    "link-name": "label",
    "label": "label",
    "select-name": "label",
    "image-alt": "label",
}
MEASURE_SCRIPT = """(() => {
const LIMITS = LIMITS_JSON;
const found = [];
const shown = (el) => {
  const s = getComputedStyle(el);
  const b = el.getBoundingClientRect();
  const clipped = (s.clip && s.clip !== "auto") || /inset\\(\\s*(50|100)%|circle\\(\\s*0|polygon\\(\\s*0/.test(s.clipPath || "");
  const away = b.right + scrollX <= 0 || b.bottom + scrollY <= 0;
  return !clipped && !away && s.visibility !== "hidden" && s.display !== "none" && +s.opacity > 0 && b.width > 1 && b.height > 1;
};
const decorated = DECORATED_JSFN;
const visible = (el) => !decorated(el) && shown(el);
COLOUR_JSFN
const opaque = (c) => { const v = rgb(c); return v.length >= 3 && (v.length < 4 || v[3] > 0.1); };
const hue = ([r, g, b]) => {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  const l = (max + min) / 2, s = d === 0 ? 0 : d / (1 - Math.abs(2 * l - 1));
  if (s < 0.25 || l < 0.12 || l > 0.92) return null;
  const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return Math.round(((h * 60) + 360) % 360 / 30);
};
const controls = [...document.querySelectorAll("button,a[href],input:not([type=hidden]),select,textarea,[role=button],[role=link]")].filter(visible);
const name = (el) => (el.innerText || el.getAttribute("aria-label") || el.tagName).trim().slice(0, 30);
const ownText = (el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.nodeValue.trim()) || ["::before", "::after"].some((p) => /^["']./.test(getComputedStyle(el, p).content));
const texts = [...document.body.querySelectorAll("*")].filter((el) => ownText(el) && visible(el));
for (const el of texts) {
  const px = parseFloat(getComputedStyle(el).fontSize);
  if (px < LIMITS.text_px) found.push({ rule: "text-size", at: name(el), px });
}
for (const el of controls) {
  const b = el.getBoundingClientRect();
  const link = el.tagName === "A" || el.getAttribute("role") === "link";
  if (!link && (b.width < LIMITS.control_px || b.height < LIMITS.control_px)) {
    found.push({ rule: "tap-size", at: name(el), w: Math.round(b.width), h: Math.round(b.height) });
  }
}
const pseudoText = (el) => ["::before", "::after"].map((p) => {
  const c = getComputedStyle(el, p).content;
  return c && /^["']/.test(c) ? c.slice(1, -1) : "";
}).join("");
const textOf = (el) => {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let out = "";
  for (let n = walker.nextNode(); n; n = walker.nextNode()) if (n.parentElement && visible(n.parentElement)) out += n.nodeValue;
  for (const e of [el, ...el.querySelectorAll("*")]) if (visible(e)) out += pseudoText(e);
  return (el.value && el.tagName === "INPUT" ? el.value : out).trim();
};
const groups = new Map();
const fields = [...document.querySelectorAll("input:not([type=hidden]),select,textarea")].filter(visible).map((f) => f.getBoundingClientRect());
const inField = (el) => { const b = el.getBoundingClientRect(); return fields.some((f) => b.left < f.right && f.left < b.right && b.top < f.bottom && f.top < b.bottom); };
for (const el of controls.filter((c) => (c.tagName === "BUTTON" || c.getAttribute("role") === "button") && !inField(c))) {
  groups.set(el.parentElement, [...(groups.get(el.parentElement) || []), el]);
}
const colourOf = (el, s) => [ownText(el) ? s.color : "", s.backgroundColor, s.borderTopWidth !== "0px" ? s.borderTopColor : ""];
for (const [parent, members] of groups) {
  if (members.length > 1) {
    const behind = getComputedStyle(parent).backgroundColor;
    const filled = members.filter((m) => { const c = getComputedStyle(m).backgroundColor; return opaque(c) && c !== behind && hue(rgb(c)) !== null; });
    const fills = new Set(filled.map((m) => getComputedStyle(m).backgroundColor));
    if (fills.size > 1) found.push({ rule: "competing-buttons", at: filled.map(name).join(" + "), fills: fills.size });
  }
  if (members.length > 1) {
  const block = parent.parentElement;
  const colours = new Set();
  for (const el of [block, ...block.querySelectorAll("*")]) {
    if (!visible(el)) continue;
    for (const c of colourOf(el, getComputedStyle(el))) {
      if (c && opaque(c) && hue(rgb(c)) !== null) colours.add(rgb(c).slice(0, 3).join(","));
    }
  }
  if (colours.size > LIMITS.accent_colours) found.push({ rule: "accent-colours", at: name(block), colours: colours.size });
  }
  if ([...parent.children].some((c) => !members.includes(c) && visible(c) && textOf(c))) continue;
  if (parent.querySelector("input:not([type=hidden]),select,textarea")) continue;
  const block = parent.parentElement;
  const box = block.getBoundingClientRect();
  const pad = parseFloat(getComputedStyle(block).paddingLeft);
  const row = parent.getBoundingClientRect();
  const ps = getComputedStyle(parent);
  const framed = (opaque(ps.backgroundColor) && ps.backgroundColor !== getComputedStyle(block).backgroundColor) || (ps.borderTopWidth !== "0px" && ps.borderTopStyle !== "none");
  const left = framed ? row.left : Math.min(...members.map((m) => m.getBoundingClientRect().left));
  const stacked = (c) => { const r = c.getBoundingClientRect(); return r.bottom <= row.top + 1 || r.top >= row.bottom - 1; };
  const siblings = [...block.children].filter((c) => c !== parent && visible(c) && ownText(c) && stacked(c));
  const textLefts = siblings.map((c) => { const r = document.createRange(); r.selectNodeContents(c); return r.getBoundingClientRect().left; });
  const edges = new Set([left, ...textLefts].map((x) => Math.round(x - box.left - pad)));
  if (edges.size > 1) found.push({ rule: "shared-edge", at: name(block), edges: [...edges] });
}
const overlaps = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
const labelled = (el) => ["aria-label", "aria-labelledby", "title"].some((a) => (el.getAttribute(a) || "").trim()) || (el.textContent || "").trim() !== "";
const selectorOf = (el) => el.tagName.toLowerCase() + (el.getAttribute("name") ? `[name="${el.getAttribute("name")}"]` : "");
const BUTTONS = "button,[role=button],input[type=button],input[type=submit]";
const submitting = (el) => el.getAttribute("type") === "submit";
const isControl = (e) => e.matches(BUTTONS + ",a[href],[tabindex],[onclick],label[for]") || getComputedStyle(e).cursor === "pointer" || textOf(e) !== "";
for (const input of document.querySelectorAll("input[type=password]")) {
  if (!visible(input)) continue;
  const r = input.getBoundingClientRect();
  const scope = input.form || input.parentElement.parentElement || input.parentElement;
  const near = (br) => {
    const gap = Math.max(br.left - r.right, r.left - br.right);
    const centre = (br.top + br.bottom) / 2;
    return gap <= 24 && centre >= r.top - 4 && centre <= r.bottom + 4;
  };
  const candidates = [...scope.querySelectorAll("*")].filter((e) => e !== input && visible(e) && !e.contains(input) && !(input.labels && [...input.labels].some((l) => l.contains(e) && l.querySelector("input") === input)) && !submitting(e) && near(e.getBoundingClientRect()) && isControl(e));
  for (const b of candidates.filter((c) => !candidates.some((o) => o !== c && c.contains(o)))) {
    const text = textOf(b);
    const why = !overlaps(b.getBoundingClientRect(), r) ? "reveal control outside the field" : text ? "reveal control with text" : !labelled(b) ? "reveal control without a label" : "";
    if (why) found.push({ rule: "field-control", at: text || name(b), selector: selectorOf(input), why });
  }
}
const fieldText = (i) => [i.placeholder, i.getAttribute("aria-label"), i.title, i.name, i.id, ...[...(i.labels || [])].map((l) => l.innerText)].join(" ");
const searches = new Set([...document.querySelectorAll("input[type=search], [role=search] input:not([type=hidden],[type=submit],[type=button],[type=checkbox],[type=radio])")]);
for (const i of document.querySelectorAll("input")) if (["text", "search"].includes(i.type) && /search/i.test(fieldText(i))) searches.add(i);
for (const input of searches) {
  if (!visible(input)) continue;
  const r = input.getBoundingClientRect();
  const scope = input.form || input.closest("[role=search]") || input.parentElement;
  const drawn = (e) => ["::before", "::after"].some((p) => { const c = getComputedStyle(e, p).content; return c && c !== "none" && c !== "normal"; });
  const icon = getComputedStyle(input).backgroundImage !== "none" || drawn(input.parentElement) || drawn(scope) || [...scope.querySelectorAll("svg,img,i")].some((i) => {
    const b = i.getBoundingClientRect();
    return shown(i) && (b.left + b.right) / 2 > r.left && (b.left + b.right) / 2 < r.right && (b.top + b.bottom) / 2 > r.top && (b.top + b.bottom) / 2 < r.bottom;
  });
  const submits = [...scope.querySelectorAll("button:not([type=button],[type=reset]),input[type=submit]")].filter(visible);
  const labelledButtons = submits.filter((b) => textOf(b));
  if (icon && labelledButtons.length) found.push({ rule: "field-control", at: name(input), selector: selectorOf(input), why: "search text button beside a field with an icon" });
  if (!icon) found.push({ rule: "field-control", at: name(input), selector: selectorOf(input), why: "search field without an icon inside" });
}
const bodyPx = parseFloat(getComputedStyle(document.body).fontSize);
const SKIP = "a,button,label,legend,th,td,dt,summary,input,select,textarea,option,time,data,output,meter,nav,pre,code,[role=alert],[aria-live],h1,h2,h3,h4,h5,h6";
const chip = (el) => {
  const s = getComputedStyle(el);
  const filled = opaque(s.backgroundColor) && s.backgroundColor !== getComputedStyle(el.parentElement).backgroundColor;
  return filled || (s.borderTopWidth !== "0px" && s.borderTopStyle !== "none");
};
const lineOf = (el) => {
  const text = textOf(el);
  const words = text.split(/\\s+/).filter(Boolean);
  if (!text || !/\\p{L}/u.test(text) || el.closest(SKIP + ",li,footer,[role=contentinfo]") || chip(el) || /error|invalid|alert/i.test(el.className + " " + el.id)) return null;
  const valueLike = (t) => t.split(/\\s+/).filter(Boolean).length <= 3 && /[0-9]/.test(t);
  if (valueLike(text) || [...el.parentElement.children].some((c) => c !== el && !c.matches(HEADINGS) && ownText(c) && valueLike(textOf(c)))) return null;
  const s = getComputedStyle(el);
  const px = parseFloat(s.fontSize);
  return px < bodyPx - 0.5 ? { el, words: words.length, px } : null;
};
const HEADINGS = "h1,h2,h3,h4,h5,h6";
for (const heading of document.querySelectorAll(HEADINGS)) {
  if (!visible(heading)) continue;
  let top = heading;
  while (top.parentElement && !["BODY", "MAIN"].includes(top.parentElement.tagName) && top.parentElement.querySelectorAll(HEADINGS).length === 1) top = top.parentElement;
  const roots = [];
  if (top !== heading) roots.push(top);
  else for (let n = heading.nextElementSibling; n && !n.matches(HEADINGS) && !n.querySelector(HEADINGS); n = n.nextElementSibling) roots.push(n);
  const lines = roots.flatMap((root) => [root, ...root.querySelectorAll("*")]).filter((el) => ownText(el) && visible(el)).map(lineOf).filter(Boolean);
  if (lines.some((l) => l.px < LIMITS.text_px)) continue;
  if (lines.length > 1) found.push({ rule: "extra-text", at: name(heading), secondary_lines: lines.length });
  for (const line of lines) if (line.words > LIMITS.secondary_words) found.push({ rule: "extra-text", at: name(heading), words: line.words });
}
if (document.documentElement.scrollWidth > innerWidth + 1) {
  found.push({ rule: "overflow", at: "page", scrollWidth: document.documentElement.scrollWidth, width: innerWidth });
}
return JSON.stringify(found);
})()"""


def measure_script() -> str:
    script = MEASURE_SCRIPT.replace("LIMITS_JSON", json.dumps(LIMITS))
    script = script.replace("COLOUR_JSFN", COLOUR_JS)
    script = script.replace("DECORATED_JSFN", DECORATED_JS)
    return script.replace("DECORATION_JSON", json.dumps(DECORATION))


def decoration_script(selectors: list[str]) -> str:
    decorated = DECORATED_JS.replace("DECORATION_JSON", json.dumps(DECORATION))
    return (
        f"(() => {{ const LIMITS = {json.dumps(LIMITS)}; {COLOUR_JS}const decorated = {decorated}; "
        f"return JSON.stringify({json.dumps(selectors)}.map((s) => {{ try {{ "
        "const el = document.querySelector(s); return Boolean(el && decorated(el)); "
        "} catch { return false; } })); })()"
    )


def axe_findings(output: str) -> list[dict[str, object]]:
    """The violations of an axe run, one finding for each element."""
    data = json.loads(output[output.index("{") :])["data"]
    return [
        {
            "rule": AXE_NAMES.get(item["id"], item["id"]),
            "at": ", ".join(node["target"][-1:]),
        }
        for item in data["violations"]
        for node in item["nodes"]
    ]


def checkout_state(root: Path) -> dict[str, object]:
    """The commit a capture was taken from and whether the checkout had uncommitted changes."""

    def git(*args: str) -> str:
        done = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=False
        )
        return done.stdout.strip() if done.returncode == 0 else ""

    return {
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
    }


def write_record(
    root: Path,
    image: Path,
    width: int,
    findings: list[dict[str, object]],
    route: str = "",
) -> Path:
    record = image.with_suffix(".json")
    record.write_text(
        json.dumps(
            {
                "image": image.name,
                "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                "width": width,
                "findings": findings,
                "route": route,
                **checkout_state(root),
            },
            indent=2,
        )
        + "\n"
    )
    return record
