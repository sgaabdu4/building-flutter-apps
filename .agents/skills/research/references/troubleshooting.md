# Failure and remedy research

- Establish expected behavior, observed failure and the exact environment: relevant command/route, input, error, version and configuration. Use available evidence before asking the user to repeat it.
- Reproduce the reported case at its actual failing boundary: command, request, browser/device or runtime. Minimize the case without removing the conditions that trigger it. If reproduction is unavailable, retain that limitation instead of claiming a confirmed cause.
- Form plausible competing explanations and choose the smallest observation that distinguishes them. Investigate the failing boundary and adjacent assumptions rather than repeating the same unsuccessful action.
- Recurrence = comparable symptom, boundary and conditions; a repeated message alone does not prove a shared cause. Compare each attempted change with its result. After repeated failure, require new distinguishing evidence before another similar attempt; otherwise state the missing evidence and next useful check. Reuse the conversation/test evidence, not a separate failure ledger.
- Search current official docs, changelogs and issues using the error and environment. Consult analogous community incidents for leads; match their versions and conditions before adopting a remedy.
- Trace the relevant caller, dependency and response/error handling through Codebase and Library and API routes as needed.
- Tie the correction to a demonstrated mechanism at its owner; a nearby stack frame, correlation or plausible narrative is insufficient. If a candidate fails, reassess the explanation. Keep unresolved hypotheses explicit until evidence distinguishes them.
- If implementation is authorized, verify the original failure and the affected behavior after the correction. Otherwise provide a concrete recommendation and the remaining proof, without implying that a proposed fix has been tested.
