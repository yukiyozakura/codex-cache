#!/usr/bin/env python3
"""Read-only schema/plugin discovery, using a separate stdio server (never compact).
This diagnostic cannot verify Desktop's private live stdio server.
"""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('cache',root/'src/cache.py')
c=importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

async def main():
    api=c.Native(lambda m:None)
    api.proc=await asyncio.create_subprocess_exec(c.DESKTOP_CODEX,'app-server','--listen','stdio://',stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
    api.reader=asyncio.create_task(api.read())
    try:
        await api.call('initialize',dict(clientInfo=dict(name='codex_cache_readonly_diagnostic',version='0.1.0')))
        api.send(dict(method='initialized',params={}))
        for method in ['hooks/list','skills/list']:
            r=await api.call(method,dict(cwds=[str(root)],forceReload=True) if method=='skills/list' else dict(cwds=[str(root)]))
            selected=[]
            for entry in r.get('data',[]):
                field='hooks' if method=='hooks/list' else 'skills'
                selected += [v for v in entry.get(field,[]) if 'codex-cache' in json.dumps(v)]
            print(json.dumps(dict(method=method, selected=[{k:v[k] for k in ('name','eventName','enabled','trustStatus','pluginId','path') if k in v} for v in selected], diagnostics=[{k:e.get(k) for k in ('warnings','errors')} for e in r.get('data',[])] if method=='hooks/list' else None),indent=2))
    finally: await api.close()

asyncio.run(main())
