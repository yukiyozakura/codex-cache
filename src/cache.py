#!/usr/bin/env python3
"""Codex-native adapter. Apache-2.0; policy attribution: ../NOTICE.
No third-party dependencies, transcript reads, credential reads or shell execution.
"""
import argparse
import asyncio
import contextlib
import fcntl
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time

DEFAULTS = dict(autoCompactDefault='off', compactAfterMinutes=55, minContextPercent=20)
HOOK_EVENTS = {'SessionStart', 'UserPromptSubmit', 'Stop', 'Interrupt', 'PreCompact', 'PostCompact', 'SessionEnd'}
DESKTOP_CODEX = '/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex'
IDENTITY = re.compile(r'^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$')


def data_dir():
    # Hook environment is authoritative. Fallback matches PluginStore's user data
    # directory for the fixed local marketplace, not the versioned plugin cache.
    if os.environ.get('PLUGIN_DATA'):
        return Path(os.environ['PLUGIN_DATA'])
    return Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'plugins/data/codex-cache-codex-cache-local'


def fresh(tid):
    return dict(threadId=tid, enabled=False, generation=0, activity=0,
                lastActivityAt=None, dueAt=None, running=True, turnId=None,
                compactedActivity=None, attemptedActivity=None, pending=None,
                manual=False, adoptStop=False, usage=None, lastCompact=None, hookCount=0,
                blockedReason='not-opted-in')


class Store:
    def __init__(self, root, create=False):
        self.root = Path(root).expanduser().resolve()
        self.path = self.root / 'registry.sqlite3'
        if create:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            with self.connect() as db:
                db.execute('CREATE TABLE IF NOT EXISTS threads(id TEXT PRIMARY KEY, data TEXT NOT NULL)')
                db.execute('CREATE TABLE IF NOT EXISTS runtime(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)')
            self.path.chmod(0o600)
            path = self.root / 'settings.json'
            if not path.exists():
                with path.open('x') as f:
                    json.dump(DEFAULTS, f, indent=2)
                path.chmod(0o600)

    @contextlib.contextmanager
    def connect(self, readonly=False):
        db = sqlite3.connect(self.path.as_uri() + ('?mode=ro' if readonly else '?mode=rwc'), uri=True, timeout=1)
        db.execute('PRAGMA busy_timeout=1000')
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, tid):
        if not self.path.exists():
            return None
        with self.connect(True) as db:
            row = db.execute('SELECT data FROM threads WHERE id=?', (tid,)).fetchone()
            return json.loads(row[0]) if row else None

    def change(self, tid, fn):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM threads WHERE id=?', (tid,)).fetchone()
            s = json.loads(row[0]) if row else fresh(tid)
            result = fn(s)
            db.execute('INSERT OR REPLACE INTO threads VALUES(?,?)', (tid, json.dumps(s)))
            return result

    def all(self):
        if not self.path.exists():
            return []
        with self.connect(True) as db:
            return [json.loads(r[0]) for r in db.execute('SELECT data FROM threads')]

    def runtime(self, value=None):
        if not self.path.exists():
            return {}
        with self.connect() as db:
            if value is not None:
                db.execute('INSERT OR REPLACE INTO runtime VALUES(1,?)', (json.dumps(value),))
            row = db.execute('SELECT data FROM runtime WHERE id=1').fetchone()
            return json.loads(row[0]) if row else {}

    def settings(self):
        path = self.root / 'settings.json'
        cfg = {**DEFAULTS, **(json.loads(path.read_text()) if path.exists() else {})}
        if cfg['autoCompactDefault'] != 'off':
            raise ValueError('autoCompactDefault must remain off; opt-in is required per thread')
        for key, low, high in [('compactAfterMinutes', 0.01, 1440), ('minContextPercent', 0, 100)]:
            v = cfg[key]
            if isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or not low <= v <= high:
                raise ValueError('invalid setting: ' + key)
        return cfg


def invalidate(s):
    s['generation'] += 1
    s['dueAt'] = None
    s['usage'] = None
    # Retain an outstanding claim so PreCompact can veto a delayed request.


def arm(s, cfg, now):
    s['running'] = False
    s['lastActivityAt'] = now
    if (s['enabled'] or s['manual']) and s['activity'] > 0 and s['compactedActivity'] != s['activity'] and s['attemptedActivity'] != s['activity']:
        s['dueAt'] = now if s['manual'] else now + cfg['compactAfterMinutes'] * 60
        s['blockedReason'] = 'waiting-idle-deadline'


def context_percent(s):
    u = s.get('usage')
    if not u or u.get('activity') != s['activity'] or u.get('turnId') != s['turnId']:
        return None
    window, tokens = u.get('modelContextWindow'), u.get('tokens')
    if (isinstance(window, bool) or isinstance(tokens, bool) or
        not isinstance(window, (int, float)) or not isinstance(tokens, (int, float)) or
        not math.isfinite(window) or not math.isfinite(tokens) or window <= 0 or tokens < 0):
        return None
    return 100 * tokens / window


def blocker(s, cfg, now):
    if not (s['enabled'] or s['manual']): return 'not-opted-in'
    if s['running']: return 'thread-running'
    if s['activity'] <= 0: return 'awaiting-user-activity'
    if s['compactedActivity'] == s['activity']: return 'already-compacted-this-idle-stretch'
    if s['attemptedActivity'] == s['activity']: return 'already-attempted-this-idle-stretch'
    if s['dueAt'] is None or now < s['dueAt']: return 'waiting-idle-deadline'
    p = context_percent(s)
    if p is None: return 'official-context-telemetry-unavailable'
    if not s['manual'] and p < cfg['minContextPercent']: return 'below-minimum-context'
    return None


def hook(store, e, now=None):
    now = time.time() if now is None else now
    tid = e.get('session_id', '')
    # Child hooks share a parent session ID. Never let them mutate the parent's policy.
    if not IDENTITY.fullmatch(tid) or e.get('agent_id') or e.get('agent_type'):
        return {}
    held = store.get(tid)
    if not held or not (held['enabled'] or held['manual'] or held['pending']):
        return {}  # OFF: no writes, settings reads, daemon or IPC.
    cfg = store.settings()
    event = e.get('hook_event_name')
    output = {}
    def update(s):
        nonlocal output
        s['hookCount'] += 1
        s['lastHook'] = dict(event=event, at=now)
        if event == 'UserPromptSubmit':
            invalidate(s)
            s['activity'] += 1
            s['turnId'] = e.get('turn_id')
            s['lastActivityAt'] = now
            s['running'] = True
            s['adoptStop'] = False
            s['blockedReason'] = 'thread-running'
        elif event == 'SessionStart':
            if e.get('source') == 'compact':
                s['compactedActivity'] = s['activity']
            else:
                invalidate(s)
                s['running'] = True
                s['blockedReason'] = 'resumed-awaiting-turn-completion'
        elif event in ('Stop', 'Interrupt'):
            if s.get('adoptStop') and event == 'Stop':
                s['turnId'] = e.get('turn_id')
                s['activity'] += 1
                s['adoptStop'] = False
            # A stale Stop from a previous turn must never arm a newer turn.
            if e.get('turn_id') == s['turnId']:
                arm(s, cfg, now)
        elif event == 'SessionEnd':
            invalidate(s)
            s['running'] = True
            s['blockedReason'] = 'session-ended-awaiting-resume'
        elif event == 'PreCompact':
            pending = s['pending']
            if pending:
                valid = (pending['generation'] == s['generation'] and
                         pending['activity'] == s['activity'] and
                         (s['enabled'] or s['manual']) and
                         s['compactedActivity'] != s['activity'] and
                         e.get('turn_id') != s['turnId'])
                if not valid:
                    output = dict(continue_=False, stopReason='Codex Cache: stale or cancelled compaction request')
                    output['continue'] = output.pop('continue_')
                    s['blockedReason'] = 'stale-compaction-vetoed'
                    return
                pending['turnId'] = e.get('turn_id')
            # All compactions inhibit our next auto attempt, even if they fail.
            s['dueAt'] = None
            s['attemptedActivity'] = s['activity']
        elif event == 'PostCompact':
            pending = s['pending']
            associated = pending and pending.get('turnId') == e.get('turn_id')
            # Native API has no request tag. Association is explicitly correlation.
            origin = 'plugin-request-associated' if associated else ('codex-auto' if e.get('trigger') == 'auto' else 'user-manual')
            s['lastCompact'] = dict(origin=origin, trigger=e.get('trigger'), at=now,
                                    attribution='correlated' if associated else 'hook-trigger')
            s['compactedActivity'] = s['activity']
            s['dueAt'] = None
            s['pending'] = None
            s['manual'] = False
            s['usage'] = None
            s['blockedReason'] = 'already-compacted-this-idle-stretch'
    store.change(tid, update)
    return output


class UnixWebSocket:
    """Minimal RFC 6455 text client for Codex's private local Unix socket.

    No extensions/compression are offered; supports fragmented text and ping/pong.
    Only same-user sockets with private permissions are accepted. No TCP listener.
    """
    LIMIT = 16 * 1024 * 1024

    @classmethod
    async def connect(cls, path):
        import base64
        import hashlib
        import stat
        path = Path(path)
        if not path.is_absolute(): raise ValueError('App Server socket path must be absolute')
        metadata = path.stat()
        if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
            raise ValueError('App Server socket must be private and owned by this user')
        reader, writer = await asyncio.open_unix_connection(str(path), limit=16384)
        try:
            key = base64.b64encode(os.urandom(16)).decode('ascii')
            writer.write(('GET /rpc HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n'
                          'Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\n'
                          'Sec-WebSocket-Key: ' + key + '\r\n\r\n').encode('ascii'))
            await writer.drain()
            header = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), timeout=8)
            if len(header) > 8192: raise ValueError('oversized WebSocket handshake')
            lines = header.decode('ascii').split('\r\n')
            fields = dict(line.split(':', 1) for line in lines[1:] if ':' in line)
            fields = {k.lower(): v.strip() for k, v in fields.items()}
            expected = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode('ascii')).digest()).decode('ascii')
            if (lines[0].split(' ')[:2] != ['HTTP/1.1', '101'] or
                fields.get('sec-websocket-accept') != expected or
                fields.get('upgrade', '').lower() != 'websocket' or
                'upgrade' not in [v.strip().lower() for v in fields.get('connection', '').split(',')] or
                'sec-websocket-extensions' in fields or 'sec-websocket-protocol' in fields):
                raise ValueError('invalid or unsolicited WebSocket handshake')
            self = cls()
            self.reader, self.writer = reader, writer
            return self
        except BaseException:
            writer.close()
            with contextlib.suppress(Exception): await writer.wait_closed()
            raise

    def frame(self, opcode, payload):
        import struct
        if len(payload) > self.LIMIT: raise ValueError('oversized WebSocket message')
        n = len(payload)
        length = bytes([0x80 | n]) if n < 126 else (b'\xfe' + struct.pack('!H', n) if n < 65536 else b'\xff' + struct.pack('!Q', n))
        mask = os.urandom(4)
        self.writer.write(bytes([0x80 | opcode]) + length + mask + bytes(v ^ mask[i % 4] for i, v in enumerate(payload)))

    def send(self, text):
        self.frame(1, text.encode('utf-8'))

    async def receive(self):
        import struct
        parts, size, fragmented = [], 0, False
        while True:
            try: head = await self.reader.readexactly(2)
            except asyncio.IncompleteReadError: return None
            fin, opcode, length = bool(head[0] & 0x80), head[0] & 15, head[1] & 127
            if head[0] & 0x70 or head[1] & 0x80: raise ValueError('unsupported WebSocket server frame')
            if length == 126: length = struct.unpack('!H', await self.reader.readexactly(2))[0]
            elif length == 127: length = struct.unpack('!Q', await self.reader.readexactly(8))[0]
            if length > self.LIMIT or size + length > self.LIMIT: raise ValueError('oversized WebSocket message')
            if opcode >= 8 and (not fin or length > 125): raise ValueError('invalid WebSocket control frame')
            payload = await self.reader.readexactly(length)
            if opcode == 8:
                if len(payload) == 1: raise ValueError('invalid WebSocket close frame')
                self.frame(8, payload)
                return None
            if opcode == 9:
                self.frame(10, payload)
                continue
            if opcode == 10: continue
            if opcode not in (0, 1) or (opcode == 0) != fragmented:
                raise ValueError('invalid WebSocket text continuation')
            parts.append(payload)
            size += length
            if fin: return b''.join(parts).decode('utf-8')
            fragmented = True

    async def close(self):
        if not self.writer.is_closing():
            with contextlib.suppress(Exception):
                self.frame(8, b'\x03\xe8')
                await self.writer.drain()
            self.writer.close()
        with contextlib.suppress(Exception): await self.writer.wait_closed()


class Native:
    """Connect to an EXISTING server's documented Unix WebSocket transport."""
    def __init__(self, on_event, socket_path=None):
        self.on_event, self.seq, self.waiters = on_event, 0, {}
        self.proc, self.ws, self.socket_path = None, None, socket_path

    async def connect(self):
        home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
        path = self.socket_path or str(home / 'app-server-control/app-server-control.sock')
        self.ws = await UnixWebSocket.connect(path)
        self.reader = asyncio.create_task(self.read())
        r = await self.call('initialize', dict(clientInfo=dict(name='codex_cache', version='0.1.0')))
        self.send(dict(method='initialized', params={}))
        return r

    def send(self, msg):
        if self.ws: self.ws.send(json.dumps(msg))
        else: self.proc.stdin.write((json.dumps(msg) + '\n').encode())

    async def read(self):
        try:
            while True:
                line = await self.ws.receive() if self.ws else await self.proc.stdout.readline()
                if not line: break
                msg = json.loads(line)
                if 'id' in msg and ('result' in msg or 'error' in msg):
                    f = self.waiters.pop(msg['id'], None)
                    if f and not f.done():
                        if 'error' in msg: f.set_exception(RuntimeError(str(msg['error'])))
                        else: f.set_result(msg['result'])
                elif 'id' in msg:
                    # Never approve tools/commands on behalf of Desktop.
                    self.send(dict(id=msg['id'], error=dict(code=-32601, message='Unsupported by Codex Cache')))
                else:
                    self.on_event(msg)
        finally:
            for f in list(self.waiters.values()):
                if not f.done(): f.set_exception(RuntimeError('shared App Server disconnected'))
            self.waiters.clear()

    async def call(self, method, params):
        self.seq += 1
        f = asyncio.get_running_loop().create_future()
        self.waiters[self.seq] = f
        try:
            self.send(dict(id=self.seq, method=method, params=params))
            return await asyncio.wait_for(f, timeout=8)
        finally:
            self.waiters.pop(self.seq, None)

    async def close(self):
        if self.ws:
            await self.ws.close()
            await self.reader
        if self.proc:
            if self.proc.returncode is None:
                self.proc.terminate()
            await self.proc.wait()
            await self.reader


async def compact_candidate(store, api, tid, now=None):
    """Recheck target and CAS claim immediately before the native mutation."""
    now = time.time() if now is None else now
    cfg, s = store.settings(), store.get(tid)
    why = blocker(s, cfg, now)
    if why: return why
    generation = s['generation']
    if not await hooks_trusted(api, tid): return 'plugin-hooks-not-enabled-and-trusted'
    r = await api.call('thread/read', dict(threadId=tid, includeTurns=False))
    t = r['thread']
    if t.get('id') != tid: return 'thread-id-mismatch'
    if t.get('parentThreadId') or t.get('ephemeral') or t.get('source') not in ('cli', 'vscode', 'appServer'):
        return 'noninteractive-or-worker-thread'
    if t.get('status', {}).get('type') != 'idle': return 'native-thread-not-idle'
    if not await is_loaded(api, tid): return 'thread-not-loaded-in-shared-server'
    # Fail closed after each await, including OFF/new-activity during native reads.
    def claim(x):
        why = blocker(x, cfg, now)
        if why or x['generation'] != generation: return why or 'stale-generation'
        x['attemptedActivity'] = x['activity']
        x['pending'] = dict(generation=generation, activity=x['activity'], requestedAt=now)
        x['dueAt'] = None
        x['blockedReason'] = 'native-request-in-flight'
        return None
    why = store.change(tid, claim)
    if why: return why
    # At-most-once on timeout/error too: never retry an uncertain model mutation.
    await api.call('thread/compact/start', dict(threadId=tid))
    return 'native-request-accepted-awaiting-PostCompact'


async def is_loaded(api, tid):
    cursor = None
    while True:
        r = await api.call('thread/loaded/list', dict(cursor=cursor, limit=100))
        if tid in r['data']: return True
        cursor = r.get('nextCursor')
        if not cursor: return False


async def hooks_trusted(api, tid):
    r = await api.call('hooks/list', dict(threadId=tid))
    found = set()
    for entry in r.get('data', []):
        if entry.get('errors'): return False
        for h in entry.get('hooks', []):
            if h.get('pluginId') == 'codex-cache@codex-cache-local':
                if not h.get('enabled') or h.get('trustStatus') != 'trusted': return False
                # hooks/list uses lowerCamelCase, unlike hooks.json/stdin events.
                event = h.get('eventName', '')
                found.add(event[:1].upper() + event[1:])
    return HOOK_EVENTS <= found


def telemetry(store, msg, connection_epoch):
    p, method = msg.get('params', {}), msg.get('method')
    tid = p.get('threadId')
    s = store.get(tid) if tid else None
    if not s or not (s['enabled'] or s['manual']): return
    if method == 'thread/tokenUsage/updated':
        if p.get('turnId') != s['turnId']: return
        u = p.get('tokenUsage', {})
        def update(x):
            if p.get('turnId') == x['turnId']:
                x['usage'] = dict(tokens=u.get('last', {}).get('totalTokens'),
                    modelContextWindow=u.get('modelContextWindow'), activity=x['activity'],
                    turnId=p['turnId'], connectionEpoch=connection_epoch, source='thread/tokenUsage/updated')
        store.change(tid, update)
    elif method == 'item/completed' and p.get('item', {}).get('type') == 'contextCompaction':
        def update(x):
            x['compactedActivity'] = x['activity']
            x['dueAt'] = None
            x['usage'] = None
            x['blockedReason'] = 'native-compaction-observed'
        store.change(tid, update)


async def daemon(store):
    # flock prevents duplicate schedulers across simultaneous hooks/resume.
    with (store.root / 'daemon.lock').open('a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return
        await scheduler(store)


async def scheduler(store):
    api, subscribed, epoch, retry_at = None, set(), 0, 0
    while any(s['enabled'] or s['manual'] for s in store.all()):
        try:
            cfg = store.settings()
            if api is None:
                if time.monotonic() < retry_at:
                    await asyncio.sleep(2)
                    continue
                epoch = time.time_ns()
                # Context from an old server/connection must never authorize a mutation.
                for s in store.all():
                    if s['enabled'] or s['manual']:
                        store.change(s['threadId'], lambda x: x.update(usage=None))
                api = Native(lambda m: telemetry(store, m, epoch))
                await api.connect()
                subscribed.clear()
            for s in store.all():
                tid = s['threadId']
                if not (s['enabled'] or s['manual']):
                    if tid in subscribed:
                        await api.call('thread/unsubscribe', dict(threadId=tid))
                        subscribed.discard(tid)
                    continue
                if not await is_loaded(api, tid):
                    store.change(tid, lambda x: x.update(blockedReason='thread-not-loaded-in-shared-server', usage=None))
                    continue
                if not await hooks_trusted(api, tid):
                    store.change(tid, lambda x: x.update(blockedReason='plugin-hooks-not-enabled-and-trusted', usage=None))
                    continue
                if tid not in subscribed:
                    # Metadata-only warm resume subscribes to official token usage; never pass path,
                    # history, model or config overrides. Refuse child/hidden threads.
                    r = await api.call('thread/read', dict(threadId=tid, includeTurns=False))
                    t = r['thread']
                    if t.get('id') != tid or t.get('parentThreadId') or t.get('ephemeral') or t.get('source') not in ('cli', 'vscode', 'appServer'):
                        store.change(tid, lambda x: x.update(blockedReason='noninteractive-or-worker-thread'))
                        continue
                    r = await api.call('thread/resume', dict(threadId=tid, excludeTurns=True))
                    if r['thread']['id'] != tid: raise RuntimeError('thread-id-mismatch')
                    subscribed.add(tid)
                result = await compact_candidate(store, api, tid)
                store.change(tid, lambda x: x.update(blockedReason=result))
            store.runtime(dict(pid=os.getpid(), heartbeatAt=time.time(), transport='existing-server-unix-websocket', connected=True))
        except Exception as ex:
            if api:
                with contextlib.suppress(Exception): await api.close()
            api, subscribed = None, set()
            retry_at = time.monotonic() + 30
            store.runtime(dict(pid=os.getpid(), heartbeatAt=time.time(), connected=False,
                               blockedReason='shared-App-Server-unreachable', detail=str(ex)[:300]))
        await asyncio.sleep(2)
    if api: await api.close()
    store.runtime(dict(pid=os.getpid(), heartbeatAt=time.time(), connected=False, blockedReason='no-opted-in-threads'))


def start_daemon(store):
    log = (store.root / 'daemon.log').open('a')
    with log:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'daemon'],
            env={**os.environ, 'PLUGIN_DATA': str(store.root)}, stdin=subprocess.DEVNULL,
            stdout=log, stderr=log, start_new_session=True, close_fds=True)


def status(store, tid):
    s = store.get(tid) or fresh(tid)
    runtime = store.runtime() if store.path.exists() else {}
    cfg = store.settings()
    reason = s['blockedReason']
    if s['enabled'] or s['manual']:
        if not runtime.get('connected') or time.time() - runtime.get('heartbeatAt', 0) > 45:
            reason = 'shared-App-Server-unreachable'
    return dict(s, settings=cfg, contextPercent=context_percent(s),
                blockedReason=reason, runtime=runtime, dataDirectory=str(store.root),
                cacheWarm=None, cacheExpiresAt=None, cacheTimer='idle-policy-heuristic; not TTL detection')


def control(store, tid, command):
    store.settings()
    def update(s):
        if command == 'on':
            if not s['enabled']:
                invalidate(s)
                s['enabled'] = True
                s['adoptStop'] = True
                s['running'] = True
                # Opt-in occurs during an already-running user turn. Its Stop
                # hook supplies the actual turn id if no prompt hook observed it.
                s['blockedReason'] = 'opted-in-awaiting-current-turn-stop'
        elif command == 'off':
            invalidate(s)
            s['enabled'] = False
            s['manual'] = False
            s['adoptStop'] = False
            s['blockedReason'] = 'not-opted-in'
        elif command == 'compact':
            invalidate(s)
            s['manual'] = True
            s['adoptStop'] = True
            s['running'] = True
            s['blockedReason'] = 'manual-request-awaiting-current-turn-stop'
    store.change(tid, update)


async def doctor(tid):
    api = Native(lambda msg: None)
    try:
        await api.connect()
        loaded = await is_loaded(api, tid)
        return dict(reachable=True, currentThreadLoaded=loaded,
                    hooksTrusted=await hooks_trusted(api, tid) if loaded else False)
    except Exception as ex:
        return dict(reachable=False, blockedReason='shared-App-Server-unreachable', detail=str(ex))
    finally:
        with contextlib.suppress(Exception): await api.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['on', 'off', 'status', 'compact', 'hook', 'daemon', 'doctor'])
    args = parser.parse_args()
    os.umask(0o077)
    store = Store(data_dir())
    if args.command == 'hook':
        e = json.load(sys.stdin)
        # Cap handling to known events; never store prompts, messages or transcripts.
        tid = e.get('session_id', '')
        s = store.get(tid) if isinstance(tid, str) and IDENTITY.fullmatch(tid) else None
        out = hook(store, e)
        print(json.dumps(out))
        s = store.get(tid) if s else None
        if s and (s['enabled'] or s['manual']) and e.get('hook_event_name') in ('SessionStart', 'Stop', 'Interrupt') and not e.get('agent_id'):
            start_daemon(store)
        return
    if args.command == 'daemon':
        asyncio.run(daemon(store))
        return
    tid = os.environ.get('CODEX_THREAD_ID', '')
    if not IDENTITY.fullmatch(tid): raise ValueError('CODEX_THREAD_ID is unavailable; refusing to select another conversation')
    if args.command in ('on', 'off', 'compact'):
        store = Store(data_dir(), create=True)
        control(store, tid, args.command)
        # Stop hook starts the scheduler, after capturing this turn's identity.
    result = status(store, tid)
    if args.command == 'doctor': result['transportProbe'] = asyncio.run(doctor(tid))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        print(json.dumps(dict(error=str(exc))), file=sys.stderr)
        sys.exit(1)
