import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('cache', Path(__file__).resolve().parents[1] / 'src/cache.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
A = '00000000-0000-0000-0000-000000000001'
B = '00000000-0000-0000-0000-000000000002'

class FakeAPI:
    def __init__(self, tid=A, status='idle', before=None, **thread):
        self.tid, self.status, self.before, self.extra = tid, status, before, thread
        self.calls = []
    async def call(self, method, params):
        self.calls.append((method, params))
        if self.before: self.before(method)
        if method == 'thread/read':
            return {'thread': dict(id=self.tid, status={'type':self.status}, source='appServer', parentThreadId=None, ephemeral=False, **self.extra)}
        if method == 'thread/loaded/list': return dict(data=[self.tid], nextCursor=None)
        if method == 'hooks/list': return dict(data=[dict(hooks=[dict(pluginId='codex-cache@codex-cache-local', eventName=e[:1].lower()+e[1:], enabled=True, trustStatus='trusted') for e in c.HOOK_EVENTS])])
        return {}

class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = c.Store(self.tmp.name, create=True)
    def tearDown(self): self.tmp.cleanup()
    def event(self, name, tid=A, turn='t1', now=100, **kw):
        return c.hook(self.store, dict(session_id=tid, hook_event_name=name, turn_id=turn, **kw), now)
    def ready(self, tid=A, percent=25):
        c.control(self.store, tid, 'on')
        self.event('UserPromptSubmit', tid=tid)
        self.event('Stop', tid=tid, now=110)
        c.telemetry(self.store, dict(method='thread/tokenUsage/updated', params=dict(threadId=tid, turnId='t1', tokenUsage=dict(last=dict(totalTokens=percent*100), modelContextWindow=10000))), 1)
    def test_default_off_does_not_write_or_call(self):
        before = self.store.path.stat().st_mtime_ns
        self.event('UserPromptSubmit')
        self.event('Stop')
        self.assertIsNone(self.store.get(A))
        self.assertEqual(before, self.store.path.stat().st_mtime_ns)
    def test_off_without_registry_creates_nothing(self):
        root = Path(self.tmp.name) / 'absent'
        c.hook(c.Store(root), dict(session_id=A, hook_event_name='Stop'))
        self.assertFalse(root.exists())
    def test_only_on_thread_compacts(self):
        self.ready()
        api = FakeAPI()
        self.assertIsNone(c.blocker(self.store.get(A), c.DEFAULTS, 3410))
        self.assertEqual(asyncio.run(c.compact_candidate(self.store, api, A, 3410)), 'native-request-accepted-awaiting-PostCompact')
        self.assertEqual(api.calls[-1], ('thread/compact/start', {'threadId': A}))
        self.assertIsNone(self.store.get(B))
    def test_activity_invalidates_and_resets_timer(self):
        self.ready()
        gen = self.store.get(A)['generation']
        self.event('UserPromptSubmit', turn='t2', now=200)
        s = self.store.get(A)
        self.assertGreater(s['generation'], gen)
        self.assertIsNone(s['dueAt'])
        self.assertIsNone(s['usage'])
        self.event('Stop', turn='t1', now=205)
        self.assertIsNone(self.store.get(A)['dueAt'])
        self.event('Stop', turn='t2', now=220)
        self.assertEqual(self.store.get(A)['dueAt'], 3520)
    def test_off_cancels_timer(self):
        self.ready()
        c.control(self.store, A, 'off')
        s = self.store.get(A)
        self.assertIsNone(s['dueAt'])
        self.assertEqual(c.blocker(s, c.DEFAULTS, 9000), 'not-opted-in')
    def test_external_compact_blocks_until_new_user_activity(self):
        for trigger, origin in [('manual','user-manual'),('auto','codex-auto')]:
            self.ready()
            self.event('PostCompact', trigger=trigger)
            self.event('Stop')
            self.assertEqual(self.store.get(A)['lastCompact']['origin'], origin)
            self.assertEqual(c.blocker(self.store.get(A), c.DEFAULTS, 9000), 'already-compacted-this-idle-stretch')
            self.event('SessionStart', source='resume')
            self.assertEqual(self.store.get(A)['compactedActivity'], self.store.get(A)['activity'])
            self.event('UserPromptSubmit', turn='new')
            self.event('Stop', turn='new')
            s=self.store.get(A)
            self.assertNotEqual(s['activity'],s['compactedActivity'])
            self.assertIsNotNone(s['dueAt'])
    def test_one_attempt_even_when_ack_or_completion_missing(self):
        self.ready()
        api=FakeAPI()
        asyncio.run(c.compact_candidate(self.store,api,A,3410))
        self.assertEqual(asyncio.run(c.compact_candidate(self.store,api,A,9999)), 'already-attempted-this-idle-stretch')
        self.assertEqual(sum(m=='thread/compact/start' for m,p in api.calls),1)
    def test_two_threads_stay_independent(self):
        self.ready(A)
        self.ready(B, 30)
        self.event('UserPromptSubmit', tid=A, turn='t2')
        self.assertTrue(self.store.get(A)['running'])
        self.assertFalse(self.store.get(B)['running'])
        api=FakeAPI(B)
        asyncio.run(c.compact_candidate(self.store,api,B,3410))
        self.assertEqual(api.calls[-1][1], {'threadId':B})
        self.assertIsNone(self.store.get(A)['attemptedActivity'])
    def test_workers_sharing_parent_id_have_no_effect(self):
        self.ready()
        before = self.store.get(A)
        for event in ['UserPromptSubmit','PreCompact','PostCompact','SessionStart','Stop']:
            self.event(event, agent_id=B, agent_type='worker')
        self.assertEqual(before,self.store.get(A))
    def test_thread_id_mismatch_active_and_hidden_refused(self):
        for api, reason in [(FakeAPI(B),'thread-id-mismatch'),(FakeAPI(status='active'),'native-thread-not-idle')]:
            self.ready()
            self.assertEqual(asyncio.run(c.compact_candidate(self.store,api,A,3410)),reason)
            self.assertFalse(any(m=='thread/compact/start' for m,p in api.calls))
        self.ready()
        api=FakeAPI()
        api.extra={'source':'exec'}
        # Build a hidden/worker response without duplicate dict keywords.
        async def call(method,params):
            if method=='hooks/list': return dict(data=[dict(hooks=[dict(pluginId='codex-cache@codex-cache-local', eventName=e, enabled=True, trustStatus='trusted') for e in c.HOOK_EVENTS])])
            return {'thread':dict(id=A,status={'type':'idle'},source='exec')}
        api.call=call
        self.assertEqual(asyncio.run(c.compact_candidate(self.store,api,A,3410)),'noninteractive-or-worker-thread')
    def test_context_is_exact_native_usage_or_skip(self):
        self.ready(percent=19.9)
        self.assertEqual(c.context_percent(self.store.get(A)),19.9)
        self.assertEqual(c.blocker(self.store.get(A),c.DEFAULTS,3410),'below-minimum-context')
        self.ready(percent=20)
        self.assertIsNone(c.blocker(self.store.get(A),c.DEFAULTS,3410))
        self.store.change(A,lambda s:s.update(usage=None))
        self.assertEqual(c.blocker(self.store.get(A),c.DEFAULTS,3410),'official-context-telemetry-unavailable')
    def test_race_off_or_activity_during_native_read(self):
        for action in ['off','activity']:
            self.ready()
            def race(method):
                if method=='thread/read':
                    if action=='off': c.control(self.store,A,'off')
                    else: self.event('UserPromptSubmit',turn='new')
            api=FakeAPI(before=race)
            asyncio.run(c.compact_candidate(self.store,api,A,3410))
            self.assertFalse(any(m=='thread/compact/start' for m,p in api.calls))
    def test_delayed_native_request_vetoed_after_off(self):
        self.ready()
        asyncio.run(c.compact_candidate(self.store,FakeAPI(),A,3410))
        c.control(self.store,A,'off')
        result=self.event('PreCompact',turn='compact-turn',trigger='manual')
        self.assertFalse(result['continue'])
    def test_plugin_attribution_and_manual_never_opt_in(self):
        self.ready()
        asyncio.run(c.compact_candidate(self.store,FakeAPI(),A,3410))
        self.event('PreCompact',turn='compact-turn',trigger='manual')
        self.event('PostCompact',turn='compact-turn',trigger='manual')
        self.assertEqual(self.store.get(A)['lastCompact']['origin'],'plugin-request-associated')
        c.control(self.store,B,'compact')
        self.assertFalse(self.store.get(B)['enabled'])
    def test_process_restart_and_resume_preserve_opt_in(self):
        self.ready()
        reopened=c.Store(self.tmp.name)
        self.assertTrue(reopened.get(A)['enabled'])
        self.event('SessionStart',source='resume')
        s=reopened.get(A)
        self.assertTrue(s['enabled'])
        self.assertIsNone(s['dueAt'])
        self.assertIsNone(s['usage'])
    def test_one_minute_configuration_and_reject_global_on(self):
        path=Path(self.tmp.name)/'settings.json'
        path.write_text(json.dumps(dict(c.DEFAULTS,compactAfterMinutes=1)))
        self.ready()
        self.assertEqual(self.store.get(A)['dueAt'],170)
        path.write_text(json.dumps(dict(c.DEFAULTS,autoCompactDefault='on')))
        with self.assertRaises(ValueError): self.store.settings()
    def test_on_during_existing_turn_adopts_stop(self):
        c.control(self.store,A,'on')
        self.event('Stop',turn='existing-turn')
        s=self.store.get(A)
        self.assertEqual(s['turnId'],'existing-turn')
        self.assertEqual(s['dueAt'],3400)
    def test_off_hook_subprocess_no_network_or_daemon(self):
        path=Path(self.tmp.name)/'empty'
        r=subprocess.run([sys.executable,str(Path(c.__file__)),'hook'],input=json.dumps(dict(session_id=B,hook_event_name='Stop')),text=True,capture_output=True,env={**os.environ,'PLUGIN_DATA':str(path)})
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads(r.stdout),{})
        self.assertFalse(path.exists())
    def test_status_default_off(self):
        self.assertFalse(c.status(self.store,A)['enabled'])

    def test_untrusted_or_missing_hooks_prevent_native_request(self):
        self.ready()
        api=FakeAPI()
        async def missing(method,params): return dict(data=[])
        api.call=missing
        self.assertEqual(asyncio.run(c.compact_candidate(self.store,api,A,3410)),'plugin-hooks-not-enabled-and-trusted')

class SchedulerTests(unittest.TestCase):
    setUp = PolicyTests.setUp
    tearDown = PolicyTests.tearDown
    ready = PolicyTests.ready
    event = PolicyTests.event
    # Exercise the actual daemon loop and its advisory lock, not just the predicate.
    def test_daemon_dispatches_one_candidate_and_exits_when_off(self):
        self.ready()
        self.store.change(A, lambda s:s.update(dueAt=0))
        calls=[]
        store=self.store
        class MockNative(FakeAPI):
            def __init__(self, event):
                super().__init__()
                self.event=event
            async def connect(self):
                self.event(dict(method='thread/tokenUsage/updated',params=dict(threadId=A,turnId='t1',tokenUsage=dict(last=dict(totalTokens=2500),modelContextWindow=10000))))
            async def close(self): pass
            async def call(self,method,params):
                calls.append((method,params))
                if method=='thread/resume': return dict(thread=dict(id=A))
                if method=='thread/compact/start':
                    c.control(store,A,'off')
                    return {}
                return await super().call(method,params)
        original=c.Native
        try:
            c.Native=MockNative
            asyncio.run(asyncio.wait_for(c.daemon(store),timeout=5))
        finally: c.Native=original
        self.assertEqual(sum(m=='thread/compact/start' for m,p in calls),1)
        self.assertFalse(store.get(A)['enabled'])

if __name__=='__main__': unittest.main()
