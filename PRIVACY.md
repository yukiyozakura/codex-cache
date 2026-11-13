# Privacy

Default alert mode stores thread IDs, explicit opt-in, optional user label,
generation/activity/deadline timestamps and notification outcomes locally in
Codex's plugin data directory. Hook prompt/message fields are discarded.

OFF conversations perform no state write, helper/daemon startup, model call or
network call. Alert scheduling uses only local SQLite and the public macOS
UserNotifications API through the locally built Codex Cache Alerts helper app.
It does not read transcript contents, auth.json, credentials or keychains, contact
an App Server, invoke a model, or compact. The native helper receives only a
thread ID, short label and idle duration, which can appear on the lock screen
according to the user's notification preview settings.

The retained legacy compact mode requires explicit configuration and a verified
existing App Server. Native compaction uses Codex's own provider authentication
and may transmit conversation context/incur usage; it remains unavailable for
normal Desktop chats on this Mac. No private Desktop bridge is installed.

Installer actions use official Codex CLI plugin commands and Apple's compiler,
codesign and registration tools. Original Claude scripts and local config
backups are excluded from the installed package. There is no remote backend or
plugin telemetry.
