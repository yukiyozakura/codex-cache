# Codex Cache — opt-in idle reminders for Codex Desktop

Default **OFF** for every conversation. When explicitly enabled, notify after
**50 minutes idle**, then repeat **every minute** until user activity or OFF.
Normal Desktop settings and its App Server connection remain unchanged.

The current **0.2.0 alert mode** uses Codex lifecycle hooks, local persistent
state and macOS UserNotifications. It needs no App Server connection, context
telemetry, model call, transcript parsing or network. It does **not** compact.
It does not claim that a prompt cache is warm or has a particular expiry.

Adapted from [the-cybersapien/claude-cache](https://github.com/the-cybersapien/claude-cache),
Apache-2.0, by Aditya Aggarwal. [LICENSE](LICENSE) and [NOTICE](NOTICE) are retained.
The original Claude adapter is kept under `upstream/` for reference and excluded
from the installed runtime package.

## Use in a conversation

```text
$codex-cache:cache on
$codex-cache:cache off
$codex-cache:cache
```

Optional label, useful when multiple long conversations are enabled:

```text
$codex-cache:cache on Lead
```

Only the current `CODEX_THREAD_ID` is selected. Disposable workers, new chats
and forks stay OFF. No role name or new-session event enables reminders.
ON/OFF persists across restart/resume. After resume the next completed user turn
rearms the idle timer. Sending a status message is itself activity and resets
the wait; an in-turn `dueAt: null` is therefore normal.

Additional explicit checks:

```text
$codex-cache:cache test
$codex-cache:cache doctor
```

`test` sends one test notification without enabling a conversation. `doctor`
reads the Mac notification permission; in alert mode it never connects to an
App Server. Normal status reports `actionMode`, `enabled`, `dueAt`, `lastAlert`,
`alertCount` and `blockedReason`. `alertCount` is a cumulative accepted-request
count. `lastAlert.result.accepted` means macOS accepted it; Focus and notification
settings still control whether a banner/sound is presented.

The notification shows a short label or thread ID so it can be identified.
Repeats replace that conversation's prior Notification Center entry instead of
creating an unlimited stack. Do not use `$codex-cache:cache compact` in alert
mode; use Desktop's own manual compaction when a reminder is useful.

## Setup on this Mac

Run from the repository:

```sh
/usr/bin/python3 scripts/install.py
```

The installer backs up existing Codex config, uses official marketplace/plugin
CLI commands, creates no opted-in threads, and installs only an allowlisted
runtime package. It builds the small native helper from `native/Alerts.swift`
with Apple's Command Line Tools if the helper is absent:

```text
~/Applications/Codex Cache Alerts.app
```

No Homebrew/npm/Python package is downloaded for notifications. The helper uses
public AppKit/UserNotifications APIs and is ad-hoc signed locally. It does not
use AppleScript, UI key injection, private IPC or network access.

1. Review/trust the seven Codex Cache hooks in Desktop **Settings > Hooks** or
   **Review hooks**. Script updates require another review under Codex's trust
   rules. Version 0.2.0 changes the script and skill.
2. Enable **Codex Cache Alerts** in macOS **System Settings > Notifications**.
   The notification permission on this Mac was confirmed authorized, sound on,
   and a native test request was present in the delivered-notification list.
3. In each long conversation, run the `on` command. Installation leaves all OFF.

The skill may require an app reload if it has not refreshed automatically.
A hook's source/skill being discoverable is not proof it has fired for a given
live chat; use status/lastHook after opting in to verify that separately.

## Settings

The officially supplied `PLUGIN_DATA/settings.json` contains:

```json
{
  "autoCompactDefault": "off",
  "actionMode": "alert",
  "alertAfterMinutes": 50,
  "alertRepeatMinutes": 1,
  "compactAfterMinutes": 55,
  "minContextPercent": 20
}
```

For this marketplace, data is under
`~/.codex/plugins/data/codex-cache-codex-cache-local/`. Hook-provided PLUGIN_DATA
is authoritative; a version-independent fallback matches the current Codex
PluginStore. Registry state is SQLite. No prompt text or transcript contents
are persisted. Defaults are reloaded by the scheduler. For a one-minute
initial-delay test set `alertAfterMinutes` to `1`, then restore `50`.

The compact settings are retained for the legacy experimental compact adapter;
**alert mode does not use a context gate** because exact Desktop context usage
is unavailable without the shared-server connection. This is a time reminder,
not cache detection. `autoCompactDefault` must remain `off`; global ON is rejected.

## Timer behavior

- UserPromptSubmit updates activity, increments generation and invalidates the
  old deadline. Stop/Interrupt arm the current turn's deadline. Stale Stop events
  cannot arm a newer turn.
- After 50 idle minutes, submit one native notification and set a new deadline
  one minute later. A generation/state recheck immediately before submission
  cancels a stale claim. OFF cancels the deadline and future repeats.
- A native notification already being accepted can race an incoming user event;
  future repeats are cancelled. No destructive action is involved.
- Manual/Codex compaction observed by hooks suppresses redundant reminders until
  the next user activity.
- One flock-protected scheduler serves all opted-in conversations. It starts only
  for explicit opt-ins and exits when all are OFF. No LaunchAgent, background
  model conversation or scheduled Codex automation is created.
- The local poll is every two seconds, so submission can be a few seconds late.
  Sleep delays it; wake sends at most one due reminder and schedules the next
  minute from the actual submission time. Missed reminders are never replayed.
- OFF hooks do only ID/registry checks and exit. Child hooks carrying agent_id
  or agent_type are ignored; no SubagentStart/SubagentStop hook is installed.

## Verification

```sh
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -W error::ResourceWarning -m unittest discover -s tests-codex -v
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 scripts/smoke_alerts.py
```

The smoke test takes about two minutes and sends two real notifications, one
minute apart. It uses a synthetic ID in a temporary registry, never opts in a
real conversation, never invokes a model, and stops its scheduler after OFF.
39 automated tests cover the alert policy and retained compact/transport code.
See [VALIDATION.md](VALIDATION.md) for actual results and verification limits.

## Legacy auto-compaction

`actionMode: compact` retains the earlier 55-minute / official-context-20%
adapter, but automatic native compact remains **blocked for normal Desktop
chats on this Mac**. It is not enabled by the alert setup. The native Unix
WebSocket adapter has an isolated two-client transport test; that does not make
Desktop's private stdio backend shareable. No non-public Desktop startup flag,
extra App Server or security-check bypass is installed.

See [DESKTOP-CONNECTION.md](DESKTOP-CONNECTION.md) and
[AUDIT-UPSTREAM.md](AUDIT-UPSTREAM.md) for the connection and security review.

## References

- [Codex hooks and trust](https://learn.chatgpt.com/docs/hooks)
- [Codex plugin packaging](https://developers.openai.com/plugins/build/plugins)
- [Apple notification permission](https://developer.apple.com/documentation/usernotifications/unusernotificationcenter/requestauthorization(options:completionhandler:))
- [Apple local notification scheduling](https://developer.apple.com/documentation/usernotifications/scheduling-a-notification-locally-from-your-app)
