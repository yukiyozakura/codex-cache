"""Public native macOS notification helper. Never invokes AppleScript/UI automation."""
import json
from pathlib import Path
import subprocess


def helper():
    return Path.home() / 'Applications/Codex Cache Alerts.app/Contents/MacOS/CodexCacheAlerts'


def call(command, payload=None):
    path = helper()
    if not path.is_file():
        return dict(error='notification-helper-not-installed')
    try:
        r = subprocess.run([str(path), command], input=json.dumps(payload or {}),
                           text=True, capture_output=True, timeout=10)
        result = json.loads(r.stdout) if r.stdout.strip() else dict(error=r.stderr.strip()[:300] or 'notification-helper-failed')
        if r.returncode and 'error' not in result: result['error'] = 'notification-helper-failed'
        return result
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        return dict(error=str(error))


def send_alert(thread_id, label, idle_minutes):
    return call('notify', dict(threadId=thread_id, label=label, idleMinutes=idle_minutes))
