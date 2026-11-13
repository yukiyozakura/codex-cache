#!/usr/bin/env python3
"""Probe official multi-client Unix transport in an isolated temporary Codex home.
Never reads/resumes an existing thread or invokes a model. Not a Desktop E2E test.
"""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True
root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cache', root / 'src/cache.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


async def proxy(socket, env):
    client = c.Native(lambda msg: None, socket_path=str(socket))
    try:
        await client.connect()
        return client
    except BaseException:
        await client.close()
        raise


async def main():
    with tempfile.TemporaryDirectory(prefix='codex-cache-transport-') as tmp:
        home = Path(tmp)
        socket = home / 'shared.sock'
        env = {**os.environ, 'CODEX_HOME': str(home)}
        server = await asyncio.create_subprocess_exec(c.DESKTOP_CODEX,
            '-c', 'features.code_mode_host=false', '-c', 'features.apps=false',
            '-c', 'features.plugins=false', '-c', 'features.remote_plugin=false',
            'app-server', '--listen', 'unix://' + str(socket),
            env=env, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        clients = []
        try:
            for _ in range(100):
                if socket.exists(): break
                if server.returncode is not None: raise RuntimeError('isolated server exited')
                await asyncio.sleep(0.05)
            if not socket.exists(): raise RuntimeError('isolated server did not open its socket')
            for _ in range(2): clients.append(await proxy(socket, env))
            results = await asyncio.gather(*(client.call('thread/loaded/list', dict(limit=100)) for client in clients))
            if any(r.get('data') for r in results): raise RuntimeError('unexpected loaded threads in isolated home')
            print(json.dumps(dict(isolatedHome=True, transport='Native Unix WebSocket (RFC 6455 handshake and frames)',
                concurrentClients=len(clients), loadedThreads=[r['data'] for r in results],
                submittedModelTurns=0, desktopAttached=False,
                conclusion='Native shared transport works; this does not establish Desktop attachment.'), indent=2))
        finally:
            for client in clients: await client.close()
            if server.returncode is None: server.terminate()
            try: await asyncio.wait_for(server.wait(), timeout=5)
            except asyncio.TimeoutError:
                server.kill()
                await server.wait()


if __name__ == '__main__': asyncio.run(main())
