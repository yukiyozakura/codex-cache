#!/usr/bin/env python3
"""Build a local notification helper with Apple's public UserNotifications API."""
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
target = Path.home() / 'Applications' / 'Codex Cache Alerts.app'
with tempfile.TemporaryDirectory(prefix='codex-cache-build-') as tmp:
    app = Path(tmp) / target.name
    binary = app / 'Contents' / 'MacOS' / 'CodexCacheAlerts'
    binary.parent.mkdir(parents=True)
    info = dict(CFBundleIdentifier='io.github.yukiyozakura.codex-cache-alerts',
                CFBundleName='Codex Cache Alerts', CFBundleDisplayName='Codex Cache Alerts',
                CFBundleExecutable='CodexCacheAlerts', CFBundlePackageType='APPL',
                CFBundleShortVersionString='0.2.0', CFBundleVersion='2',
                LSUIElement=True, LSMinimumSystemVersion='12.0')
    with (app/'Contents'/'Info.plist').open('wb') as f: plistlib.dump(info, f)
    subprocess.run(['/usr/bin/swiftc', '-O', '-module-cache-path', str(Path(tmp)/'module-cache'),
        str(root/'native/Alerts.swift'), '-o', str(binary), '-framework', 'AppKit', '-framework', 'UserNotifications'], check=True)
    subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(app)], check=True)
    target.parent.mkdir(exist_ok=True)
    if target.exists():
        # This exact helper path is owned by this project; never overwrite another bundle.
        with (target/'Contents'/'Info.plist').open('rb') as f: old = plistlib.load(f)
        if old.get('CFBundleIdentifier') != info['CFBundleIdentifier']: raise RuntimeError('unexpected app at helper destination')
        shutil.rmtree(target)
    shutil.copytree(app, target)
print(target)
subprocess.run(['/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister', '-f', str(target)], check=True)
subprocess.run([str(target/'Contents/MacOS/CodexCacheAlerts'), 'status'], check=True, timeout=10)
