import { spawnSync } from 'node:child_process';
import { join, resolve } from 'node:path';
import { readJson } from './media.mjs';

const work = resolve(process.argv[2]);
const only = process.argv[3] ?? '';
const first = process.argv[4] ?? '1';
const python = process.env.TTS_PYTHON;
const { exaggeration = 0.7, cfg = 0.4 } = readJson(work, 'storyboard.json').voice ?? {};
if (!python) throw new Error('Set TTS_PYTHON to the python of an environment with chatterbox-tts installed (references/setup.md).');
const code = `
import json, os, sys, torch, torchaudio as ta
from chatterbox.tts import ChatterboxTTS
work, only, first, exaggeration, cfg = sys.argv[1], set(filter(None, sys.argv[2].split(","))), int(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5])
device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
model = ChatterboxTTS.from_pretrained(device=device)
os.makedirs(f"{work}/vo/takes", exist_ok=True)
for key, text in json.load(open(f"{work}/lines.json")):
    if only and key not in only:
        continue
    for seed in range(first, first + 6):
        out = f"{work}/vo/takes/{key}_s{seed}.wav"
        if os.path.exists(out):
            continue
        torch.manual_seed(seed)
        wav = model.generate(text, exaggeration=exaggeration, cfg_weight=cfg)
        ta.save(out, wav, model.sr)
        print(key, seed, round(wav.shape[-1] / model.sr, 2), flush=True)
`;
const result = spawnSync(python, ['-c', code, work, only, first, String(exaggeration), String(cfg)], {
  stdio: 'inherit',
  env: { NUMBA_CACHE_DIR: join(work, 'vo/.numba'), ...process.env },
});
process.exit(result.status ?? 1);
