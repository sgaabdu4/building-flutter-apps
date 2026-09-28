const supportedActions = new Set([
  'assertText',
  'assertUrl',
  'assertVisible',
  'back',
  'click',
  'drag',
  'forward',
  'goto',
  'hover',
  'pause',
  'press',
  'reload',
  'screenshot',
  'scroll',
  'select',
  'type',
  'typeKeys',
  'waitForSelector',
  'waitForText',
  'waitForUrl',
]);

const sensitivePatterns = [
  { type: 'GitHub token', pattern: /\bgh[pousr]_[A-Za-z0-9_]{20,}\b/ },
  { type: 'GitHub fine-grained token', pattern: /\bgithub_pat_[A-Za-z0-9_]{20,}\b/ },
  { type: 'AWS access key', pattern: /\bAKIA[0-9A-Z]{16}\b/ },
  { type: 'Bearer token', pattern: /\bBearer\s+[A-Za-z0-9._~+/-]{20,}/i },
  { type: 'Private key', pattern: /-----BEGIN (?:RSA|EC|OPENSSH|PGP) PRIVATE KEY-----/ },
  {
    type: 'Secret-like assignment',
    pattern: /(?:token|secret|password|passwd|api[_-]?key)\s*[=:]\s*[^&\s]{8,}/i,
  },
];

const supportedModifiers = new Set(['Alt', 'Control', 'Meta', 'Shift']);
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

function safeSlug(value) {
  return (
    String(value || 'walkthrough')
      .replace(/[^a-z0-9._-]+/gi, '-')
      .replace(/^-+|-+$/g, '') || 'walkthrough'
  );
}

function finiteNumber(value, fallback, minimum = 0, maximum = Number.POSITIVE_INFINITY) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(maximum, Math.max(minimum, parsed));
}

function resolveUrl(baseUrl, value) {
  return new URL(String(value || '/'), baseUrl).toString();
}

function safeUrl(value) {
  try {
    const parsed = new URL(value);
    if (parsed.protocol === 'about:') return `[${parsed.href}]`;
    return `${parsed.origin}${parsed.pathname}`;
  } catch {
    return '[non-http-url]';
  }
}

function redactedMessage(value) {
  let text = String(value || '')
    .replace(/\s+/g, ' ')
    .trim();
  for (const { type, pattern } of sensitivePatterns) {
    const flags = pattern.flags.includes('g') ? pattern.flags : `${pattern.flags}g`;
    text = text.replace(new RegExp(pattern.source, flags), `[redacted ${type}]`);
  }
  return text.length > 240 ? `${text.slice(0, 237)}...` : text;
}

function findSensitive(value) {
  const text = String(value || '');
  return sensitivePatterns.filter(({ pattern }) => pattern.test(text)).map(({ type }) => type);
}

function includesAllowedSubstring(value, entries) {
  const text = String(value || '');
  return Array.isArray(entries) && entries.some((entry) => text.includes(String(entry)));
}

function isAllowedHttpResponse(url, status, entries) {
  return (
    Array.isArray(entries) &&
    entries.some(
      (entry) =>
        Number(entry?.status) === status && String(entry?.urlIncludes || '').length > 0 && String(url).includes(String(entry.urlIncludes)),
    )
  );
}

function hasTargetDescriptor(target) {
  return Boolean(target && (target.role || target.label || target.placeholder || target.testId || target.text || target.selector));
}

function getModifiers(step) {
  if (step.modifiers === undefined) return [];
  if (!Array.isArray(step.modifiers)) throw new Error(`Step "${step.label || step.action}" modifiers must be an array`);
  const modifiers = step.modifiers.map(String);
  for (const modifier of modifiers) {
    if (!supportedModifiers.has(modifier)) {
      throw new Error(`Step "${step.label || step.action}" uses unsupported modifier "${modifier}"`);
    }
  }
  return modifiers;
}

function validatePointSpec(point, label, problems) {
  if (point === undefined) return;
  if (!point || typeof point !== 'object' || Array.isArray(point)) {
    problems.push(`${label} must be an object`);
    return;
  }
  const hasRatio = point.xRatio !== undefined || point.yRatio !== undefined;
  const hasOffset = point.x !== undefined || point.y !== undefined;
  if (hasRatio && hasOffset) {
    problems.push(`${label} must use ratios or pixel offsets, not both`);
    return;
  }
  if (!hasRatio && !hasOffset) {
    problems.push(`${label} needs xRatio/yRatio or x/y`);
    return;
  }
  const first = Number(hasRatio ? point.xRatio : point.x);
  const second = Number(hasRatio ? point.yRatio : point.y);
  if (!Number.isFinite(first) || !Number.isFinite(second)) {
    problems.push(`${label} coordinates must be finite numbers`);
    return;
  }
  if (hasRatio && (first < 0 || first > 1 || second < 0 || second > 1)) {
    problems.push(`${label} ratios must be between 0 and 1`);
  }
  if (hasOffset && (first < 0 || second < 0)) {
    problems.push(`${label} pixel offsets must be non-negative`);
  }
}

function getTarget(page, step) {
  const target = step.target || {};
  if (target.role) return page.getByRole(target.role, { name: target.name, exact: Boolean(target.exact) });
  if (target.label) return page.getByLabel(target.label, { exact: Boolean(target.exact) });
  if (target.placeholder) return page.getByPlaceholder(target.placeholder, { exact: Boolean(target.exact) });
  if (target.testId) return page.getByTestId(target.testId);
  if (target.text) return page.getByText(target.text, { exact: Boolean(target.exact) });
  if (target.selector) return page.locator(target.selector);
  if (step.selector) return page.locator(step.selector);
  throw new Error(`Step "${step.label || step.action}" needs a target`);
}

function validateConfig(config, baseUrl) {
  const problems = [];
  const strict = config.strictE2E !== false;
  const minReadableHoldMs = finiteNumber(config.minReadableHoldMs, 900);
  const pointerEnabled = config.pointer !== false && config.pointer?.enabled !== false;
  const pointerSettleMs = finiteNumber(config.pointer?.moveHoldMs, 320);
  try {
    new URL(baseUrl);
  } catch {
    problems.push('baseUrl must be a valid URL');
  }
  if (!Array.isArray(config.steps) || config.steps.length === 0) {
    problems.push('steps must contain the complete user journey');
    return problems;
  }
  if (strict && config.steps[0]?.action !== 'goto') {
    problems.push('strictE2E requires the first step to be a goto start state');
  }
  const readySelector = String(config.readySelector || '').trim();
  if (!readySelector) {
    problems.push('readySelector is required');
  } else if (strict && /^(?:html|body|\*)$/i.test(readySelector)) {
    problems.push('strictE2E requires a product-specific readySelector, not html/body/*');
  }
  if (strict && config.captureStepScreenshots === false) {
    problems.push('strictE2E requires one checkpoint screenshot per step');
  }
  if (strict && config.blockExternalRequests !== true) {
    problems.push('strictE2E requires blockExternalRequests: true');
  }
  if (config.allowedHttpResponses !== undefined) {
    if (!Array.isArray(config.allowedHttpResponses)) {
      problems.push('allowedHttpResponses must be an array');
    } else {
      for (const [index, entry] of config.allowedHttpResponses.entries()) {
        const status = Number(entry?.status);
        if (!Number.isInteger(status) || status < 400 || status > 599) {
          problems.push(`allowedHttpResponses entry ${index + 1} needs an integer status from 400 to 599`);
        }
        if (!String(entry?.urlIncludes || '').trim()) {
          problems.push(`allowedHttpResponses entry ${index + 1} needs a non-empty urlIncludes value`);
        }
      }
    }
  }
  for (const [index, step] of config.steps.entries()) {
    const prefix = `step ${index + 1}`;
    if (!supportedActions.has(step.action)) problems.push(`${prefix} uses unsupported action "${step.action}"`);
    if (!String(step.label || '').trim()) problems.push(`${prefix} needs a descriptive label`);
    if (step.action !== 'pause') {
      const holdMs = finiteNumber(step.holdMs ?? config.stepHoldMs, 0);
      if (strict && holdMs < minReadableHoldMs) {
        problems.push(`${prefix} "${step.label || step.action}" holds for ${holdMs}ms; minimum is ${minReadableHoldMs}ms`);
      }
    }
    if (['click', 'drag', 'hover', 'select', 'type', 'waitForSelector', 'assertVisible'].includes(step.action)) {
      if (!step.target && !step.selector) problems.push(`${prefix} "${step.label || step.action}" needs a stable target`);
    }
    if (strict && pointerEnabled && ['click', 'select', 'type'].includes(step.action) && pointerSettleMs < 150) {
      problems.push(`${prefix} pointer settle time must be at least 150ms`);
    }
    if (step.action === 'press') {
      const hasTarget = Boolean(step.target || step.selector);
      if (!String(step.key || '').trim()) problems.push(`${prefix} press needs a key`);
      if (step.scope !== undefined && step.scope !== 'global') {
        problems.push(`${prefix} press scope must be "global" when provided`);
      }
      if (step.scope === 'global' && hasTarget) {
        problems.push(`${prefix} global press must not declare a target`);
      }
      if (step.scope !== 'global' && !hasTarget) {
        problems.push(`${prefix} press needs a stable target or scope "global"`);
      }
      const cueLeadMs = finiteNumber(step.keyboardCueLeadMs ?? config.keyboardCueLeadMs, 320);
      const cueHoldMs = finiteNumber(step.keyboardCueHoldMs ?? config.keyboardCueHoldMs, 420);
      if (strict && cueLeadMs < 200) problems.push(`${prefix} keyboard cue lead must be at least 200ms`);
      if (strict && cueHoldMs < 250) problems.push(`${prefix} keyboard cue hold must be at least 250ms`);
    }
    if (['click', 'hover'].includes(step.action)) {
      validatePointSpec(step.position, `${prefix} position`, problems);
    }
    if (step.modifiers !== undefined) {
      try {
        getModifiers(step);
      } catch (error) {
        problems.push(`${prefix} ${error.message}`);
      }
    }
    if (step.preserveVisualDuringReload === true && step.action !== 'reload') {
      problems.push(`${prefix} preserveVisualDuringReload is only valid for reload steps`);
    }
    if (step.action === 'typeKeys' && step.text === undefined && !step.textFromEnv) {
      problems.push(`${prefix} typeKeys needs text or textFromEnv`);
    }
    if (step.action === 'drag') {
      validatePointSpec(step.from, `${prefix} drag start`, problems);
      validatePointSpec(step.to, `${prefix} drag destination`, problems);
      if (!step.to && !hasTargetDescriptor(step.toTarget)) {
        problems.push(`${prefix} drag needs a relative "to" point or stable "toTarget"`);
      }
      const durationMs = finiteNumber(step.durationMs ?? config.dragDurationMs, 900);
      if (strict && durationMs < 600) problems.push(`${prefix} drag duration must be at least 600ms`);
    }
    if (step.action === 'scroll' && !step.target && !step.selector) {
      const durationMs = finiteNumber(step.durationMs ?? config.scrollDurationMs, 900);
      if (strict && durationMs < 600) problems.push(`${prefix} smooth scroll duration must be at least 600ms`);
    }
  }
  if (strict) {
    const finalSteps = config.steps.slice(-4);
    if (!finalSteps.some((step) => ['assertText', 'assertUrl', 'assertVisible'].includes(step.action))) {
      problems.push('strictE2E requires a final assertion within the last four steps');
    }
  }
  return problems;
}

export {
  findSensitive,
  finiteNumber,
  getModifiers,
  getTarget,
  hasTargetDescriptor,
  includesAllowedSubstring,
  isAllowedHttpResponse,
  parseArgs,
  redactedMessage,
  resolveUrl,
  safeSlug,
  safeUrl,
  validateConfig,
};
