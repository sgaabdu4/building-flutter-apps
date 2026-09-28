import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith('--')) continue;
    const key = token.slice(2);
    const next = argv[index + 1];
    args[key] = next && !next.startsWith('--') ? next : true;
    if (args[key] !== true) index += 1;
  }
  return args;
}

function required(args, key) {
  if (!args[key] || args[key] === true) {
    throw new Error(`Missing --${key}`);
  }
  return String(args[key]);
}

const args = parseArgs(process.argv.slice(2));
const repo = path.resolve(required(args, 'repo'));
const output = path.resolve(args.out || path.join(repo, '.walkthrough'));
const baseUrl = String(args['base-url'] || 'http://127.0.0.1:3000/');
const name = String(args.name || 'repository-walkthrough');
const baseOrigin = new URL(baseUrl).origin;
const skillRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

await mkdir(output, { recursive: true });

const config = {
  name,
  repository: repo,
  baseUrl,
  strictE2E: true,
  readySelector: 'main',
  allowedOrigins: [baseOrigin],
  blockExternalRequests: true,
  blockEventStreams: false,
  acceptDownloads: false,
  viewport: { width: 1440, height: 1000 },
  reducedMotion: 'reduce',
  videoQuality: 90,
  assetReadyTimeoutMs: 2500,
  visualStabilityMs: 300,
  visualStabilityTimeoutMs: 5000,
  scrollDurationMs: 900,
  dragDurationMs: 900,
  scrollStableMs: 240,
  scrollSettleTimeoutMs: 3000,
  captureStepScreenshots: true,
  pointer: {
    enabled: true,
    color: '#ff3b30',
    size: 20,
    rippleSize: 38,
    rippleMs: 520,
    moveDurationMs: 900,
    moveHoldMs: 320,
  },
  settleMs: 0,
  openingHoldMs: 1600,
  stepHoldMs: 1400,
  finalHoldMs: 1800,
  minReadableHoldMs: 1200,
  maxStaticMs: 7000,
  pointerMissingFailMs: 160,
  openingStableMs: 800,
  steps: [
    {
      action: 'goto',
      label: 'Open the application',
      url: '/',
      holdMs: 1600,
    },
    {
      action: 'assertVisible',
      label: 'Confirm the opening state',
      target: {
        selector: 'main',
      },
      holdMs: 1400,
    },
    {
      action: 'pause',
      label: 'Hold on the completed journey',
      ms: 1800,
    },
  ],
};

await writeFile(path.join(output, 'walkthrough.config.json'), `${JSON.stringify(config, null, 2)}\n`, 'utf8');
await writeFile(
  path.join(output, 'README.md'),
  `# ${name}\n\n1. Start the repository application at ${baseUrl}.\n2. Replace \`readySelector\` and the example steps with the real start-to-finish journey. Keep the first \`goto\`, a product-specific ready selector, readable holds, smooth scrolls, and a final assertion.\n3. Record with Playwright's post-readiness screencast:\n\n\`\`\`bash\nnode ${path.join(skillRoot, 'scripts/run-walkthrough.mjs')} --config ${path.join(output, 'walkthrough.config.json')}\n\`\`\`\n\n4. Run \`review-video.mjs\` without approval. Watch the complete video at 1x, inspect the opening sheet, contact sheets, and every step checkpoint, then fix and rerun any defect.\n5. Approve only a clean rerun with \`--approve --reviewer <name> --notes "<what was inspected>"\`.\n6. Recorded E2E ends with the accepted WebM and reports. Only for video delivery, convert the approved source with \`convert-mp4.mjs --review <passed-review.json>\`, then run the same full review against the final MP4.\n`,
  'utf8',
);

console.log(`Created ${path.join(output, 'walkthrough.config.json')}`);
