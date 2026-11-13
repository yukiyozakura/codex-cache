#!/usr/bin/env python3
"""Install using Codex's supported plugin CLI; never edit trust state."""
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
codex = '/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex'
# Install an allowlisted runtime package, excluding .git, local config backups,
# test artifacts, original Claude adapters, and unrelated developer material.
package = root / 'dist' / 'plugin'
if package.exists():
    shutil.rmtree(package)
package.mkdir(parents=True)
for name in ['.codex-plugin', 'hooks', 'skills', 'src', 'LICENSE', 'NOTICE', 'README.md']:
    source = root / name
    if source.is_dir():
        shutil.copytree(source, package / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    else:
        shutil.copy2(source, package / name)
config = home / 'config.toml'
backup = root / 'local-setup' / ('config-before-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '.toml')
backup.parent.mkdir(mode=0o700, exist_ok=True)
if config.exists():
    shutil.copy2(config, backup)
    backup.chmod(0o600)
    print('Config backup:', backup)
for args in [['plugin', 'marketplace', 'add', str(root), '--json'],
             ['plugin', 'add', 'codex-cache@codex-cache-local', '--json'],
             ['plugin', 'list', '--marketplace', 'codex-cache-local', '--json']]:
    subprocess.run([codex] + args, check=True)
sys.dont_write_bytecode = True
sys.path.insert(0, str(root / 'src'))
import cache
cache.Store(cache.data_dir(), create=True)  # defaults only, zero opted-in threads
print('Installed. Review Codex Cache in Desktop Settings > Hooks; restart Desktop to reload the plugin.')
