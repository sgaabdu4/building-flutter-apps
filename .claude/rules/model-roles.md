# Subagent models by role

- Using subagents is optional; decide per task. These rules apply only when you use them.
- Planning, research needing judgment, investigation and review subagents run on Opus: `model: "opus"`.
- Implementation subagents (writing or changing code, mechanical edits, carrying out an agreed plan) run on Sonnet: `model: "sonnet"`.
- Narrow lookup subagents (finding files or code, pulling one fact from a doc, summarizing logs or CI output, simple browser checks) run on Haiku: `model: "haiku"`. They report back and never write code or make judgment calls.
- Workflow scripts follow the same split in every `agent()` opts object. Never leave a subagent on the default model.
- Don't stop or restart running agents just to change their model.
- Same-task follow-up → SendMessage the finished subagent; unrelated task → new subagent.
