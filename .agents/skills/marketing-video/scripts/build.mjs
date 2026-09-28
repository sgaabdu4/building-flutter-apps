import { copyFileSync, cpSync, existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join, resolve } from 'node:path';
import { clipSource, readJson, seconds, size } from './media.mjs';

const work = resolve(process.argv[2]);
const board = readJson(work, 'storyboard.json');
const lines = Object.fromEntries(readJson(work, 'lines.json', []));
const best = readJson(work, 'vo/best.json', {});
const clipIndex = readJson(work, 'clips/index.json', {});
const manifest = readJson(work, 'shots/manifest.json', []);
const CARD = 1.35;
const used = new Set();
let estimated = 0;

function voice(key) {
  if (!(key in lines)) return null;
  if (used.has(key)) throw new Error(`voice line ${key} is used twice`);
  used.add(key);
  const file = best[key]?.[0];
  if (!file) estimated += 1;
  return {
    key,
    text: lines[key],
    file,
    dur: file ? seconds(join(work, file)) : lines[key].split(/\s+/).length / 2.6,
  };
}

function subtitles(v, at) {
  const parts = v.text.split(/(?<=[.!?])\s+/);
  const chars = parts.reduce((a, p) => a + p.length, 0);
  let t = at;
  return parts.map((text) => {
    const dur = (v.dur * text.length) / chars;
    t += dur;
    return { text, at: t - dur, dur };
  });
}

function target(file, label) {
  if (!label || typeof label === 'object') return label ?? null;
  const box = manifest.find((m) => m.file === file)?.targets.find((t) => t.label === label);
  if (!box) throw new Error(`no target "${label}" for ${file} in shots/manifest.json`);
  return box;
}

function shots(s, out, place) {
  let t = CARD;
  out.shots = [];
  for (const g of s.groups) {
    const v = voice(g.line);
    if (!v) throw new Error(`scene ${s.id}: no line ${g.line} in lines.json`);
    const base = g.shots.map((sh) => sh.dur ?? Math.max(2.6, 0.7 + (sh.click ? 1.3 : 0) + (sh.zoom ? 2.1 : 0)));
    const sum = base.reduce((a, b) => a + b, 0);
    const k = Math.max(1, (0.3 + v.dur + 0.55) / sum);
    place(v, t + 0.3);
    g.shots.forEach((sh, i) => {
      const file = join(work, 'shots', sh.file);
      if (!existsSync(file)) throw new Error(`shot ${sh.file} missing from shots/`);
      const dims = size(file);
      out.shots.push({
        src: `../shots/${sh.file}`,
        size: dims,
        frame: sh.frame ?? board.shotFrame ?? dims[0],
        at: t,
        dur: base[i] * k,
        caption: sh.caption,
        click: target(sh.file, sh.click),
        zoom: target(sh.file, sh.zoom),
      });
      t += base[i] * k;
    });
  }
  delete out.groups;
  return t + 0.35;
}

function clips(s) {
  let at = 1.15;
  return (s.clips ?? []).map((c, i) => {
    const x = clipIndex[`${s.id}-${i + 1}`];
    if (x?.source !== clipSource(board, c)) throw new Error(`clip ${s.id}-${i + 1} is missing or out of date: run clips.mjs`);
    const clip = {
      ...x,
      at,
      dur: x.dur + (c.hold || 0),
      src: `../clips/${s.id}-${i + 1}/`,
      caption: c.caption,
      speed: c.speed ?? 1,
    };
    at += clip.dur;
    return clip;
  });
}

let at = 0;
const scenes = [];
const placement = [];
for (const s of board.scenes) {
  const out = { ...s, start: at, subs: [] };
  const place = (v, t) => {
    out.subs.push(...subtitles(v, at + t));
    if (v.file) placement.push({ key: v.key, file: v.file, at: at + t });
  };
  if (s.groups) out.dur = shots(s, out, place);
  else {
    out.clips = clips(s);
    const clipTime = out.clips.length ? out.clips.at(-1).at + out.clips.at(-1).dur + 0.3 : 0;
    const v = voice(s.line ?? s.id);
    const voAt = s.voAt ?? 0.6;
    if (v) place(v, voAt);
    out.dur = Math.max(s.min ?? 3, v ? voAt + v.dur + (s.tail ?? 0.9) : 0, clipTime);
  }
  scenes.push(out);
  at += out.dur;
}
const unused = Object.keys(lines).filter((k) => !used.has(k));
if (unused.length) throw new Error(`lines not placed in any scene: ${unused.join(', ')}`);
placement.forEach((p, i) => {
  const next = placement[i + 1];
  const end = p.at + seconds(join(work, p.file));
  if (next && end > next.at - 0.1) throw new Error(`${p.key} runs into ${next.key} by ${(end - next.at).toFixed(2)}s`);
});

if (!existsSync(join(work, 'render/index.html')))
  cpSync(new URL('../assets/template/', import.meta.url), join(work, 'render'), { recursive: true });
mkdirSync(join(work, 'audio'), { recursive: true });
const require = createRequire(import.meta.url);
copyFileSync(require.resolve('gsap/dist/gsap.min.js'), join(work, 'render/gsap.min.js'));
const options = {
  subtitles: !!board.subtitles,
  transitions: board.transitions ?? 'cut',
  backdrop: !!board.backdrop,
};
writeFileSync(
  join(work, 'render/scenes.js'),
  `window.BRAND = ${JSON.stringify(board.brand ?? {})};\nwindow.OPTIONS = ${JSON.stringify(options)};\nwindow.SCENES = ${JSON.stringify(scenes, null, 1)};\n`,
);
writeFileSync(join(work, 'audio/placement.json'), JSON.stringify({ total: at, clips: placement }, null, 1));
console.log(
  'total',
  at.toFixed(2),
  's,',
  scenes.length,
  'scenes,',
  estimated ? `${estimated} lines timed by estimate (no take yet)` : 'every line has a take',
);
for (const s of scenes) console.log(s.id, s.type.padEnd(10), s.start.toFixed(1).padStart(6), s.dur.toFixed(1).padStart(5), s.label ?? '');
for (const s of scenes.filter((x) => !['app', 'flow', 'loop'].includes(x.type) && x.dur > 8)) {
  console.log(
    `CHECK scene ${s.id} holds one graphic for ${s.dur.toFixed(1)}s: shorten its line, or give it cards, bands or a flow to reveal`,
  );
}
