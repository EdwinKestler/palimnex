"""Explicit, local SQLite retention profile. No scheduled or remote erasure."""
from __future__ import annotations
import hashlib
import hmac
import json
import re
import secrets
import os
from pathlib import Path
from typing import Any
from . import durable as d
from .security import scan_text

SCHEMA = 'project-memory:retention-ledger:v2'
POLICY = 'project-memory:retention-policy:v1'
PLAN = 'project-memory:cleanup-plan:v2'
CONTRACT = {'schema': 'project-memory:deletion-contract:v2', 'mode': 'forget',
            'digest_kind': 'hmac-sha256', 'keep_tombstone': True,
            'audit_residue': 'non-reconstructive-hash-chained-tombstone',
            'derived_data': 'recompute-or-withdraw',
            'caches': 'require-verified-invalidation',
            'packs': 'require-verified-retirement',
            'security_audit_log': 'protected'}
SQL = '''CREATE TABLE retention_control (
 sequence INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload BLOB NOT NULL,
 previous_digest TEXT NOT NULL, digest TEXT NOT NULL UNIQUE);'''
COLUMNS = ('sequence', 'kind', 'payload', 'previous_digest', 'digest')
KINDS = {'migration', 'policy', 'hold', 'release', 'pin', 'pack', 'authorization',
         'support', 'support_recomputed', 'erased', 'compacted', 'invalid'}
IMPORTED_REASON_CODES = {
    'RETENTION_EXPIRED', 'SOURCE_DELETED', 'SOURCE_SYNCHRONIZATION',
    'PRIVACY_REQUEST', 'LEGAL_ERASURE',
}
DURABLE_REASON_CODES = {'AUTHORIZED_ERASURE', 'PRIVACY_REQUEST', 'LEGAL_ERASURE'}
ERASURE_SCOPE = [
    'source_payload', 'provenance_payloads', 'graph_nodes', 'relationships',
    'embeddings', 'indexes', 'local_projection_outbox',
]

def digest(value):
    return hashlib.sha256(d.canonical_json(value)).hexdigest()

def checked_text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError('invalid '+label)
    if scan_text(value):
        raise ValueError('sensitive '+label)
    return value

def identifier(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{32}', value):
        raise ValueError('invalid record identifier')
    return value

def actor_identifier(value):
    checked_text(value,'actor identifier')
    if not re.fullmatch('[a-z0-9][a-z0-9._:-]{0,127}',value):
        raise ValueError('authorized actor must be a pseudonymous machine identifier')
    return value

def validate_policy(p):
    fields = {'schema','policy_id','version','mode','clock','rules','grace_after_close_seconds','plan_ttl_seconds'}
    if not isinstance(p, dict) or set(p) != fields or p['schema'] != POLICY:
        raise ValueError('invalid retention policy fields')
    checked_text(p['policy_id'], 'policy_id')
    if len(p['policy_id']) > 128 or type(p['version']) is not int or p['version'] < 1:
        raise ValueError('invalid policy identity/version')
    if p['mode'] != 'manual' or p['clock'] != 'tx_at':
        raise ValueError('only manual tx_at policy is supported')
    for field in ('grace_after_close_seconds','plan_ttl_seconds'):
        if type(p[field]) is not int or p[field] < 0:
            raise ValueError('invalid duration')
    if not 1 <= p['plan_ttl_seconds'] <= 86400:
        raise ValueError('invalid plan TTL')
    if not isinstance(p['rules'], list) or len(p['rules']) > 128:
        raise ValueError('invalid rules')
    for rule in p['rules']:
        if not isinstance(rule,dict) or set(rule) != {'retention','kinds','ttl_seconds'}:
            raise ValueError('invalid expiry rule')
        if rule['retention'] not in ('volatile','session') or type(rule['ttl_seconds']) is not int or rule['ttl_seconds'] < 0:
            raise ValueError('invalid expiry class/duration')
        if not isinstance(rule['kinds'],list) or not rule['kinds'] or any(not isinstance(k,str) or k not in d.EVENT_KINDS or k.startswith('session_') for k in rule['kinds']) or len(set(rule['kinds'])) != len(rule['kinds']):
            raise ValueError('invalid expiry kinds')
    return p

class RetentionLedger(d.MemoryLedger):
    schema = SCHEMA
    pin_reads = True
    table_columns = {**d.TABLE_COLUMNS, 'retention_control': COLUMNS}

    def initialize(self):
        if not self.path.exists():
            raise ValueError('explicit retention-migrate required')
        return self.status()

    def _controls(self,c):
        result=[]; previous='0'*64
        for seq,row in enumerate(c.execute('SELECT * FROM retention_control ORDER BY sequence'),1):
            payload=json.loads(row['payload'])
            expected=digest([seq,row['kind'],payload,previous])
            if row['sequence'] != seq or row['kind'] not in KINDS or row['previous_digest'] != previous or row['digest'] != expected or d.canonical_json(payload) != row['payload']:
                raise ValueError('retention control integrity failed')
            result.append({'kind':row['kind'],'payload':payload,'digest':expected,
                           'previous_digest':previous})
            previous=expected
        if not result or result[0]['kind'] != 'migration':
            raise ValueError('missing retention migration record')
        return result

    def _record(self,c,kind,payload):
        last=c.execute('SELECT sequence,digest FROM retention_control ORDER BY sequence DESC LIMIT 1').fetchone()
        seq=last['sequence']+1 if last else 1; previous=last['digest'] if last else '0'*64
        c.execute('INSERT INTO retention_control VALUES(?,?,?,?,?)',
                  (seq,kind,d.canonical_json(payload),previous,digest([seq,kind,payload,previous])))

    def _semantic_errors(self,c):
        errors=super()._semantic_errors(c)
        try:
            controls=self._controls(c)
            forgotten={eid for e in controls if e['kind']=='erased' for eid in e['payload']['events']}
            for row in c.execute('SELECT event_id FROM events WHERE event_id NOT IN (SELECT event_id FROM event_terms)'):
                if row['event_id'].hex() not in forgotten:raise ValueError('non-tombstone lacks terms')
            for entry in controls:
                p=entry['payload']
                if entry['kind']=='policy': validate_policy(p['policy'])
                if entry['kind']=='authorization':
                    if set(p)!={'authorization_id','events','authorized_by','policy_id','reason_code','requested_at','expires_at'}:
                        raise ValueError('invalid authorization')
                    identifier(p['authorization_id']);self._ids(p['events'])
                    actor_identifier(p['authorized_by']);checked_text(p['policy_id'],'policy_id')
                    if p['reason_code'] not in IMPORTED_REASON_CODES|DURABLE_REASON_CODES or type(p['requested_at']) is not int or type(p['expires_at']) is not int or p['expires_at']<=p['requested_at']:
                        raise ValueError('invalid authorization')
                if entry['kind'] in ('support','support_recomputed'):
                    if set(p)!={'fact_event_id','sources','threshold','aggregation','recorded_at'} or p['aggregation']!='max':
                        raise ValueError('invalid support control')
                    identifier(p['fact_event_id'])
                    if type(p['threshold']) not in (int,float) or not 0<=p['threshold']<=1 or type(p['recorded_at']) is not int:
                        raise ValueError('invalid support control')
                    for source in p['sources']:
                        if set(source)!={'event_id','confidence'} or not 0<=source['confidence']<=1:raise ValueError('invalid support control')
                        identifier(source['event_id'])
                if entry['kind']=='erased':
                    if p.get('previous_audit_hash') != entry.get('previous_digest'):
                        raise ValueError('deletion receipt breaks audit continuity')
                    required={'receipt_id','plan_digest','events','record_classes','operation','requested_at','completed_at',
                              'authorized_by','policy_id','reason_codes','scope',
                              'affected_artifact_count','verification_status',
                              'previous_audit_hash','legal_hold_exceptions',
                              'record_commitments','derived','authority','authorizes_actions'}
                    if set(p)!=required or p['verification_status']!='verified' or p['scope']!=ERASURE_SCOPE:
                        raise ValueError('invalid deletion receipt')
                    if p['operation']!='erased' or p['completed_at']<p['requested_at'] or p['affected_artifact_count']<1:
                        raise ValueError('invalid deletion receipt')
                    for eid in p['events']:
                        row=c.execute('SELECT kind,payload,terms_digest FROM events WHERE event_id=?',(bytes.fromhex(eid),)).fetchone()
                        if row is None or row['kind']!=d.EVENT_KINDS['evidence'] or d.unpack_payload(row['payload']) != {'forgotten':True,'receipt_id':p['receipt_id']} or row['terms_digest'] != d._term_set_digest([],allow_empty=True):
                            raise ValueError('tombstone differs from deletion receipt')
                        if eid not in p['record_classes'] or eid not in p['record_commitments'] or not re.fullmatch('hmac-sha256:[0-9a-f]{64}',p['record_commitments'][eid]):
                            raise ValueError('tombstone lacks record commitment')
                        for table in ('event_terms','evidence','verifications','verification_attempts','promotions','workflows'):
                            if c.execute(f'SELECT 1 FROM {table} WHERE event_id=?',(bytes.fromhex(eid),)).fetchone():
                                raise ValueError('tombstone retained reconstructive derivative')
            state=self._state(c)
            for fact_id,support in state['supports'].items():
                if fact_id not in forgotten and any(x['event_id'] in forgotten for x in support['sources']):
                    raise ValueError('retained derived fact still names forgotten support')
        except (ValueError,KeyError,TypeError,json.JSONDecodeError):
            errors.append('retention control or tombstone validation failed')
        return errors

    def _logical_digest(self,c):
        return digest([super()._logical_digest(c),self._controls(c)])

    def _state(self,c):
        controls=self._controls(c); policy=None; holds={}; pins=[]; packs={}; authorizations={}; supports={}; erased={}; compacted=set(); invalid=set()
        for entry in controls:
            p=entry['payload']; k=entry['kind']
            if k=='policy': policy=p['policy']
            elif k=='hold': holds[p['hold_id']]=p
            elif k=='release': holds.pop(p['hold_id'],None)
            elif k=='pin': pins.append(p)
            elif k=='pack': packs[p['pack_id']]=p
            elif k=='authorization': authorizations[p['authorization_id']]=p
            elif k in ('support','support_recomputed'): supports[p['fact_event_id']]=p
            elif k=='erased': erased[p['plan_digest']]=p
            elif k=='compacted': compacted.add(p['plan_digest'])
            elif k=='invalid': invalid.add(p['plan_digest'])
        return dict(controls=controls,policy=policy,holds=holds,pins=pins,packs=packs,
                    authorizations=authorizations,supports=supports,erased=erased,
                    compacted=compacted,invalid=invalid)

    def retention_status(self):
        with self.connection(create=False) as c:
            s=self._state(c)
            return {'configured':s['policy'] is not None,'policy':s['policy'],
                    'policy_digest':digest(s['policy']), 'ledger_digest':self._logical_digest(c),
                    'pending_compaction':sorted(set(s['erased'])-s['compacted']),
                    'automatic_deletion':False, 'schema':SCHEMA}

    def activate_policy(self,p,*,actor,reason):
        validate_policy(p); checked_text(actor,'actor');checked_text(reason,'reason')
        with self.connection(create=False,write=True) as c:
            s=self._state(c)
            versions=[e['payload']['policy']['version'] for e in s['controls'] if e['kind']=='policy']
            if versions and p['version'] <= max(versions): raise ValueError('policy version must increase')
            self._record(c,'policy',{'policy':p,'actor':actor,'reason':reason})
        return self.retention_status()

    def hold(self,event_ids,*,actor,reason):
        checked_text(actor,'actor');checked_text(reason,'reason')
        ids=self._ids(event_ids)
        with self.connection(create=False,write=True) as c:
            self._exist(c,ids); hid=secrets.token_hex(16)
            self._record(c,'hold',{'hold_id':hid,'events':ids,'actor':actor,'reason':reason})
        return {'hold_id':hid,'events':ids}

    def release(self,hold_id,*,actor,reason):
        identifier(hold_id);checked_text(actor,'actor');checked_text(reason,'reason')
        with self.connection(create=False,write=True) as c:
            if hold_id not in self._state(c)['holds']: raise ValueError('unknown active hold')
            self._record(c,'release',{'hold_id':hold_id,'actor':actor,'reason':reason})
        return {'released':hold_id}

    def pin(self,session_id,event_ids):
        identifier(session_id);ids=self._ids(event_ids)
        with self.connection(create=False,write=True) as c:
            self._exist(c,ids)
            session=c.execute('SELECT status FROM sessions WHERE session_id=?',(bytes.fromhex(session_id),)).fetchone()
            if session is None or session['status']!=1: raise ValueError('pin requires active session')
            self._record(c,'pin',{'session_id':session_id,'events':ids})
        return {'session_id':session_id,'events':ids}

    def _pin_read_tx(self,c,session_id,event_ids):
        if not event_ids:return
        row=c.execute('SELECT status FROM sessions WHERE session_id=?',(bytes.fromhex(session_id),)).fetchone()
        if row is None or row['status'] != 1:return
        existing={eid for pin in self._state(c)['pins'] if pin['session_id']==session_id for eid in pin['events']}
        new=sorted(set(event_ids)-existing)
        if new:self._record(c,'pin',{'session_id':session_id,'events':new})

    @staticmethod
    def _ids(ids):
        if not isinstance(ids,list) or not ids or len(ids)>1000:raise ValueError('expected 1..1000 record IDs')
        return sorted(set(identifier(x) for x in ids))

    @staticmethod
    def _exist(c,ids):
        if any(c.execute('SELECT 1 FROM events WHERE event_id=?',(bytes.fromhex(e),)).fetchone() is None for e in ids):
            raise ValueError('unknown event')

    def register_pack(self,pack_id,event_ids,pack_digest):
        identifier(pack_id);ids=self._ids(event_ids)
        if not isinstance(pack_digest,str) or not re.fullmatch('[0-9a-f]{64}',pack_digest):raise ValueError('invalid pack digest')
        with self.connection(create=False,write=True) as c:
            self._exist(c,ids)
            if pack_id in self._state(c)['packs']:raise ValueError('pack already registered')
            self._record(c,'pack',{'pack_id':pack_id,'events':ids,'digest':pack_digest})
        return {'registered':pack_id,'deletion_behavior':'exclude'}

    def authorize_erasure(self,event_ids,*,authorized_by,policy_id,reason_code,expires_at=None):
        """Record explicit, expiring authority; this never erases by itself."""
        actor_identifier(authorized_by);checked_text(policy_id,'policy_id')
        ids=self._ids(event_ids)
        now=d.now_ms(); expiry=now+3600_000 if expires_at is None else expires_at
        if type(expiry) is not int or expiry <= now or expiry > now+86400_000:
            raise ValueError('authorization expiry must be within 24 hours')
        if reason_code not in IMPORTED_REASON_CODES|DURABLE_REASON_CODES:
            raise ValueError('invalid erasure reason code')
        with self.connection(create=False,write=True) as c:
            s=self._state(c)
            if s['policy'] is None or s['policy']['policy_id'] != policy_id:
                raise ValueError('authorization must name the active retention policy')
            self._exist(c,ids)
            rows=c.execute('SELECT hex(event_id) event_id,kind,retention,import_batch_id FROM events WHERE event_id IN ('+','.join('?' for _ in ids)+')',tuple(bytes.fromhex(x) for x in ids)).fetchall()
            for row in rows:
                if row['kind'] in (d.EVENT_KINDS['session_started'],d.EVENT_KINDS['session_closed']):
                    raise ValueError('session audit anchors are protected')
                imported=row['import_batch_id'] is not None
                allowed=IMPORTED_REASON_CODES if imported else DURABLE_REASON_CODES
                if row['retention'] != d.RETENTION_CODES['durable'] and not imported:
                    raise ValueError('explicit authorization is only for durable or imported records')
                if reason_code not in allowed:
                    raise ValueError('reason code is not allowed for this record class')
            aid=secrets.token_hex(16)
            payload={'authorization_id':aid,'events':ids,'authorized_by':authorized_by,
                     'policy_id':policy_id,'reason_code':reason_code,
                     'requested_at':now,'expires_at':expiry}
            self._record(c,'authorization',payload)
        return {**payload,'operation':'authorized','automatic_deletion':False}

    def register_support(self,fact_event_id,sources,*,threshold):
        """Bind a derived fact to independently scored source-event support."""
        fact=identifier(fact_event_id)
        if type(threshold) not in (int,float) or isinstance(threshold,bool) or not 0 <= threshold <= 1:
            raise ValueError('support threshold must be between zero and one')
        if not isinstance(sources,list) or not sources or len(sources)>1000:
            raise ValueError('support requires one or more sources')
        normalized=[]
        for item in sources:
            if not isinstance(item,dict) or set(item)!={'event_id','confidence'}:
                raise ValueError('invalid source support')
            source=identifier(item['event_id']); confidence=item['confidence']
            if source==fact or type(confidence) not in (int,float) or isinstance(confidence,bool) or not 0 <= confidence <= 1:
                raise ValueError('invalid source support')
            normalized.append({'event_id':source,'confidence':float(confidence)})
        normalized=sorted(normalized,key=lambda x:x['event_id'])
        if len({x['event_id'] for x in normalized})!=len(normalized):
            raise ValueError('duplicate source support')
        ids=[fact,*[x['event_id'] for x in normalized]]
        with self.connection(create=False,write=True) as c:
            self._exist(c,ids)
            row=c.execute('SELECT kind FROM events WHERE event_id=?',(bytes.fromhex(fact),)).fetchone()
            if row['kind']!=d.EVENT_KINDS['fact']:
                raise ValueError('only fact events may register derived support')
            payload={'fact_event_id':fact,'sources':normalized,'threshold':float(threshold),
                     'aggregation':'max','recorded_at':d.now_ms()}
            self._record(c,'support',payload)
        return payload

    def propose(self,*,event_ids=None,at=None):
        if event_ids is not None:event_ids=self._ids(event_ids)
        with self.connection(create=False) as c:
            return self._propose(c,event_ids, d.now_ms() if at is None else at)

    def _propose(self,c,ids,at):
        if type(at) is not int or at < 0:raise ValueError('invalid time')
        s=self._state(c);p=s['policy'];affected=[];exclusions=[];dependencies=[];packs=[]
        bindings={'ledger_digest':self._logical_digest(c),'policy_digest':digest(p),
                  'hold_set_digest':digest(s['holds']),'session_pin_digest':digest([s['pins'],[[r[0],r[1],r[2],bool(p and (r[1]==1 or at < r[2]+p['grace_after_close_seconds']*1000))] for r in c.execute('SELECT hex(session_id),status,ended_at FROM sessions ORDER BY session_id')]]),
                  'pack_manifest_digest':digest(s['packs']),
                  'authorization_digest':digest(s['authorizations']),
                  'support_digest':digest(s['supports']),
                  'control_digest':s['controls'][-1]['digest']}
        if ids is not None:self._exist(c,ids)
        rows=c.execute('SELECT e.*,s.status,s.ended_at FROM events e JOIN sessions s USING(session_id) ORDER BY e.event_id').fetchall()
        by_id={r['event_id'].hex():r for r in rows}
        forgotten={e for receipt in s['erased'].values() for e in receipt['events']}
        authorization_by_event={}
        for authorization in s['authorizations'].values():
            if authorization['expires_at'] >= at and p is not None and authorization['policy_id']==p['policy_id']:
                for event_id in authorization['events']:
                    authorization_by_event[event_id]=authorization
        roots=[]
        for r in rows:
            eid=r['event_id'].hex()
            if ids is not None and eid not in ids:continue
            reason=None
            if p is None:reason='policy_unconfigured'
            elif any(eid in h['events'] for h in s['holds'].values()):reason='preservation_hold'
            elif r['status']==1 or at < r['ended_at']+p['grace_after_close_seconds']*1000:reason='active_session'
            elif any(eid in pin['events'] and self._session_pinned(c,pin['session_id'],at,p) for pin in s['pins']):reason='active_session'
            elif eid in forgotten:reason='already_erased'
            elif r['kind'] in (d.EVENT_KINDS['session_started'],d.EVENT_KINDS['session_closed']):reason='protected_audit_log'
            elif r['import_batch_id'] is not None or r['retention']==d.RETENTION_CODES['durable']:
                authorization=authorization_by_event.get(eid)
                if authorization is None or ids is None:reason='authorization_required'
                else:
                    imported=r['import_batch_id'] is not None
                    allowed=IMPORTED_REASON_CODES if imported else DURABLE_REASON_CODES
                    if authorization['reason_code'] not in allowed:reason='authorization_required'
            else:
                rule=next((x for x in p['rules'] if d.RETENTION_NAMES[r['retention']]==x['retention'] and d.EVENT_KIND_NAMES[r['kind']] in x['kinds']),None)
                if rule is None or at < r['observed_at']+rule['ttl_seconds']*1000:reason='not_expired'
            if reason:exclusions.append({'event_id':eid,'reason':reason})
            else:roots.append(eid)
        # A temporal assertion chain is content-dependent. Erase it as one unit so
        # removal of a correction cannot resurrect its predecessor.
        closure=set(roots);causes={eid:{'kind':'requested','source_event_id':eid} for eid in roots}
        changed=True
        while changed:
            changed=False
            for row in rows:
                eid=row['event_id'].hex()
                linked=[x.hex() for x in (row['supersedes_event_id'],row['contradicts_event_id']) if x]
                if eid in closure or any(target in closure for target in linked):
                    for candidate in [eid,*linked]:
                        if candidate not in closure:
                            closure.add(candidate);causes[candidate]={'kind':'temporal_dependency','source_event_id':eid}
                            dependencies.append({'event_id':candidate,'effect':'withdraw','kind':'temporal_relation','source_event_id':eid})
                            changed=True
            for fact_id,support in s['supports'].items():
                removed=[x for x in support['sources'] if x['event_id'] in closure]
                if not removed or fact_id in closure:continue
                remaining=[x for x in support['sources'] if x['event_id'] not in closure]
                confidence=max((x['confidence'] for x in remaining),default=0.0)
                if not remaining or confidence < support['threshold']:
                    closure.add(fact_id);causes[fact_id]={'kind':'unsupported_derived','source_event_id':removed[0]['event_id']}
                    dependencies.append({'event_id':fact_id,'effect':'withdraw','kind':'derived_support','source_event_id':removed[0]['event_id'],
                                         'remaining_confidence':confidence,'threshold':support['threshold']})
                    changed=True
                else:
                    dependencies.append({'event_id':fact_id,'effect':'recompute','kind':'derived_support','source_event_id':removed[0]['event_id'],
                                         'remaining_confidence':confidence,'threshold':support['threshold']})
        dependencies=[json.loads(value) for value in sorted({d.canonical_json(item).decode() for item in dependencies})]
        blockers=[]
        for eid in sorted(closure):
            row=by_id[eid]
            if row['kind'] in (d.EVENT_KINDS['session_started'],d.EVENT_KINDS['session_closed']):
                blockers.append({'event_id':eid,'reason':'protected_audit_log'})
            elif any(eid in h['events'] for h in s['holds'].values()):blockers.append({'event_id':eid,'reason':'preservation_hold'})
            elif row['status']==1 or (p and at < row['ended_at']+p['grace_after_close_seconds']*1000):blockers.append({'event_id':eid,'reason':'active_session'})
            elif c.execute('SELECT 1 FROM projection_outbox WHERE event_id=? AND attempted_at IS NOT NULL',(row['event_id'],)).fetchone():blockers.append({'event_id':eid,'reason':'store_not_adapted'})
            elif any(eid in pack['events'] for pack in s['packs'].values()):
                blockers.append({'event_id':eid,'reason':'pack_sealed'})
                packs.extend({'pack_id':k,'event_id':eid,'decision':'require_verified_retirement'} for k,pack in s['packs'].items() if eid in pack['events'])
        if blockers:
            exclusions.extend(blockers)
            for eid in roots:
                if not any(x['event_id']==eid for x in blockers):exclusions.append({'event_id':eid,'reason':'dependency_guard'})
            closure.clear()
        for eid in sorted(closure):
            row=by_id[eid];authorization=authorization_by_event.get(eid)
            if authorization is None and causes[eid]['kind']!='requested':
                source=causes[eid]['source_event_id'];authorization=authorization_by_event.get(source)
                if authorization is None and roots:authorization=authorization_by_event.get(roots[0])
            affected.append({'event_id':eid,'action':'forget','record_class':('imported_source' if row['import_batch_id'] is not None else d.RETENTION_NAMES[row['retention']]),
                             'cause':causes[eid],
                             'authorization_id':authorization['authorization_id'] if authorization else None,
                             'logical_bytes':len(row['payload']),
                             'stores':['sqlite_payload','sqlite_provenance','sqlite_terms','sqlite_graph','sqlite_relationships','sqlite_workflows','sqlite_outbox']})
        if p is None:exclusions=[{'event_id':'*','reason':'policy_unconfigured'}]
        plan={'schema':PLAN,'project_id':self.project_id_text,'status':'proposed' if p else 'refused',
              'proposed_at':at,'expires_at':at+(p['plan_ttl_seconds'] if p else 3600)*1000,
              'scope':ids,'bindings':bindings,'contract':CONTRACT,'affected':affected,'exclusions':exclusions,
              'dependencies':dependencies,'packs':packs,'bytes':{'recoverable_now':0,
              'logical_payload_bytes':sum(x['logical_bytes'] for x in affected),'recoverable_after_compact':None},
              'caveats':['backups_out_of_band','model_context_not_in_scope','receipt_log_not_in_scope',
                         'unregistered_copies_out_of_band','filesystem_erasure_not_proven',
                         'sqlite_free_pages_until_vacuum']}
        plan['plan_digest']=digest(plan)
        return plan

    @staticmethod
    def _session_pinned(c,sid,at,p):
        r=c.execute('SELECT status,ended_at FROM sessions WHERE session_id=?',(bytes.fromhex(sid),)).fetchone()
        return r is None or r['status']==1 or at < r['ended_at']+p['grace_after_close_seconds']*1000

    def apply(self,plan,*,confirm_digest,key,actor,reason):
        actor_identifier(actor);checked_text(reason,'reason')
        if not isinstance(key,bytes) or len(key)!=32:raise ValueError('forget key must contain 32 bytes')
        if not isinstance(plan,dict):raise ValueError('invalid plan')
        pd=plan.get('plan_digest');body={k:v for k,v in plan.items() if k!='plan_digest'}
        if pd!=confirm_digest or pd!=digest(body):raise ValueError('DIGEST_MISMATCH')
        failure=None;receipt=None
        with self.connection(create=False,write=True) as c:
            s=self._state(c)
            if pd in s['invalid']:raise ValueError('STALE_PLAN')
            if pd in s['erased']:
                return {**s['erased'][pd],'status':'applied' if pd in s['compacted'] else 'compaction_pending','idempotent':True}
            now=d.now_ms()
            fresh=self._propose(c,plan.get('scope'),plan.get('proposed_at'))
            current=self._propose(c,plan.get('scope'),now)
            if plan != fresh or plan['project_id'] != self.project_id_text:failure='STALE_PLAN'
            elif plan['status']!='proposed':failure='POLICY_NOT_CONFIGURED'
            elif now>plan['expires_at'] or now<plan['proposed_at']:failure='PLAN_EXPIRED'
            elif current['bindings']!=plan['bindings'] or current['affected']!=plan['affected']:failure='STALE_PLAN'
            elif not plan['affected']:failure='NOTHING_TO_ERASE'
            if failure:
                self._record(c,'invalid',{'plan_digest':pd,'reason':failure})
            else:
                affected_by_id={x['event_id']:x for x in plan['affected']}
                authorizations={x['authorization_id']:s['authorizations'][x['authorization_id']]
                                for x in plan['affected'] if x['authorization_id']}
                requested_at=min((x['requested_at'] for x in authorizations.values()),default=plan['proposed_at'])
                reason_codes=sorted({x['reason_code'] for x in authorizations.values()} or {'RETENTION_EXPIRED'})
                receipt={'receipt_id':secrets.token_hex(16),'plan_digest':pd,
                         'events':[x['event_id'] for x in plan['affected']],
                         'record_classes':{x['event_id']:x['record_class'] for x in plan['affected']},
                         'operation':'erased',
                         'requested_at':requested_at,'completed_at':now,
                         'authorized_by':sorted({x['authorized_by'] for x in authorizations.values()} or {actor}),
                         'policy_id':s['policy']['policy_id'],'reason_codes':reason_codes,
                         'scope':ERASURE_SCOPE,'affected_artifact_count':0,
                         'verification_status':'verified',
                         'previous_audit_hash':s['controls'][-1]['digest'],
                         'legal_hold_exceptions':[], 'record_commitments':{},
                         'derived':[x for x in plan['dependencies'] if x['effect'] in ('withdraw','recompute')],
                         'authority':'historical_only','authorizes_actions':False}
                # Secure-delete applies to canonical pages; VACUUM/checkpoint finalize local files separately.
                c.execute('PRAGMA secure_delete=ON')
                for eid in receipt['events']:
                    row=c.execute('SELECT * FROM events WHERE event_id=?',(bytes.fromhex(eid),)).fetchone()
                    receipt['record_commitments'][eid]='hmac-sha256:'+hmac.new(key,row['record_digest'],hashlib.sha256).hexdigest()
                    packed,payload_digest=d.pack_payload({'forgotten':True,'receipt_id':receipt['receipt_id']})
                    terms=d._term_set_digest([],allow_empty=True);subject=hashlib.sha256(b'forgotten\0'+row['event_id']).digest()
                    record=d._event_record_digest(row['project_id'],row['session_id'],row['event_id'],row['sequence'],d.EVENT_KINDS['evidence'],subject,terms,row['observed_at'],row['valid_from'],None,None,row['claimed_trust'],row['sensitivity'],d.RETENTION_CODES['durable'],payload_digest,row['import_batch_id'])
                    for table in ('event_terms','evidence','verifications','verification_attempts','promotions'):
                        receipt['affected_artifact_count']+=c.execute(f'DELETE FROM {table} WHERE event_id=?',(row['event_id'],)).rowcount
                    workflows=c.execute('SELECT workflow_id FROM workflows WHERE event_id=?',(row['event_id'],)).fetchall()
                    for workflow in workflows:
                        receipt['affected_artifact_count']+=c.execute('DELETE FROM workflow_steps WHERE workflow_id=?',(workflow['workflow_id'],)).rowcount
                    receipt['affected_artifact_count']+=c.execute('DELETE FROM workflows WHERE event_id=?',(row['event_id'],)).rowcount
                    for table,target in (('supersessions','predecessor_event_id'),('contradictions','opposed_event_id')):
                        receipt['affected_artifact_count']+=c.execute(f'DELETE FROM {table} WHERE assertion_event_id=? OR {target}=?',(row['event_id'],row['event_id'])).rowcount
                    receipt['affected_artifact_count']+=c.execute('UPDATE events SET kind=?,payload=?,payload_digest=?,subject_digest=?,terms_digest=?,supersedes_event_id=NULL,contradicts_event_id=NULL,retention=?,record_digest=? WHERE event_id=?',
                        (d.EVENT_KINDS['evidence'],packed,payload_digest,subject,terms,d.RETENTION_CODES['durable'],record,row['event_id'])).rowcount
                # Session prompts/outcomes can themselves disclose erased content. Keep
                # their durable audit anchors, but scrub payloads and retrieval terms.
                session_ids={c.execute('SELECT session_id FROM events WHERE event_id=?',(bytes.fromhex(eid),)).fetchone()['session_id'] for eid in receipt['events']}
                for session_id in session_ids:
                    session_payload,session_digest=d.pack_payload({'task':'forgotten session'})
                    receipt['affected_artifact_count']+=c.execute('UPDATE sessions SET task_payload=?,task_digest=? WHERE session_id=?',(session_payload,session_digest,session_id)).rowcount
                    for anchor in c.execute('SELECT * FROM events WHERE session_id=? AND kind IN (?,?)',(session_id,d.EVENT_KINDS['session_started'],d.EVENT_KINDS['session_closed'])).fetchall():
                        payload={'task':'forgotten session'} if anchor['kind']==d.EVENT_KINDS['session_started'] else {'outcome':'forgotten session'}
                        packed,payload_digest=d.pack_payload(payload)
                        term_values=d._term_digests({'subject':'forgotten session','payload':payload,
                                                    'kind':d.EVENT_KIND_NAMES[anchor['kind']]})
                        terms=d._term_set_digest(term_values)
                        receipt['record_commitments'][anchor['event_id'].hex()]='hmac-sha256:'+hmac.new(key,anchor['record_digest'],hashlib.sha256).hexdigest()
                        record=d._event_record_digest(anchor['project_id'],anchor['session_id'],anchor['event_id'],anchor['sequence'],anchor['kind'],anchor['subject_digest'],terms,anchor['observed_at'],anchor['valid_from'],None,None,anchor['claimed_trust'],anchor['sensitivity'],anchor['retention'],payload_digest,anchor['import_batch_id'])
                        for table in ('event_terms','evidence','verifications','verification_attempts','promotions'):
                            receipt['affected_artifact_count']+=c.execute(f'DELETE FROM {table} WHERE event_id=?',(anchor['event_id'],)).rowcount
                        for term in term_values:
                            c.execute('INSERT INTO event_terms(event_id,term_digest) VALUES(?,?)',(anchor['event_id'],term))
                            receipt['affected_artifact_count']+=1
                        receipt['affected_artifact_count']+=c.execute('UPDATE events SET payload=?,payload_digest=?,terms_digest=?,record_digest=? WHERE event_id=?',(packed,payload_digest,terms,record,anchor['event_id'])).rowcount
                # The graph is fully derived. Rebuild it only from sanitized survivors and
                # tombstones so shared-node ownership and temporal edges cannot dangle.
                receipt['affected_artifact_count']+=c.execute('DELETE FROM edges').rowcount
                graph_rows=c.execute('SELECT * FROM events ORDER BY session_id,sequence,event_id').fetchall()
                expected_identities={hashlib.sha256(b'event\0'+row['event_id']).digest() for row in graph_rows}
                expected_identities.update(hashlib.sha256(b'subject\0'+row['subject_digest']).digest() for row in graph_rows)
                for node in c.execute('SELECT node_id,identity_digest FROM nodes').fetchall():
                    if node['identity_digest'] not in expected_identities:
                        receipt['affected_artifact_count']+=c.execute('DELETE FROM nodes WHERE node_id=?',(node['node_id'],)).rowcount
                for row in graph_rows:
                    self._write_event_graph(c,row['event_id'],row['subject_digest'],row['supersedes_event_id'],row['contradicts_event_id'],row['observed_at'],row['valid_from'])
                # Retained derived facts are independently supported after removing the
                # forgotten sources; append the reduced support set to the audit chain.
                for dependency in plan['dependencies']:
                    if dependency['effect']!='recompute':continue
                    support=s['supports'][dependency['event_id']]
                    remaining=[x for x in support['sources'] if x['event_id'] not in receipt['events']]
                    self._record(c,'support_recomputed',{**support,'sources':remaining,'recorded_at':now})
                receipt['previous_audit_hash']=c.execute('SELECT digest FROM retention_control ORDER BY sequence DESC LIMIT 1').fetchone()['digest']
                self._record(c,'erased',receipt)
                errors=self._semantic_errors(c)
                if errors:raise ValueError('cleanup validation failed: '+ ';'.join(errors[:3]))
        if failure:raise ValueError(failure)
        return self.finalize(pd)

    def finalize(self,plan_digest):
        # Same owner lock used by all ordinary ledger readers/writers. No external stores claimed atomic.
        with self.file_lock(exclusive=True):
            c=self._open(create=False)
            try:
                self._require_schema(c)
                if self._semantic_errors(c):raise ValueError('corrupt retention ledger')
                s=self._state(c)
                if plan_digest not in s['erased']:raise ValueError('unknown deletion receipt')
                receipt=s['erased'][plan_digest]
                if plan_digest not in s['compacted']:
                    if c.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]:raise ValueError('compaction checkpoint busy')
                    c.execute('VACUUM')
                    if c.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]:raise ValueError('compaction checkpoint busy')
                    c.execute('BEGIN IMMEDIATE');self._record(c,'compacted',{'plan_digest':plan_digest});c.commit()
                    c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                return {**receipt,'status':'applied','local_compaction':'complete','external_copies':'not_erased','forensic_erasure':False}
            finally:c.close()

    def project_outbox(self,*args,**kwargs):
        raise ValueError('retention profile does not publish hot projections; adapter required')

    def hot_events(self,*args,**kwargs):
        raise ValueError('retention profile does not consume legacy hot projections')

    def restore_untrusted_document(self,*args,**kwargs):
        raise ValueError('retention ledger import requires deletion-registry-aware adapter')


def as_retention(ledger):
    return RetentionLedger(ledger.path,project_id=ledger.project_id_text,project_slug=ledger.project_slug,root=ledger.root)

def open_ledger(ledger):
    if not ledger.path.exists():return ledger
    with ledger.file_lock(exclusive=False):
        c=ledger._open(create=False)
        try:r=c.execute("SELECT value FROM metadata WHERE key='ledger_schema'").fetchone()
        finally:c.close()
    return as_retention(ledger) if r is not None and r[0].decode()==SCHEMA else ledger

def migrate(ledger,*,expected_digest):
    if isinstance(ledger,RetentionLedger):return ledger.retention_status()
    with ledger.file_lock(exclusive=True):
        c=ledger._open(create=False)
        try:
            from .portable import _intent_path
            if _intent_path(ledger).exists():raise ValueError('pending import blocks retention migration')
            ledger._require_schema(c)
            if ledger._semantic_errors(c):raise ValueError('cannot migrate corrupt ledger')
            if ledger._logical_digest(c)!=expected_digest:raise ValueError('DIGEST_MISMATCH')
            marker=Path(str(ledger.path)+'.retention-v2')
            if marker.exists():
                d._guard_private_file(marker,'retention migration marker')
                if marker.read_bytes()!=SCHEMA.encode():raise ValueError('invalid retention marker')
            else:
                fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
                try:os.write(fd,SCHEMA.encode());os.fsync(fd)
                finally:os.close(fd)
                d._fsync_directory(marker.parent)
            c.execute('BEGIN IMMEDIATE');c.execute(SQL)
            c.execute("UPDATE metadata SET value=? WHERE key='ledger_schema'",(SCHEMA.encode(),))
            newer=as_retention(ledger)
            newer._record(c,'migration',{'from_schema':d.LEDGER_SCHEMA,'before_digest':expected_digest,'at':d.now_ms()})
            c.commit()
        except BaseException:
            c.rollback();raise
        finally:c.close()
    return as_retention(ledger).retention_status()


def unconfigured_plan(ledger):
    """Read-only retained-all discovery for an unmigrated ledger."""
    with ledger.connection(create=False) as c:
        logical=ledger._logical_digest(c)
    at=d.now_ms()
    plan={'schema':PLAN,'project_id':ledger.project_id_text,'status':'refused',
          'proposed_at':at,'expires_at':at+3600000,'scope':None,
          'bindings':{'ledger_digest':logical,'policy_digest':digest(None),
                      'hold_set_digest':digest({}),'session_pin_digest':digest([]),
                      'pack_manifest_digest':digest({}),
                      'authorization_digest':digest({}),
                      'support_digest':digest({}),'control_digest':'0'*64},
          'contract':CONTRACT,'affected':[],'exclusions':[{'event_id':'*','reason':'policy_unconfigured'}],
          'dependencies':[],'packs':[],'bytes':{'recoverable_now':0,'logical_payload_bytes':0,'recoverable_after_compact':None},
          'caveats':['retention_migration_required','backups_out_of_band','model_context_not_in_scope']}
    plan['plan_digest']=digest(plan)
    return plan
