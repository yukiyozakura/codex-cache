# Privacy

The Codex Cache runtime stores local thread IDs, opt-in policy, generation,
activity/deadline timestamps, official token counts and compact outcomes in the
Codex plugin data directory. It does not read auth.json, keychains, environment
credentials or transcript contents. Hook payload prompt/message text is discarded.

OFF threads cause no network/model call, state write or scheduler startup.
Opted-in scheduling uses only local IPC through Codex's existing-server Unix WebSocket transport.
Native compaction is performed by Codex using its own existing authentication;
that operation may send the conversation to its configured provider and incur
usage. This plugin has no telemetry, remote backend or API-key setup.

Installer actions use the official Codex plugin CLI. Optional upstream cloning
and fork creation use GitHub. No upstream Claude script is executed.
