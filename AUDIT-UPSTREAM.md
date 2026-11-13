# Upstream behavior retained and replaced

Reference: cachekeeper 0.3.1 / claude-cache
`af2b6c523fb7f7b00024430bfb13bab921981a48`, Apache-2.0.

| Area | Upstream | Codex adaptation |
|---|---|---|
| Session state | Runtime atoms for info/prefs, store for handoff notes | Thread UUID keyed SQLite in PLUGIN_DATA, opt-in persists |
| Default | autoCompactDefault=true | off; global ON rejected |
| Timer | 15-second tick, last model request, TTL-dependent due time | Persisted deadline after Stop, generation invalidation and SQLite claim |
| Minimum context | 30% default; runtime usage window | 20%; official thread/tokenUsage/updated or skip |
| Compact guard | Versioned claim, running/compacting/compactedAt/attemptedFor | Native identity/status/hooks checks, transactional claim, PreCompact veto |
| Already compacted | session.compact plus hidden-compaction usage heuristic | Pre/PostCompact and native contextCompaction; no blank-usage inference |
| Reset | New model response clears compactedAt | Only new user prompt resets eligibility |
| Cache TTL | Claude transcript cache_creation and env/settings, 5m/1h | Not ported; 55-minute heuristic, no warmth claim |
| AFK | Can model-fork a handoff note and alter TTL timing | Excluded from MVP; no helper/model thread |
| Controls | /cache command, band buttons, AFK tool | Explicit Codex skill, current CODEX_THREAD_ID |
| Compact call | $.session.compact | thread/compact/start via existing-server proxy only |

See VALIDATION.md for the security review and Desktop blockers.
