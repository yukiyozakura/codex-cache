# 0.1.1 — Correct native Unix WebSocket transport

- Replace mistaken JSONL-over-proxy assumption with real HTTP Upgrade and
  WebSocket frames on a private same-user Unix socket.
- Add six protocol tests and an isolated two-client native transport probe.
- Confirm the Desktop connection blocker and document experimental alternatives.
- No app-wide connection override or opt-in state change is applied.

# 0.1.0 — Codex Desktop adaptation, 2026-11-13

- Explicit per-thread opt-in, default OFF, 55-minute idle, official context 20% gate.
- Persistent registry, generation-based cancellation, at-most-once claims.
- Seven native lifecycle hooks and a conversation skill.
- Existing-server native compact adapter; unavailable Desktop transport fails closed.
- Apache-2.0 attribution; original Claude source retained under upstream/.
- This Mac: installed and discovered; live Desktop compact remains blocked.
