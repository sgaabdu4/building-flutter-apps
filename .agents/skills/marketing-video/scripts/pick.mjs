import { mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, join, relative, resolve } from 'node:path';
import { readJson, run, seconds } from './media.mjs';

const work = resolve(process.argv[2]);
const target = process.argv[3];
const bin = process.env.WHISPER_BIN ?? 'mlx_whisper';
const mlx = basename(bin).includes('mlx');

const flag = (name) => `--${mlx ? name : name.replaceAll('-', '_')}`;

function transcribe(files, extra = []) {
  const dir = mkdtempSync(join(tmpdir(), 'whisper-'));
  const model = mlx ? 'mlx-community/whisper-large-v3-turbo' : 'turbo';
  const flags = [
    flag('model'),
    model,
    flag('output-dir'),
    dir,
    flag('output-format'),
    'json',
    '--language',
    'en',
    '--verbose',
    'False',
    ...extra,
  ];
  for (const f of files) run(bin, [...flags, f], { stdio: ['ignore', 'ignore', 'pipe'] });
  const out = Object.fromEntries(
    files.map((f) => [f, JSON.parse(readFileSync(join(dir, `${basename(f).replace(/\.[^.]+$/, '')}.json`), 'utf8'))]),
  );
  rmSync(dir, { recursive: true, force: true });
  return out;
}

if (target) {
  const spans = readJson(work, 'audio/placement.json').clips.flatMap((c) =>
    [c.at, c.at + seconds(join(work, c.file)) + 0.3].map((t) => t.toFixed(2)),
  );
  const extra = [flag('clip-timestamps'), spans.join(','), flag('condition-on-previous-text'), 'False'];
  for (const seg of transcribe([resolve(target)], extra)[resolve(target)].segments) console.log(seg.text.trim());
  process.exit(0);
}

const heardAs = readJson(work, 'vo/heard-as.json', {});
const words = (s) =>
  s
    .toLowerCase()
    .replaceAll('-', '')
    .replace(/[^a-z0-9' ]/g, ' ')
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => heardAs[w] ?? w);
const distance = (a, b) => {
  let row = [...Array(b.length + 1).keys()];
  a.forEach((x, i) => {
    const next = [i + 1];
    b.forEach((y, j) => {
      next.push(Math.min(row[j + 1] + 1, next[j] + 1, row[j] + (x === y ? 0 : 1)));
    });
    row = next;
  });
  return row[b.length];
};

const lines = Object.fromEntries(readJson(work, 'lines.json'));
const scenes = Object.fromEntries(
  readJson(work, 'storyboard.json').scenes.flatMap((s) => (s.groups ? s.groups.map((g) => [g.line, s]) : [[s.line ?? s.id, s]])),
);
const cachePath = join(work, 'vo/heard.json');
const cache = readJson(work, 'vo/heard.json', {});
const takes = readdirSync(join(work, 'vo/takes'))
  .filter((f) => f.endsWith('.wav') && f.split('_')[0] in lines)
  .sort()
  .map((f) => join(work, 'vo/takes', f));
const fresh = takes.filter((f) => !(basename(f) in cache));
if (fresh.length) {
  for (const [f, result] of Object.entries(transcribe(fresh))) cache[basename(f)] = result.text.trim();
  writeFileSync(cachePath, JSON.stringify(cache, null, 1));
}
const best = {};
for (const file of takes) {
  const key = basename(file).split('_')[0];
  const scene = scenes[key];
  const fits = !scene || scene.type === 'app' || (scene.voAt ?? 0.6) + seconds(file) + (scene.tail ?? 0.9) <= (scene.min ?? 3);
  const heard = cache[basename(file)];
  const rank = [distance(words(heard), words(lines[key])), fits ? 0 : 1];
  console.log(basename(file), 'wer', rank[0], fits ? 'fits' : 'extends scene', '|', heard);
  if (!best[key] || rank[0] < best[key].rank[0] || (rank[0] === best[key].rank[0] && rank[1] < best[key].rank[1])) {
    best[key] = { file: relative(work, file), rank, heard };
  }
}
writeFileSync(
  join(work, 'vo/best.json'),
  JSON.stringify(Object.fromEntries(Object.entries(best).map(([k, v]) => [k, [v.file, v.rank[0], v.heard]])), null, 1),
);
for (const key of Object.keys(lines))
  console.log(
    'BEST',
    key,
    best[key] ? `${best[key].file} wer ${best[key].rank[0]}${best[key].rank[0] > 1 ? ' REGENERATE' : ''} | ${best[key].heard}` : 'MISSING',
  );
