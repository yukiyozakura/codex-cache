import asyncio
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('cache',Path(__file__).resolve().parents[1]/'src/cache.py')
c=importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
A='00000000-0000-0000-0000-000000000001'
B='00000000-0000-0000-0000-000000000002'

class AlertsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=c.Store(self.tmp.name,create=True)
        self.sent=[]
    def tearDown(self):self.tmp.cleanup()
    def event(self,name,tid=A,turn='t1',now=100,**kw):
        return c.hook(self.store,dict(session_id=tid,hook_event_name=name,turn_id=turn,**kw),now)
    def ready(self,tid=A):
        c.control(self.store,tid,'on',label='Lead' if tid==A else 'Owner')
        self.event('UserPromptSubmit',tid=tid)
        self.event('Stop',tid=tid,now=110)
    def send(self,tid,label,minutes):
        self.sent.append((tid,label,minutes))
        return dict(accepted=True)
    def tick(self,now,tid=A):return asyncio.run(c.alert_candidate(self.store,tid,now,self.send))
    def test_default_is_alert_50_minutes_repeat_one_minute_and_off(self):
        cfg=self.store.settings()
        self.assertEqual((cfg['actionMode'],cfg['alertAfterMinutes'],cfg['alertRepeatMinutes'],cfg['autoCompactDefault']),('alert',50,1,'off'))
        self.assertFalse(c.status(self.store,A)['enabled'])
    def test_first_notification_at_50_minutes_then_every_minute(self):
        self.ready()
        self.assertEqual(self.store.get(A)['dueAt'],3110)
        self.assertEqual(self.tick(3109),'waiting-alert-deadline')
        self.assertEqual(self.tick(3110),'alert-submitted-waiting-repeat')
        self.assertEqual(self.sent,[(A,'Lead',50)])
        self.tick(3169)
        self.assertEqual(len(self.sent),1)
        self.tick(3170)
        self.assertEqual(len(self.sent),2)
        self.assertEqual(self.store.get(A)['dueAt'],3230)
    def test_new_activity_stops_repeat_and_restarts_fifty_minutes(self):
        self.ready();self.tick(3110)
        self.event('UserPromptSubmit',turn='t2',now=3120)
        self.assertEqual(self.tick(4000),'thread-running')
        self.event('Stop',turn='t2',now=4010)
        self.assertEqual(self.store.get(A)['dueAt'],7010)
        self.tick(7009);self.assertEqual(len(self.sent),1)
        self.tick(7010);self.assertEqual(len(self.sent),2)
    def test_off_stops_pending_and_repeat(self):
        self.ready();self.tick(3110)
        c.control(self.store,A,'off')
        self.assertEqual(self.tick(9000),'not-opted-in')
        self.assertEqual(len(self.sent),1)
        self.assertIsNone(self.store.get(A)['dueAt'])
    def test_sleep_wake_does_not_replay_missed_notifications(self):
        self.ready();self.tick(3110)
        self.tick(99999)
        self.assertEqual(len(self.sent),2)
        self.assertEqual(self.store.get(A)['dueAt'],100059)
        self.tick(99999);self.assertEqual(len(self.sent),2)
    def test_no_context_or_native_connection_required(self):
        self.ready()
        self.assertIsNone(self.store.get(A)['usage'])
        self.tick(3110)
        s=c.status(self.store,A)
        self.assertFalse(s['contextGateApplied'])
        self.assertNotEqual(s['blockedReason'],'shared-App-Server-unreachable')
        self.assertEqual(len(self.sent),1)
    def test_sessions_and_workers_do_not_mix(self):
        self.ready(A);self.ready(B)
        before=self.store.get(A)
        self.event('UserPromptSubmit',agent_id=B,agent_type='worker')
        self.assertEqual(before,self.store.get(A))
        c.control(self.store,A,'off');self.tick(3110,B)
        self.assertEqual([v[0] for v in self.sent],[B])
    def test_manual_or_auto_compact_suppresses_redundant_reminders(self):
        self.ready();self.tick(3110)
        self.event('PostCompact',turn='c1',trigger='manual',now=3120)
        self.assertEqual(self.tick(4000),'already-compacted-this-idle-stretch')
        self.assertEqual(len(self.sent),1)
    def test_alert_policy_refuses_native_manual_compact_command(self):
        with self.assertRaises(ValueError):c.control(self.store,A,'compact')
        self.assertIsNone(self.store.get(A))
    def test_recheck_after_claim_cancels_stale_generation(self):
        self.ready()
        original=self.store.get
        count=0
        def racing_get(tid):
            nonlocal count
            count+=1
            if count==2:self.event('UserPromptSubmit',turn='new',now=3110)
            return original(tid)
        with patch.object(self.store,'get',side_effect=racing_get):self.tick(3110)
        self.assertEqual(self.sent,[])
        self.assertTrue(original(A)['running'])
    def test_permission_failure_is_visible_and_retries_only_next_minute(self):
        self.ready()
        def denied(*args):return dict(error='notification-permission-not-authorized')
        self.assertEqual(asyncio.run(c.alert_candidate(self.store,A,3110,denied)),'notification-permission-not-authorized')
        self.assertEqual(self.store.get(A)['alertCount'],0)
        self.assertEqual(self.tick(3111),'waiting-alert-deadline')
        self.tick(3170);self.assertEqual(len(self.sent),1)
    def test_registry_restart_retains_on_and_repeat_deadline(self):
        self.ready();self.tick(3110)
        reopened=c.Store(self.tmp.name)
        self.assertTrue(reopened.get(A)['enabled'])
        self.assertEqual(reopened.get(A)['dueAt'],3170)
        self.event('SessionStart',source='resume',now=3120)
        self.assertIsNone(reopened.get(A)['dueAt'])
        self.assertTrue(reopened.get(A)['enabled'])

if __name__=='__main__':unittest.main()
