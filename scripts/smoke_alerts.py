#!/usr/bin/env python3
"""Real one-minute timer + one-minute repeat against the Mac notification API.
Only a synthetic ID in a temporary registry is opted in; no Codex thread/API call.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid
sys.dont_write_bytecode = True
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'src'))
import cache
from notifier import call

permission = call('status')
if permission.get('authorization') not in ('authorized', 'provisional'):
    raise SystemExit('Notification permission required before smoke test: ' + json.dumps(permission))
with tempfile.TemporaryDirectory(prefix='codex-cache-alert-test-') as tmp:
    store = cache.Store(tmp, create=True)
    (Path(tmp)/'settings.json').write_text(json.dumps(dict(cache.DEFAULTS, alertAfterMinutes=1, alertRepeatMinutes=1)))
    tid = str(uuid.uuid4())
    cache.control(store, tid, 'on', label='通知動作確認（テスト）')
    began = time.monotonic()
    cache.hook(store, dict(session_id=tid, hook_event_name='UserPromptSubmit', turn_id='test-turn'))
    cache.hook(store, dict(session_id=tid, hook_event_name='Stop', turn_id='test-turn'))
    process = subprocess.Popen([sys.executable, str(root/'src/cache.py'), 'daemon'],
                               env={**os.environ, 'PLUGIN_DATA':tmp},
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    observed = 0
    arrivals = []
    try:
        while time.monotonic()-began < 145:
            if process.poll() is not None: raise RuntimeError('scheduler exited: ' + process.stderr.read())
            s = store.get(tid)
            count = s.get('alertCount',0)
            if count > observed:
                observed = count
                arrivals.append(s['lastAlert']['at'])
                print(json.dumps(dict(alert=count, elapsedSeconds=round(time.monotonic()-began,2), lastAlert=s['lastAlert'])), flush=True)
            if count >= 2: break
            time.sleep(0.25)
        if observed < 2: raise RuntimeError('did not observe first and repeated notification')
        cache.control(store, tid, 'off')
        process.wait(timeout=5)
        delivered = call('list')
        has_entry = any(v['id']=='codex-cache.'+tid for v in delivered.get('delivered',[]))
        print(json.dumps(dict(passed=True, repeatSeconds=round(arrivals[1]-arrivals[0],2),
            macOSDeliveredEntry=has_entry, stoppedAfterOff=process.returncode==0,
            productionRegistryChanged=False, submittedModelTurns=0)), flush=True)
    finally:
        if process.poll() is None:
            cache.control(store,tid,'off')
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate();process.wait(timeout=5)
        process.stderr.close()
