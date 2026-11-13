# Validation and audit — 2026-11-13 (JST)

## Result

Implementation and user-scope installation completed. **Operational Desktop idle
compaction is not verified and is blocked on this Mac.** No conversation was
opted in by installation. No production thread was compacted or resumed by the
plugin during setup.

## Evidence

- Upstream clone/revision: the-cybersapien/claude-cache,
  af2b6c523fb7f7b00024430bfb13bab921981a48, v0.3.1.
- Fork: https://github.com/yukiyozakura/codex-cache (branch codex-desktop).
- Apache-2.0 LICENSE retained unchanged, NOTICE added, changed upstream source
  relocated with original contents to upstream/ and excluded from runtime package.
- Desktop bundled CLI: 0.167.0-alpha.3.2. Homebrew CLI: 0.166.0.
- Official plugin CLI reports codex-cache@codex-cache-local installed/enabled.
- Official hooks/list in a separate read-only diagnostic server discovers seven
  hooks with no load errors/warnings. Their actual status is **untrusted**.
- Official skills/list discovers codex-cache:cache, scope user, enabled true.
- Root portable plugin.json loaded the skill but silently omitted hooks in this
  runtime. The compatibility .codex-plugin/plugin.json loads both successfully.
- Read-only process inspection: live Desktop app-server launched without --listen
  unix://, using its stdio connection. Default app-server-control socket absent.
- Bundled `codex app-server proxy` returns "No such file or directory" for its
  default socket. The adapter does not discover or reverse-engineer private IPC.
- App UI automation cannot inspect this app: computer-use tool denies access to
  com.openai.codex. No alternative UI automation was used to bypass this restriction.

## Automated tests

27 tests pass with Python 3.9.6 and ResourceWarning treated as errors:

```sh
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -W error::ResourceWarning -m unittest discover -s tests-codex -v
```

Coverage includes OFF no-write/no-daemon behavior; ON-only native request; reset
and stale Stop; OFF cancellation; manual/automatic/plugin-associated compaction
markers; one attempt per idle stretch, including missing completion; new user
activity; multiple thread IDs; workers sharing a parent's session ID; active,
wrong-ID and noninteractive source rejection; exact 20% boundary; absent
telemetry; OFF/activity races during native reads; delayed request veto; registry
reopen/resume; 1-minute configuration; rejection of global ON; opt-in mid-turn;
missing/untrusted hooks; actual scheduler loop with a mock native adapter.

Tests use virtual timestamps or mocks for native mutations. They are **not**
Desktop end-to-end verification and do not claim a successful live compact.
The 1-minute configuration is checked with virtual time; no 55-minute wait or
paid model invocation was performed.

## Security review

Read upstream runtime, manifest, hooks, tests and CI before execution. Upstream
has a `$.process.run(['tail', '-c', '262144', transcript])` call for Claude TTL
inference, environment/settings reads, store writes, `$.session.compact`, and
`$.model.fork` for AFK handoff generation. The fork and compact can call the
model via Claude's runtime. Upstream CI installs Claude/TypeScript via npm and
runs shell/CLI validation. No direct fetch/HTTP client, credential-file read,
keychain read or arbitrary shell string in the plugin runtime was found. This
is a bounded source review, not a guarantee about Claude's runtime dependencies.

None of that adapter or CI is executed by Codex Cache. The new runtime uses the
Python standard library, no shell=True, no eval, no external Python/npm package,
no transcript parser, no API key, no credential read and no remote telemetry.
Its only runtime subprocess is its own detached Python scheduler. It connects
to an existing private same-user Unix socket directly, using the documented
WebSocket protocol; it never starts an App Server. Hook command paths are quoted. Input IDs are
validated UUIDs; SQLite parameters are bound. Only lifecycle/usage metadata is
stored; prompt/message text is discarded. Config backup and generated package
are gitignored. Installer stages an allowlisted package, so user config backups
and .git are not copied into the installed plugin.

## Remaining manual / unavailable checks

1. Desktop restart to reload the skill; review/trust Codex Cache in Settings >
   Hooks or Review hooks. Required by Codex's documented trust policy; no trust
   database was edited or bypassed.
2. Actual Desktop hook firing, conversation invocation, deadline updates,
   native target-only compact and restart/resume end-to-end remain unverified.
3. A supported connection to the Desktop's same App Server is required. Hook
   trust/restart alone does not expose that connection. The runtime stays
   fail-closed if native telemetry or live idle status is unavailable.
4. Native compact lacks an atomic expected-turn/generation precondition. A
   concurrent turn can race the final read. PreCompact veto is an additional
   guard, not a server-side transactional scheduling guarantee.
5. API compact is tagged manual by Codex, so plugin-vs-human attribution is
   request/turn correlation. Codex-auto vs manual is a formal hook trigger.
6. OFF hook process startup remains one small Python invocation per configured
   lifecycle event. No global model call/network scan/daemon is launched.
7. Resume preserves opt-in but intentionally requires a subsequent turn Stop
   and fresh native usage before another timer may compact.
8. Sleep/wake/offline can delay a wall-clock deadline. No warm-cache guarantee,
   exact expiry, token savings or price savings are claimed.

## Follow-up after hook approval

The user approved all seven hooks; hooks/list confirmed each as trusted. The
Desktop shared socket was still absent. The installed application startup logic
was inspected read-only and confirmed the nonempty-config-override gate described
in issue #41014. No application bundle or signing/security checks were changed.

An isolated native transport probe exposed a defect missed by mocked 0.1.0
adapter tests: `app-server proxy` relays raw bytes and does not translate JSONL.
Fixed in 0.1.1 with a minimal standards-based Unix WebSocket client. Six additional
protocol tests cover text fragmentation across UTF-8 boundaries, ping/pong,
masked client frame lengths, invalid/oversized frames, close/EOF, private
same-user socket checks and HTTP handshake validation. All 27 tests pass.

`scripts/probe_shared_transport.py` starts a temporary independent CODEX_HOME
and a temporary Unix listener. Two simultaneous clients successfully initialize
and call thread/loaded/list, both seeing no loaded threads. No thread is created,
read or resumed, and no model turn is submitted. The test server is terminated
and its temporary state removed. This is transport verification, not Desktop
end-to-end verification. The initial failed JSONL probe timed out; its test
server exited and generated temporary state was subsequently cleaned up.

The source update is installed as 0.1.1 and requires hook re-review under Codex's
hash-based trust rules. The user's approval of 0.1.0 was not overwritten or
copied to the new definition. No conversation was enabled by this update.
