---
name: cache
description: Explicitly control idle auto-compaction for THIS Codex conversation. Invoke $codex-cache:cache on, off, status, or compact. Never enable automatically based on role, task, or another conversation.
---

# This conversation's cache policy

Use only when explicitly invoked by the user. Parse the argument as `on`, `off`,
`status` (also the default), or `compact`. Do not infer opt-in from Lead/Owner roles.

Run the bundled helper with the shell tool, resolving `../../src/cache.py` relative
to this SKILL.md. Example for an installed copy:

```sh
/usr/bin/python3 /absolute/plugin/root/src/cache.py on
```

The helper reads `CODEX_THREAD_ID` from the current shell environment. Never pass
another thread ID, choose a thread from a picker, or substitute the session tree ID.
If it is missing, stop and explain that current-thread identity is unavailable.
If the sandbox denies access to the plugin data directory, request the normal
shell escalation for this exact command. Do not create a second registry in the repo.

Report the helper's JSON briefly, including `enabled`, `blockedReason`, and whether
native transport/context are verified. `on` persists opt-in; it does not mean the
Desktop App Server is reachable or compaction has succeeded. The helper never
launches another App Server, parses transcripts, sends prompts, or types /compact.

`compact` queues one manual native request for after this turn. It needs fresh
official context telemetry and a verified idle root thread, and bypasses only
the 55-minute delay and 20% floor. It never enables automatic compaction.
