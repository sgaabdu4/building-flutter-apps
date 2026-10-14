# Running subagents

- Using subagents is optional. When you brief one that starts a long run, tell it: never end your turn while the run is going; poll it from a foreground loop under 9 minutes and repeat. A plain `nohup … &` lets it stop early and never resume.
- SendMessage to a still-running workflow agent starts a second copy. Prevent early stops instead of relying on it.
- Start model-based test or verification runs only after every change in the task is finished, review fixes included.
- Agents can stall with no error. Keep an on-disk handover note current, and watch transcripts early for interrupts, session-limit messages or 20+ minutes with no writes. On a stall, start a fresh agent in the same worktree from that note. Do not impose a token budget or planned handover point.
