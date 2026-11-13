# Codex Cache — Desktop adapter MVP

Explicit per-conversation idle compaction, adapted from
[the-cybersapien/claude-cache](https://github.com/the-cybersapien/claude-cache)
(Apache-2.0, Aditya Aggarwal). See [NOTICE](NOTICE) and [LICENSE](LICENSE).
Original implementation and docs are retained in `upstream/`, never executed.

**Current Mac status (2026-11-13): installed, but automatic Desktop compaction
is blocked.** The Desktop's live App Server is private stdio; its documented
control/proxy socket is absent. This plugin will not load the same conversation
in a second server, type `/compact`, or use private Desktop IPC. Hook review
and an app restart do not resolve the missing shared-server connection.

## Conversation controls

After Desktop reloads the installed skill, invoke:

- `$codex-cache:cache on` — opt in only this conversation.
- `$codex-cache:cache off` — cancel its timer and persist OFF.
- `$codex-cache:cache` — status, context source, deadline, last compact and blocker.
- `$codex-cache:cache compact` — queue one manual native compact after this turn;
  it bypasses the idle delay and context floor, but still requires official
  telemetry, a verified idle thread and trusted hooks. Does not opt in.

The skill appears as `codex-cache:cache` in the actual `skills/list` response.
Typing `$cache` may find it in autocomplete, but the fully qualified name above
is the verified registered name. No custom slash command is installed.

The helper uses **CODEX_THREAD_ID**, never a session picker or the session tree
ID. Missing current-thread identity is an error. Role names, new sessions,
forks and worker creation never enable the policy.

## Policy and persistence

`PLUGIN_DATA/settings.json` defaults:

```json
{"autoCompactDefault":"off","compactAfterMinutes":55,"minContextPercent":20}
```

For development, change `compactAfterMinutes` to `1` or `2` and restore `55`
after testing. Values are reloaded while running. The safety invariant requires
`autoCompactDefault` to remain `off`; a global ON value is rejected.

State lives in SQLite under the officially provided `PLUGIN_DATA`, separate
from the versioned plugin cache. For this local marketplace it resolves to
`~/.codex/plugins/data/codex-cache-codex-cache-local/`. The helper's fallback
matches the current Codex PluginStore; hook-provided `PLUGIN_DATA` wins.
No prompt text, transcript contents, credentials or assistant text is stored.

- UserPromptSubmit increments generation/activity, invalidates the deadline and
  old context telemetry, and marks the thread running.
- Stop/Interrupt arm the deadline only for the current user turn. Stale Stops
  cannot arm a newer turn. First opt-in during a turn adopts its Stop identity.
- The scheduler rechecks registry, generation, deadline, running state, exact
  native thread ID, interactive source, parent/ephemeral flags, loaded state,
  context and trusted/enabled plugin hooks before making a native request.
- SQLite transactions claim one attempt per activity stretch; uncertain errors
  or timeouts are not retried. PreCompact can veto a cancelled/stale request.
- PostCompact and native contextCompaction items suppress further attempts until
  a new user prompt. Manual and Codex automatic compactions also count.
- Resume preserves opt-in and compact markers but invalidates old timers and
  telemetry. It waits for the next turn completion before rearming.
- No hooks for SubagentStart/SubagentStop are installed. Other hooks carrying
  agent_id/agent_type are ignored because their session_id can be the parent's.
- OFF path: one small Python process plus registry lookup, then no writes,
  no scheduler startup, IPC, network or model call. An outstanding native claim
  is the exception: its PreCompact must still be able to veto after OFF.

The scheduler runs as a detached local process only for opted-in/manual threads,
uses flock to avoid duplicate schedulers, and exits after all are OFF. Hooks
restart it on resume/Stop. It is not a LaunchAgent and does not keep a Mac awake.

## Native transport and telemetry

Only the documented Unix WebSocket transport to an **existing** App Server is used. No daemon
bootstrap, remote-control enablement, second-server resume, UI keystrokes or
private Desktop socket protocol is used by the runtime adapter.

Documented methods:

- initialize/initialized; thread/loaded/list; hooks/list; thread/read
- thread/resume (only a verified already-loaded interactive root; no overrides)
  to subscribe to token telemetry without fetching history; thread/unsubscribe when OFF
- thread/tokenUsage/updated: `100 * last.totalTokens / modelContextWindow`
- thread/compact/start with exactly `{"threadId": "<current opt-in ID>"}`
- item/completed with contextCompaction as an additional completion signal

The context numerator and denominator are the runtime's official reported
values, **not an independently measured exact count of the next prompt**.
No cumulative token totals, transcript parser, character estimate or hardcoded
window size authorizes compaction. Missing/invalid/stale usage means skip.
The first opt-in may need another normal user turn before live telemetry is
available; the adapter never invents it from a model name.

No API in the inspected Codex protocol reports a live cache-entry expiry or a
current warm/cold boolean. Cached-input token counts report previous request
hits, not future warmth. The 55-minute policy is a **heuristic**, not an OpenAI
cache TTL assertion and not a guarantee of cheaper compaction. Model/retention
policies differ. Native compaction can itself incur model usage.

Pre/PostCompact trigger distinguishes `manual` versus `auto`. API-initiated
compaction is reported as manual too, with no caller tag. The plugin correlates
its pending claim and turn as `plugin-request-associated`; simultaneous human
manual requests cannot be attributed with absolute certainty. Its status says
`attribution: correlated`, never claims an authenticated origin.

The API has no atomic "compact only if turn/generation unchanged" parameter.
Final reads, registry CAS and PreCompact reduce races but do not form a server
transaction: a concurrent user turn can start between final read and request
acceptance, and a PreCompact veto cannot undo preceding server task scheduling.
Strict race-free compaction requires an additional native server precondition.

## Install and review

Requires macOS Desktop with Python 3.9+ and the bundled Codex CLI.

```sh
/usr/bin/python3 scripts/install.py
```

Uses official `plugin marketplace add` and `plugin add`, backs up config first,
and preserves unrelated config. The current runtime ignores bundled hooks for
portable root `plugin.json`; this package therefore uses the officially supported
`.codex-plugin/plugin.json` compatibility format. This was verified with the
installed Desktop runtime rather than assumed from the latest documentation.

Desktop: **Settings > Hooks** (or **Review hooks** in composer), review/trust the
seven Codex Cache hooks. Restart Desktop when convenient to reload the skill.
**Automatic compaction remains blocked on this Mac until the Desktop's actual
App Server offers a documented shared connection.** A separate CLI server cannot
prove the Desktop thread idle and is not a workaround.

No existing conversation is enabled by installation, including the setup chat.

## Verify

```sh
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest discover -s tests-codex -v
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 scripts/inspect_runtime.py
```

The second command starts a separate **read-only diagnostic** stdio server for
hooks/list and skills/list. It never creates, resumes or compacts a thread and
is explicitly not a Desktop live-session test. See [VALIDATION.md](VALIDATION.md).

## Desktop connection investigation (0.1.1)

All seven original hooks were confirmed trusted after the user's review. A
subsequent isolated transport test found a 0.1.0 adapter bug: `app-server proxy`
is a raw byte relay, not a JSONL-to-WebSocket bridge. Version 0.1.1 implements
HTTP Upgrade plus masked WebSocket frames over a private same-user Unix socket.
A real isolated server accepted two simultaneous clients; no model turns were
submitted. Fragmentation, ping/pong, handshake validation and frame limits are
covered by tests. The installed hook script change requires a new Codex review.

This fixes the adapter, **not Desktop's missing shared connection**. The current
installed Desktop has an internal `CODEX_APP_SERVER_USE_LOCAL_DAEMON` path, but
its normal app-tools config override prevents that branch from being selected.
An internal WebSocket endpoint override also exists; forcing it can make the
app's chat-management/automation connector unavailable. No environment override,
Desktop process restart, app patch, security-check bypass or remote-login change
was applied. See [DESKTOP-CONNECTION.md](DESKTOP-CONNECTION.md) for evidence and
alternatives. The runtime remains OFF by default and fail-closed.

## Sources

- [Codex hooks](https://learn.chatgpt.com/docs/hooks)
- [Plugin packaging](https://developers.openai.com/plugins/build/plugins)
- [Codex App Server](https://learn.chatgpt.com/docs/app-server)
- [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
- Local generated protocol: Desktop bundled codex-cli 0.167.0-alpha.3.2;
  separate Homebrew CLI 0.166.0 was not substituted for the Desktop runtime.
- [Codex open source](https://github.com/openai/codex), inspected main
  69231e119bfca0b14453515e97d99688ce1c47c9 as corroboration; installed runtime
  discovery remains the release behavior evidence.
