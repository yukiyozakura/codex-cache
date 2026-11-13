# Desktop connection follow-up — 2026-11-13

## Current outcome

The seven installed 0.1.0 hooks were approved and hooks/list confirmed all seven
as trusted. The normal Desktop App Server still has a private stdio connection
and no default Unix listener. Approval alone cannot create that listener.

The local setup chat remains OFF. No existing conversation was resumed or
compacted by another server during this investigation.

## Candidate routes

| Route | Status | Decision |
|---|---|---|
| Attach to the existing normal Desktop backend | No documented shared local endpoint in this installation | Cannot currently execute native compact externally |
| Enable internal local-daemon flag | Installed startup requires an empty override list; normal Desktop always supplies an app-tools override | Flag alone cannot select the shared daemon |
| Force internal WebSocket endpoint override | Code path exists; a shared server can accept multiple clients | Experimental, app-wide topology change; not applied |
| Desktop SSH project to a shared server | SSH projects are documented | Requires a different host/project route; not an in-place fix for local chats |
| Start a second server and resume the current local thread | Does not share live status/writer ownership | Rejected |
| Private IPC, key injection or trust-check bypass | Outside this integration's constraints | Rejected |

### Official documentation and installed source

[App Server protocol](https://learn.chatgpt.com/docs/app-server#protocol) specifies
WebSocket over Unix sockets. `--listen unix://` creates the default listener;
`app-server proxy` relays bytes to it. Inspection of the official CLI source
confirms that proxy does not translate JSONL into WebSocket frames.

The installed 0.167.0-alpha.3.2 Desktop runtime and application package were
inspected read-only. No app file was modified. Normal transport selection
includes an app-tools config override; the internal daemon selection gate
requires no config overrides. This independently matches the report below.

An internal `CODEX_APP_SERVER_WS_URL` override is present, but no official
configuration reference found in this investigation documents it as a supported
Desktop user setting. Changing it changes the app's backend globally, beyond
this plugin's per-thread opt-in policy.

### Public corroboration (reports are not release guarantees)

- [#41014: daemon selection blocked by app-tools override](https://github.com/openai/codex/issues/41014).
  Still open when checked. Its November 12 follow-up describes the same gate in
  macOS package 26.1103.60933, matching this installation's code path.
- [#37403: Desktop/CLI writer ownership](https://github.com/openai/codex/issues/37403).
  An OpenAI contributor explains that Desktop launches its own App Server rather
  than sharing the daemon. A separate server is therefore not the same live owner.
- [#47425: app-tools failures after forcing shared daemon](https://github.com/openai/codex/issues/47425).
  Reported failures include chat management and automation tools becoming
  unavailable; a November 3 follow-up reports continued macOS failures. This is
  evidence of a material tradeoff, not proof that every feature fails here.
- [#40134: request for documented external-server attachment](https://github.com/openai/codex/issues/40134).
  Still open when checked; absence of a documented setting is not a promise about
  future releases or hidden flags.

[Official SSH setup](https://learn.chatgpt.com/docs/remote-connections#connect-to-an-ssh-host)
is a separate supported workflow. This Mac's localhost TCP port 22 refused a
connection. Remote Login was not enabled and no SSH credentials were created.
Self-SSH routing of existing local chats was not established, so it is not
presented as an automatic replacement for the current workflow.

## Work completed without changing the Desktop topology

The 0.1.0 adapter incorrectly treated raw proxy output as JSONL. Corrected it in
0.1.1 to perform the HTTP Upgrade and RFC 6455 framing on a private same-user
Unix socket. It offers no compression/extensions and validates the handshake,
handles fragmented text and ping/pong, masks client frames and enforces a size
limit. No new Python/npm package, remote listener or credential is needed.

27 tests pass. An actual temporary App Server with an isolated CODEX_HOME
accepted two concurrent clients through the new adapter. Both returned an empty
loaded-thread list. Zero model turns were submitted. The server was stopped.
This proves the adapter's native shared transport, not live Desktop compaction.

No launchctl environment override, LaunchAgent, service bootstrap, Desktop
restart, app patch or security-check change was applied. The user's normal
Desktop connection and all opt-in defaults remain unchanged. Version 0.1.1
requires another hook review because the bundled script changed.

## If choosing a later experimental trial

A concrete trial would use the same bundled Codex executable, a private Unix
listener and a one-launch Desktop endpoint override. It must stop normal
Desktop ownership before resuming any existing thread and must verify native
app tools as well as compact. It must have a rollback that quits the trial
Desktop, stops only the trial server, removes only the trial override and
relaunches normally. Do not patch process-ancestry or code-signing checks.

That trial is **not enabled or verified** by this document. A user decision is
needed before changing the normal app-wide backend with the known app-tools
tradeoff. Current automatic compaction therefore remains blocked.
