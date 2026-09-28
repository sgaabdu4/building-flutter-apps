const inputEvidenceVersion = 1;
const minimumSettleMs = 150;
const pointerActivationActions = new Set(['click', 'select', 'type']);
const keyboardActivationActions = new Set(['press']);

function rounded(value) {
  return Math.round(Number(value) * 10) / 10;
}

function normalizedBox(value) {
  if (!value || ![value.x, value.y, value.width, value.height].every(Number.isFinite) || value.width <= 0 || value.height <= 0) {
    return null;
  }
  return {
    x: rounded(value.x),
    y: rounded(value.y),
    width: rounded(value.width),
    height: rounded(value.height),
  };
}

function normalizedPoint(value) {
  if (!value || ![value.x, value.y].every(Number.isFinite)) return null;
  return { x: rounded(value.x), y: rounded(value.y) };
}

function pointInsideBox(point, box) {
  return Boolean(point && box && point.x >= box.x && point.y >= box.y && point.x <= box.x + box.width && point.y <= box.y + box.height);
}

function boxesOverlap(first, second) {
  if (!first || !second) return false;
  return (
    Math.max(first.x, second.x) < Math.min(first.x + first.width, second.x + second.width) &&
    Math.max(first.y, second.y) < Math.min(first.y + first.height, second.y + second.height)
  );
}

function createPointerInputEvidence({ targetBox, pointerPosition, pointerVisibleAtActivation, settleMs, activationTimeMs, cue }) {
  return {
    schemaVersion: inputEvidenceVersion,
    inputType: 'pointer',
    targetBox: normalizedBox(targetBox),
    pointerPositionAtActivation: normalizedPoint(pointerPosition),
    pointerVisibleAtActivation: Boolean(pointerVisibleAtActivation),
    settleMs: rounded(settleMs),
    activationTimeMs: rounded(activationTimeMs),
    cue: cue || null,
  };
}

async function activateWithPointer({ target, pointer, activate }) {
  const clickCue = await pointer.beginClick();
  const activationTimeMs = pointer.time();
  let cue;
  try {
    await activate(target);
  } finally {
    cue = await pointer.finishClick(clickCue);
  }
  const pointerSnapshot = pointer.snapshot();
  return {
    target,
    input: createPointerInputEvidence({
      targetBox: target.box,
      pointerPosition: pointerSnapshot.position,
      pointerVisibleAtActivation: pointerSnapshot.options.enabled,
      settleMs: activationTimeMs - target.motion.moveEndedAtMs,
      activationTimeMs,
      cue,
    }),
  };
}

function createKeyboardInputEvidence({
  scope,
  targetBox,
  focusBox,
  focusConfirmed,
  pointerPosition,
  pointerVisibleAtActivation,
  settleMs,
  activationTimeMs,
  keyChord,
  cue,
}) {
  return {
    schemaVersion: inputEvidenceVersion,
    inputType: 'keyboard',
    scope,
    targetBox: normalizedBox(targetBox),
    focusBox: normalizedBox(focusBox),
    focusConfirmed: Boolean(focusConfirmed),
    pointerPositionAtActivation: normalizedPoint(pointerPosition),
    pointerVisibleAtActivation: Boolean(pointerVisibleAtActivation),
    settleMs: rounded(settleMs),
    activationTimeMs: rounded(activationTimeMs),
    keyChord: String(keyChord),
    cue: cue || null,
  };
}

function auditStepInputEvidence(step, { pointerEnabled = true } = {}) {
  const expectedType = pointerActivationActions.has(step.action)
    ? 'pointer'
    : keyboardActivationActions.has(step.action)
      ? 'keyboard'
      : null;
  if (!expectedType) {
    return { step: step.index, required: false, passed: true, findings: [] };
  }

  const findings = [];
  const add = (kind, detail) => findings.push({ kind, detail });
  const events = Array.isArray(step.metadata?.inputEvents) ? step.metadata.inputEvents : [];
  if (events.length !== 1) {
    add('input-evidence-missing', `expected one ${expectedType} activation record and received ${events.length}`);
    return { step: step.index, required: true, passed: false, findings };
  }

  const evidence = events[0];
  if (evidence.schemaVersion !== inputEvidenceVersion || evidence.inputType !== expectedType) {
    add('input-evidence-invalid', `expected schema ${inputEvidenceVersion} ${expectedType} evidence`);
  }
  if (
    !Number.isFinite(evidence.activationTimeMs) ||
    evidence.activationTimeMs < step.startMs - 20 ||
    evidence.activationTimeMs > step.actionEndMs + 20
  ) {
    add('input-activation-time-invalid', 'activation time falls outside the recorded action');
  }
  if (!Number.isFinite(evidence.settleMs) || evidence.settleMs < minimumSettleMs) {
    add('input-settle-too-short', `the control settled for ${Math.max(0, Number(evidence.settleMs) || 0)}ms`);
  }

  if (expectedType === 'pointer') {
    const targetBox = normalizedBox(evidence.targetBox);
    const pointerPosition = normalizedPoint(evidence.pointerPositionAtActivation);
    if (!targetBox) add('input-target-box-invalid', 'pointer activation has no valid target box');
    if (!pointerPosition) {
      add('input-pointer-position-invalid', 'pointer activation has no valid pointer position');
    } else if (targetBox && !pointInsideBox(pointerPosition, targetBox)) {
      add('pointer-target-mismatch', 'pointer activation happened outside the target box');
    }
    if (pointerEnabled && evidence.pointerVisibleAtActivation !== true) {
      add('pointer-activation-hidden', 'pointer activation was not visible');
    }
    if (pointerEnabled && evidence.cue?.kind !== 'click-ripple') {
      add('pointer-cue-missing', 'pointer activation has no visible click cue');
    }
  }

  if (expectedType === 'keyboard') {
    if (!['target', 'global'].includes(evidence.scope)) {
      add('keyboard-scope-invalid', 'keyboard activation has no valid scope');
    }
    if (evidence.scope === 'target') {
      const targetBox = normalizedBox(evidence.targetBox);
      const focusBox = normalizedBox(evidence.focusBox);
      if (!targetBox || !focusBox || !boxesOverlap(targetBox, focusBox)) {
        add('keyboard-focus-mismatch', 'keyboard focus does not match the target box');
      }
      if (evidence.focusConfirmed !== true) {
        add('keyboard-focus-missing', 'keyboard target was not confirmed as focused');
      }
    }
    const cue = evidence.cue;
    if (
      cue?.kind !== 'keyboard' ||
      !Number.isFinite(cue.shownAtMs) ||
      !Number.isFinite(cue.hiddenAtMs) ||
      cue.shownAtMs > evidence.activationTimeMs ||
      cue.hiddenAtMs < evidence.activationTimeMs
    ) {
      add('keyboard-cue-missing', 'keyboard activation has no complete visible key cue');
    }
    if (pointerEnabled && evidence.pointerVisibleAtActivation !== false) {
      const changedPage = step.beforeUrl !== step.afterUrl;
      add(
        'ambiguous-keyboard-activation',
        changedPage
          ? 'the page changed while an unrelated pointer remained visible'
          : 'an unrelated pointer remained visible during keyboard activation',
      );
    }
  }

  return {
    step: step.index,
    required: true,
    passed: findings.length === 0,
    findings,
  };
}

export {
  activateWithPointer,
  auditStepInputEvidence,
  createKeyboardInputEvidence,
  createPointerInputEvidence,
  inputEvidenceVersion,
  minimumSettleMs,
};
