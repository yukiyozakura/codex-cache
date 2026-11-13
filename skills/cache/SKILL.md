---
name: cache
description: Explicitly control idle reminders for THIS Codex conversation. Invoke $codex-cache:cache on, off, status, test, or doctor. Default OFF. Alerts begin after 50 minutes idle and repeat every minute until activity or OFF. Never enable based on role or another conversation.
---

# This conversation's idle reminder

Use only when explicitly invoked by the user. Parse `on`, `off`, `status`
(default), `test`, or `doctor`. Never infer opt-in from Lead/Owner roles.
`on` may have an optional short user-provided label, for example `on Lead`.

Run the bundled helper, resolving `../../src/cache.py` relative to this SKILL.md:

```sh
/usr/bin/python3 /absolute/plugin/root/src/cache.py on --label Lead
```

The helper reads the current `CODEX_THREAD_ID`. Never select another thread,
substitute the session tree ID, or use a picker. If the ID is missing, stop and
explain that current-thread identity is unavailable. If the sandbox denies
plugin data access, request the normal escalation for this exact command; never
create a separate registry in the repository.

Default settings: actionMode=alert, autoCompactDefault=off, alertAfterMinutes=50,
alertRepeatMinutes=1. This mode sends local Mac notifications. It never compacts,
connects to App Server or calls a model, and it does not apply a context gate.
Repeat notices stop/reset on user activity or OFF. Codex compaction suppresses
redundant reminders until the next user activity. New/forked/worker threads stay
OFF. ON/OFF persists across resume; resumed chats rearm after a turn completes.

`test` sends one native test notification without enabling the conversation.
`doctor` reports notification permission and backend status; it does not contact
App Server in alert mode. If `notification-permission-not-authorized` appears,
tell the user to enable Codex Cache Alerts in macOS System Settings > Notifications.
Do not edit the OS permission database or use AppleScript/UI automation.

Report `enabled`, `actionMode`, `dueAt`, `lastAlert`, `alertCount` and
`blockedReason` briefly. `accepted=true` means macOS accepted the request;
Focus/notification settings may still suppress a visible banner or sound.
Sending a status/doctor message is itself activity and restarts the idle wait.
Do not promise exact cache expiry, warm cache detection or automatic compaction.
