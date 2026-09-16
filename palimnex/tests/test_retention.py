from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from palimnex import durable as d, retention as r
from palimnex.tests.support import PROJECT_ID, write_project

class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);write_project(self.root)
        self.base=d.MemoryLedger(self.root/'.private/memory.sqlite3',project_id=PROJECT_ID,project_slug='memory-fixture',root=self.root)
        self.sid=self.base.start_session('retention trial')['session_id']
        self.eid=self.base.append_event(self.sid,'fact',subject='violet',payload={'value':'violet temporary detail'},retention='session')['event_id']
        self.base.close_session(self.sid,outcome='finished')
        self.before=self.base.status()['logical_digest']
        r.migrate(self.base,expected_digest=self.before)
        self.ledger=r.as_retention(self.base)
        self.policy={'schema':r.POLICY,'policy_id':'local','version':1,'mode':'manual','clock':'tx_at',
                     'rules':[{'retention':'session','kinds':['fact'],'ttl_seconds':0}],
                     'grace_after_close_seconds':0,'plan_ttl_seconds':3600}
        self.key=b'k'*32
    def activate(self):self.ledger.activate_policy(self.policy,actor='operator',reason='test policy')
    def apply(self,p):return self.ledger.apply(p,confirm_digest=p['plan_digest'],key=self.key,actor='operator',reason='expiry test')
    def test_unconfigured_no_deletion_and_old_reader_refuses(self):
        before=self.ledger.status()['logical_digest'];p=self.ledger.propose()
        self.assertEqual(p['status'],'refused');self.assertEqual(p['affected'],[])
        self.assertEqual(before,self.ledger.status()['logical_digest'])
        with self.assertRaisesRegex(ValueError,'unsupported'):self.base.status()
    def test_forget_retry_compaction_and_fresh_reader(self):
        self.activate();p=self.ledger.propose();self.assertEqual([x['event_id'] for x in p['affected']],[self.eid])
        result=self.apply(p);self.assertEqual(result['status'],'applied')
        reopened=r.open_ledger(self.base)
        self.assertEqual(reopened.recall('violet')['results'],[])
        self.assertEqual(reopened.status()['integrity'],'ok');self.assertEqual(reopened.status()['semantic_errors'],[])
        digest=reopened.status()['logical_digest'];self.assertTrue(self.apply(p)['idempotent'])
        self.assertEqual(reopened.status()['logical_digest'],digest)
        self.assertNotIn(b'violet temporary detail',self.ledger.path.read_bytes())
        event=next(x for x in reopened.logical_document()['events'] if x['event_id']==self.eid)
        self.assertTrue(event['payload']['forgotten'])
    def test_holds_and_release_invalidate(self):
        self.activate();p=self.ledger.propose()
        hold=self.ledger.hold([self.eid],actor='operator',reason='preserve')
        self.assertIn('preservation_hold',[x['reason'] for x in self.ledger.propose()['exclusions']])
        with self.assertRaisesRegex(ValueError,'STALE_PLAN'):self.apply(p)
        self.ledger.release(hold['hold_id'],actor='operator',reason='release')
        with self.assertRaisesRegex(ValueError,'STALE_PLAN'):self.apply(p)
        self.apply(self.ledger.propose())
    def test_pin_session_restart_and_close_invalidate(self):
        self.activate();p=self.ledger.propose();sid=self.ledger.start_session('review')['session_id']
        self.ledger.pin(sid,[self.eid]);self.assertEqual(self.ledger.propose(event_ids=[self.eid])['exclusions'][0]['reason'],'active_session')
        self.ledger.close_session(sid,outcome='done')
        with self.assertRaisesRegex(ValueError,'STALE_PLAN'):self.apply(p)
        self.apply(self.ledger.propose(event_ids=[self.eid]))
    def test_pack_and_dependency_exclusion(self):
        self.activate();self.ledger.register_pack('a'*32,[self.eid],'b'*64)
        p=self.ledger.propose(event_ids=[self.eid]);self.assertEqual(p['exclusions'][0]['reason'],'pack_sealed')
        sid=self.ledger.start_session('correction')['session_id']
        e=self.ledger.append_event(sid,'correction',subject='violet',payload={'new':'fixed'},retention='session',supersedes=self.eid)['event_id']
        self.ledger.close_session(sid,outcome='done');p=self.ledger.propose(event_ids=[self.eid,e])
        self.assertEqual(p['affected'],[])
        self.assertTrue(any(x['effect']=='withdraw' and x['kind']=='temporal_relation' for x in p['dependencies']))
    def test_policy_change_and_tampering_refuse(self):
        self.activate();p=self.ledger.propose();p['affected']=[]
        with self.assertRaisesRegex(ValueError,'DIGEST_MISMATCH'):self.apply(p)
        p['plan_digest']=r.digest({k:v for k,v in p.items() if k!='plan_digest'})
        with self.assertRaisesRegex(ValueError,'STALE_PLAN'):self.apply(p)
        p=self.ledger.propose();self.policy['version']=2;self.activate()
        with self.assertRaisesRegex(ValueError,'STALE_PLAN'):self.apply(p)
    def test_ttl_and_clock_rollback(self):
        self.activate();p=self.ledger.propose()
        with patch('palimnex.retention.d.now_ms',return_value=p['expires_at']+1):
            with self.assertRaisesRegex(ValueError,'PLAN_EXPIRED'):self.apply(p)
    def test_transaction_rollback_and_resume_compaction(self):
        self.activate();p=self.ledger.propose();before=self.ledger.status()['logical_digest']
        with patch.object(self.ledger,'_write_event_graph',side_effect=RuntimeError('crash')):
            with self.assertRaises(RuntimeError):self.apply(p)
        self.assertEqual(self.ledger.status()['logical_digest'],before)
        with patch.object(self.ledger,'finalize',side_effect=RuntimeError('power loss')):
            with self.assertRaises(RuntimeError):self.apply(p)
        self.assertEqual(self.apply(p)['status'],'compaction_pending')
        self.assertEqual(self.ledger.finalize(p['plan_digest'])['status'],'applied')
    def test_durable_requires_authorization_and_policy_unknown_refused(self):
        self.activate();p=self.ledger.propose()
        self.assertEqual(len([x for x in p['exclusions'] if x['reason']=='protected_audit_log']),2)
        bad={**self.policy,'rules':[{'retention':'durable','kinds':['fact'],'ttl_seconds':0}]}
        with self.assertRaises(ValueError):r.validate_policy(bad)

    def test_explicit_durable_erasure_leaves_only_non_content_audit_residue(self):
        sid=self.ledger.start_session('durable private prompt')['session_id']
        event=self.ledger.append_event(sid,'decision',subject='durable private subject',
            payload={'decision':'durable private payload'},retention='durable')['event_id']
        self.ledger.close_session(sid,outcome='durable private outcome')
        self.activate()
        refused=self.ledger.propose(event_ids=[event])
        self.assertEqual(refused['exclusions'][0]['reason'],'authorization_required')
        with self.assertRaisesRegex(ValueError,'pseudonymous'):
            self.ledger.authorize_erasure([event],authorized_by='Named Person',
                policy_id='local',reason_code='AUTHORIZED_ERASURE')
        authorization=self.ledger.authorize_erasure([event],authorized_by='privacy-officer-7',
            policy_id='local',reason_code='AUTHORIZED_ERASURE')
        plan=self.ledger.propose(event_ids=[event])
        self.assertEqual(plan['affected'][0]['authorization_id'],authorization['authorization_id'])
        receipt=self.apply(plan)
        self.assertEqual(receipt['operation'],'erased')
        self.assertEqual(receipt['record_classes'][event],'durable')
        self.assertEqual(receipt['authorized_by'],['privacy-officer-7'])
        self.assertEqual(receipt['reason_codes'],['AUTHORIZED_ERASURE'])
        self.assertEqual(receipt['verification_status'],'verified')
        self.assertTrue(receipt['record_commitments'][event].startswith('hmac-sha256:'))
        raw=self.ledger.path.read_bytes()
        for secret in (b'durable private prompt',b'durable private subject',
                       b'durable private payload',b'durable private outcome'):
            self.assertNotIn(secret,raw)
        with self.ledger.connection(create=False) as c:
            row=c.execute('SELECT kind FROM events WHERE event_id=?',(bytes.fromhex(event),)).fetchone()
            self.assertEqual(row['kind'],d.EVENT_KINDS['evidence'])
            for table in ('event_terms','evidence','verifications','verification_attempts','promotions','workflows'):
                self.assertEqual(c.execute(f'SELECT count(*) FROM {table} WHERE event_id=?',(bytes.fromhex(event),)).fetchone()[0],0)

    def test_imported_source_requires_allowed_explicit_reason(self):
        from palimnex import portable
        source=d.MemoryLedger(self.root/'.private/import-source.sqlite3',project_id=PROJECT_ID,project_slug='memory-fixture',root=self.root)
        sid=source.start_session('import private prompt')['session_id']
        imported=source.append_event(sid,'fact',subject='import private subject',
            payload={'value':'import private payload'},retention='durable')['event_id']
        source.close_session(sid,outcome='import private outcome')
        pack=self.root/'.private/import-source.pmem';pack_key=bytes(range(32))
        portable.export_pack(source,pack,pack_key)
        target=d.MemoryLedger(self.root/'.private/import-target.sqlite3',project_id=PROJECT_ID,project_slug='memory-fixture',root=self.root)
        portable.import_pack(target,pack,pack_key,activate=True)
        r.migrate(target,expected_digest=target.status()['logical_digest'])
        ledger=r.as_retention(target);ledger.activate_policy(self.policy,actor='operator',reason='test policy')
        with self.assertRaisesRegex(ValueError,'reason code'):
            ledger.authorize_erasure([imported],authorized_by='connector-7',policy_id='local',reason_code='AUTHORIZED_ERASURE')
        authorization=ledger.authorize_erasure([imported],authorized_by='connector-7',policy_id='local',reason_code='SOURCE_DELETED')
        plan=ledger.propose(event_ids=[imported])
        self.assertEqual(plan['affected'][0]['record_class'],'imported_source')
        receipt=ledger.apply(plan,confirm_digest=plan['plan_digest'],key=self.key,actor='operator',reason='source deletion')
        self.assertEqual(receipt['reason_codes'],['SOURCE_DELETED'])
        for secret in (b'import private prompt',b'import private subject',b'import private payload',b'import private outcome'):
            self.assertNotIn(secret,ledger.path.read_bytes())

    def test_derived_support_recomputes_or_withdraws(self):
        sid=self.ledger.start_session('support trial')['session_id']
        source_a=self.ledger.append_event(sid,'fact',subject='source a',payload={'value':'source alpha'},retention='session')['event_id']
        source_b=self.ledger.append_event(sid,'fact',subject='source b',payload={'value':'source beta'},retention='session')['event_id']
        retained=self.ledger.append_event(sid,'fact',subject='retained derivative',payload={'value':'retained derivative'},retention='session')['event_id']
        withdrawn=self.ledger.append_event(sid,'fact',subject='withdrawn derivative',payload={'value':'withdrawn derivative'},retention='session')['event_id']
        self.ledger.close_session(sid,outcome='done');self.activate()
        sources=[{'event_id':source_a,'confidence':.9},{'event_id':source_b,'confidence':.8}]
        self.ledger.register_support(retained,sources,threshold=.7)
        self.ledger.register_support(withdrawn,sources,threshold=.85)
        plan=self.ledger.propose(event_ids=[source_a])
        self.assertIn(withdrawn,[x['event_id'] for x in plan['affected']])
        self.assertNotIn(retained,[x['event_id'] for x in plan['affected']])
        effects={(x['event_id'],x['effect']) for x in plan['dependencies']}
        self.assertIn((retained,'recompute'),effects);self.assertIn((withdrawn,'withdraw'),effects)
        self.apply(plan)
        self.assertTrue(self.ledger.recall('retained derivative')['results'])
        recalled={x['event_id'] for x in self.ledger.recall('withdrawn derivative')['results']}
        self.assertNotIn(withdrawn,recalled)
        with self.ledger.connection(create=False) as c:
            support=self.ledger._state(c)['supports'][retained]
        self.assertEqual([x['event_id'] for x in support['sources']],[source_b])

    def test_projected_or_managed_copy_blocks_erasure(self):
        self.activate()
        with self.ledger.connection(create=False,write=True) as c:
            c.execute('UPDATE projection_outbox SET attempted_at=?,delivered_at=? WHERE event_id=?',(d.now_ms(),d.now_ms(),bytes.fromhex(self.eid)))
        plan=self.ledger.propose(event_ids=[self.eid])
        self.assertEqual(plan['affected'],[])
        self.assertIn('store_not_adapted',[x['reason'] for x in plan['exclusions']])

    def test_v2_plan_contract_and_tombstone_match_draft_2020_12_schemas(self):
        from jsonschema import Draft202012Validator
        schema_root=Path(r.__file__).parent/'schemas'
        load=lambda name:json.loads((schema_root/name).read_text())
        self.activate();plan=self.ledger.propose(event_ids=[self.eid])
        for name,value in (
            ('deletion-contract.v2.schema.json',plan['contract']),
            ('cleanup-plan.v2.schema.json',plan),
        ):
            schema=load(name);Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema).validate(value)
        self.apply(plan)
        with self.ledger.connection(create=False) as c:
            receipt=self.ledger._state(c)['erased'][plan['plan_digest']]
        schema=load('erasure-tombstone.v1.schema.json')
        Draft202012Validator.check_schema(schema);Draft202012Validator(schema).validate(receipt)
    def test_import_cannot_replace_deletion_registry(self):
        from palimnex.portable import recover_import
        self.activate();self.apply(self.ledger.propose())
        with self.assertRaisesRegex(ValueError,'deletion-registry'):recover_import(self.ledger)
        with self.assertRaisesRegex(ValueError,'deletion-registry'):self.ledger.restore_untrusted_document({},source_logical_digest='a'*64,authenticated=True)
    def test_actual_packed_bytes_and_survivor_graph_identity(self):
        with self.ledger.connection(create=False) as c:
            row=c.execute('SELECT payload,subject_digest FROM events WHERE event_id=?',(bytes.fromhex(self.eid),)).fetchone()
            packed=bytes(row['payload']);subject=bytes(row['subject_digest'])
            survivors={r['node_id']:tuple(r) for r in c.execute('SELECT * FROM nodes WHERE created_event_id!=?',(bytes.fromhex(self.eid),))}
        self.assertIn(packed,self.ledger.path.read_bytes())
        self.activate();self.apply(self.ledger.propose())
        for suffix in ('','-wal','-shm'):
            path=Path(str(self.ledger.path)+suffix)
            if path.exists():
                self.assertNotIn(packed,path.read_bytes());self.assertNotIn(subject,path.read_bytes())
        with self.ledger.connection(create=False) as c:
            after={r['node_id']:tuple(r) for r in c.execute('SELECT * FROM nodes')}
        for key,value in survivors.items():self.assertEqual(after[key],value)
    def test_stale_object_import_and_recovery_blocked(self):
        from palimnex import portable
        # Build a valid pack for this root, then attempt replacement using pre-migration object.
        source=d.MemoryLedger(self.root/'.private/source.sqlite3',project_id=PROJECT_ID,project_slug='memory-fixture',root=self.root)
        sid=source.start_session('export source')['session_id']
        source.append_event(sid,'fact',subject='export',payload={'value':'exported'},retention='durable')
        source.close_session(sid,outcome='done')
        path=self.root/'.private/old.pmem';key=bytes(range(32));portable.export_pack(source,path,key)
        before=self.ledger.status()['logical_digest']
        with self.assertRaisesRegex(ValueError,'deletion-registry'):
            portable.import_pack(self.base,path,key,activate=True,replace=True)
        self.assertEqual(before,self.ledger.status()['logical_digest'])
    def test_current_read_pins_records_atomically(self):
        self.activate()
        sid=self.ledger.start_session('reader')['session_id']
        # Audit reads with an explicit active reader session scope only that session;
        # current reads can pull shared durable history and pin it.
        durable_id=self.ledger.append_event(sid,'fact',subject='shared cobalt',payload={'value':'shared'},retention='durable')['event_id']
        result=self.ledger.recall('shared',session_id=sid,visibility='current')
        self.assertIn(durable_id,[r['event_id'] for r in result['results']])
        with self.ledger.connection(create=False) as c:self.assertTrue(any(durable_id in p['events'] for p in self.ledger._state(c)['pins']))
    def test_recovery_checks_actual_schema_when_marker_missing(self):
        from palimnex import portable
        candidate=d.MemoryLedger(self.root/'.private/recovery.candidate',project_id=PROJECT_ID,project_slug='memory-fixture',root=self.root)
        sid=candidate.start_session('candidate')['session_id'];candidate.close_session(sid,outcome='done')
        with candidate.file_lock(exclusive=True):portable._checkpoint_for_replace(candidate)
        portable._write_intent(portable._intent_path(self.base),{'schema':portable.INTENT_SCHEMA,
            'live':str(self.base.path),'candidate':str(candidate.path),'backup':str(self.root/'.private/recovery.backup'),
            'logical_sha256':candidate.logical_digest()})
        Path(str(self.ledger.path)+'.retention-v2').unlink()
        before=self.ledger.status()['logical_digest']
        with self.assertRaisesRegex(ValueError,'deletion-registry'):portable.recover_import(self.base)
        self.assertEqual(self.ledger.status()['logical_digest'],before)
    def test_process_exit_rolls_back_or_leaves_resumable_receipt(self):
        import subprocess,sys
        self.activate();p=self.ledger.propose();before=self.ledger.status()['logical_digest']
        script='''
import json,os,sys
from pathlib import Path
from palimnex.retention import RetentionLedger
from palimnex.tests.support import PROJECT_ID
root=Path(sys.argv[1]);ledger=RetentionLedger(root/'.private/memory.sqlite3',project_id=PROJECT_ID,project_slug='memory-fixture',root=root)
plan=json.loads(sys.stdin.read())
if sys.argv[2]=='transaction': ledger._write_event_graph=lambda *a,**k:os._exit(17)
else: ledger.finalize=lambda *a,**k:os._exit(18)
ledger.apply(plan,confirm_digest=plan['plan_digest'],key=b'k'*32,actor='child',reason='crash trial')
'''
        result=subprocess.run([sys.executable,'-c',script,str(self.root),'transaction'],input=json.dumps(p),text=True)
        self.assertEqual(result.returncode,17);self.assertEqual(self.ledger.status()['logical_digest'],before)
        result=subprocess.run([sys.executable,'-c',script,str(self.root),'finalize'],input=json.dumps(p),text=True)
        self.assertEqual(result.returncode,18);self.assertEqual(self.apply(p)['status'],'compaction_pending')
        self.assertEqual(self.ledger.finalize(p['plan_digest'])['status'],'applied')
