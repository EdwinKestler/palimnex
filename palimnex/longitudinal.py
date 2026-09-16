"""Chronological development replay; real subprocess sessions, no implicit model calls."""
from __future__ import annotations
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from . import durable as d
from .retention import migrate, open_ledger, RetentionLedger, POLICY
from .experience import assemble_context
from .tests.support import write_project, PROJECT_ID

ARMS=('source_only','history','history_cleanup')
FAMILIES=('recall','correction','revocation','abstention','workflow','cleanup')

def digest(value):return hashlib.sha256(d.canonical_json(value)).hexdigest()

def scenarios(variants=5):
    if type(variants) is not int or not 1<=variants<=5:raise ValueError('variants must be 1..5')
    result=[]
    for family in FAMILIES:
        for variant in range(variants):
            key=f'orchard{family}{variant}';future=f'horizon{family}{variant}';a=f'violet{variant}';b=f'amber{variant}';c=f'cobalt{variant}'
            initial={'op':'assert','alias':'initial','subject':key,'value':a,'kind':'failure' if family=='workflow' else 'fact'}
            change=[];expected=a
            if family=='correction':change=[{'op':'correct','alias':'changed','subject':key,'value':b,'predecessor':'initial'}];expected=b
            if family=='revocation':change=[{'op':'revoke','alias':'changed','subject':key,'value':'withdrawn','predecessor':'initial'}];expected=None
            steps=[{'actions':[initial],'query':future,'expected':None},
                   {'actions':[],'query':key,'expected':a},
                   {'actions':change,'query':key,'expected':expected,'forbidden':[a] if family in ('correction','revocation') else []},
                   {'actions':[{'op':'assert','alias':'future','subject':future,'value':c}],'query':future,'expected':c},
                   {'actions':[{'op':'scratch','alias':'scratch','subject':'temporary'+key,'value':'scratchdetail'}], 'query':'temporary'+key,'expected':'scratchdetail'},
                   {'actions':[],'query':('unknown'+key if family=='abstention' else key),'expected':(None if family=='abstention' else expected),'cleanup':True}]
            result.append({'id':f'{family}-{variant}','family':family,'steps':steps})
    return result

def worker(request):
    """Receives exactly one session's inputs, never gold answers or future actions."""
    if set(request)!={'root','arm','actions','query','cleanup'}:raise ValueError('invalid worker envelope')
    root=Path(request['root']);arm=request['arm']
    if arm not in ARMS:raise ValueError('invalid arm')
    if not (root/'.palimnex.json').exists():write_project(root,{'docs/start.md':'# Workspace\nCommon source reference.\n'})
    base=d.MemoryLedger(root/'.private/memory.sqlite3',project_id=PROJECT_ID,project_slug='memory-fixture',root=root)
    if not base.path.exists():base.initialize()
    ledger=open_ledger(base)
    if arm=='history_cleanup' and not isinstance(ledger,RetentionLedger):
        migrate(ledger,expected_digest=ledger.status()['logical_digest']);ledger=open_ledger(base)
        ledger.activate_policy({'schema':POLICY,'policy_id':'development','version':1,'mode':'manual','clock':'tx_at',
            'rules':[{'retention':'session','kinds':['fact'],'ttl_seconds':0}],
            'grace_after_close_seconds':0,'plan_ttl_seconds':3600},actor='harness',reason='isolated trial')
    state_path=root/'.private/aliases.json';aliases=json.loads(state_path.read_text()) if state_path.exists() else {}
    cleanup_result=None
    if request['cleanup'] and arm=='history_cleanup':
        p=ledger.propose();cleanup_result=ledger.apply(p,confirm_digest=p['plan_digest'],key=b'l'*32,actor='harness',reason='development expiry')
    sid=ledger.start_session('chronological task')['session_id']
    for action in request['actions']:
        op=action['op'];kwargs={}
        if op in ('correct','revoke'):kwargs['supersedes']=aliases[action['predecessor']]
        event=ledger.append_event(sid,{'correct':'correction','revoke':'revocation'}.get(op,action.get('kind','fact')),
                                  subject=action['subject'],payload={'value':action['value']},
                                  retention='session' if op=='scratch' else 'durable',**kwargs)
        aliases[action['alias']]=event['event_id']
    started=time.perf_counter_ns()
    context=assemble_context(request['query'],root=root,ledger=ledger if arm!='source_only' else None,
                             byte_budget=8192,limit=8,session_id=sid)
    latency=(time.perf_counter_ns()-started)/1e6
    ledger.close_session(sid,outcome='session complete')
    state_path.write_text(json.dumps(aliases));state_path.chmod(0o600)
    return {'context':context,'latency_ms':latency,'pid':__import__('os').getpid(),
            'cleanup':cleanup_result,'ledger_events':ledger.status()['counts']['events']}

def evaluate_longitudinal(*,variants=5, output_directory=None, model_id="unselected", model_version="unselected"):
    cohort=scenarios(variants);outcomes=[];requests=[]
    with tempfile.TemporaryDirectory(prefix='pm-longitudinal-') as temp:
        for scenario in cohort:
            for arm in ARMS:
                root=Path(temp)/scenario['id']/arm;root.mkdir(parents=True)
                for position,step in enumerate(scenario['steps']):
                    request={'root':str(root),'arm':arm,'actions':step['actions'],'query':step['query'],'cleanup':step.get('cleanup',False)}
                    start=time.perf_counter_ns()
                    child=subprocess.run([sys.executable,'-m','palimnex.longitudinal','--worker'],
                                         input=json.dumps(request),capture_output=True,text=True,check=True,timeout=30)
                    reply=json.loads(child.stdout);context=reply['context'];text=json.dumps(context['items'])
                    expected=step['expected'];found=expected in text if expected is not None else context['abstained']
                    forbidden=any(value in text for value in step.get('forbidden',[]))
                    found=found and not forbidden
                    visible={'query':step['query'],'items':context['items']}
                    requests.append({'scenario_id':scenario['id'],'session':position,'query_id':str(position),
                                     'arm':arm,'visible_input_digest':digest(visible),'input':visible})
                    outcomes.append({'scenario_id':scenario['id'],'family':scenario['family'],'session':position,
                                     'arm':arm,'expected_evidence_present':found,'expected_abstention':expected is None,
                                     'abstained':context['abstained'],'context_bytes':context['items_bytes'],
                                     'latency_ms':reply['latency_ms'],'process_ms':(time.perf_counter_ns()-start)/1e6,
                                     'worker_pid':reply['pid'],'visible_input_digest':digest(visible),'forbidden_evidence_present':forbidden,
                                     'erased_records':len(reply['cleanup']['events']) if reply['cleanup'] else 0})
    summary={}
    for arm in ARMS:
        rows=[x for x in outcomes if x['arm']==arm];negative=[x for x in rows if x['expected_abstention']]
        summary[arm]={'observations':len(rows),'evidence_success':sum(x['expected_evidence_present'] for x in rows)/len(rows),
                      'abstention_accuracy':sum(x['abstained'] for x in negative)/len(negative),
                      'mean_context_bytes':sum(x['context_bytes'] for x in rows)/len(rows),
                      'p95_retrieval_ms':sorted(x['latency_ms'] for x in rows)[int(.95*(len(rows)-1))],
                      'erased_records':sum(x['erased_records'] for x in rows)}
    report={'schema':'project-memory:longitudinal-development:v1','status':'passed' if all(summary[a]['evidence_success']==1 for a in ARMS[1:]) else 'failed',
            'cohort_digest':digest(cohort),'generator_digest':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'scenario_count':len(cohort),'family_count':len(FAMILIES),'sessions_per_scenario':6,
            'development_only':True,'model_calls':0,'task_success':None,'supported_answer_accuracy':None,
            'quality_boundary':'deterministic evidence replay, not model task success or held-out inference',
            'arms':summary,'outcomes':outcomes}
    if output_directory is not None:
        output=Path(output_directory)
        output.mkdir(mode=0o700,parents=True,exist_ok=False)
        manifest=seal_manifest({'schema':'project-memory:longitudinal-run:v1','run_id':output.name,
            'cohort':{'id':'generated-development','split':'development','digest':digest(cohort),
                      'generator_digest':report['generator_digest'],'config_digest':digest({'variants':variants})},
            'code_digest':digest({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}),
            'model':{'id':model_id,'version':model_version},'prompt_digest':digest('Answer only from supplied evidence; otherwise abstain.'),
            'model_config_digest':digest({'temperature':0}),
            'budgets':{'input_tokens':8192,'output_tokens':1024,'context_bytes':8192},'arms':list(ARMS),
            'queries':[{k:v for k,v in q.items() if k!='input'} for q in requests],
            'scoring_protocol':'external-independent-labels:v1'})
        for name,value in (('manifest.json',manifest),('requests.json',requests),('development-report.json',report)):
            path=output/name;path.write_bytes(d.canonical_json(value));path.chmod(0o600)
        report['prepared_run']=str(output)
        report['manifest_digest']=manifest['manifest_digest']
    return report


def seal_manifest(manifest):
    required={'schema','run_id','cohort','code_digest','model','prompt_digest','model_config_digest','budgets','arms','queries','scoring_protocol'}
    if not isinstance(manifest,dict) or set(manifest)!=required or manifest['schema']!='project-memory:longitudinal-run:v1':raise ValueError('invalid run manifest')
    cohort=manifest['cohort']
    if not isinstance(cohort,dict) or set(cohort)!={'id','split','digest','generator_digest','config_digest'}:raise ValueError('invalid cohort')
    if not isinstance(manifest['model'],dict) or set(manifest['model'])!={'id','version'} or any(not isinstance(v,str) or not v or len(v)>256 for v in manifest['model'].values()):raise ValueError('invalid model identity')
    for value in [manifest['code_digest'],manifest['prompt_digest'],manifest['model_config_digest'],cohort['digest'],cohort['generator_digest'],cohort['config_digest']]:
        if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value):raise ValueError('invalid manifest digest field')
    if not isinstance(manifest['run_id'],str) or not manifest['run_id'] or len(manifest['run_id'])>256:raise ValueError('invalid run identity')
    if not isinstance(manifest['arms'],list) or not manifest['arms'] or any(not isinstance(v,str) or not v for v in manifest['arms']) or len(set(manifest['arms']))!=len(manifest['arms']):raise ValueError('invalid arms')
    if not isinstance(manifest['queries'],list) or not manifest['queries'] or len(manifest['queries'])>10000:raise ValueError('invalid query count')
    if manifest['cohort']['split'] not in ('development','heldout'):raise ValueError('invalid cohort split')
    if set(manifest['budgets'])!={'input_tokens','output_tokens','context_bytes'} or any(type(v)is not int or v<1 for v in manifest['budgets'].values()):raise ValueError('invalid budgets')
    ids=set()
    for q in manifest['queries']:
        if set(q)!={'scenario_id','session','query_id','arm','visible_input_digest'}:raise ValueError('invalid query binding')
        if type(q['session'])is not int or q['session']<0 or any(not isinstance(q[k],str) or not q[k] for k in ('scenario_id','query_id','arm')) or not isinstance(q['visible_input_digest'],str) or not re.fullmatch('[0-9a-f]{64}',q['visible_input_digest']):raise ValueError('invalid query identity')
        key=(q['scenario_id'],q['session'],q['query_id'],q['arm'])
        if key in ids or q['arm'] not in manifest['arms']:raise ValueError('duplicate or unknown query')
        ids.add(key)
    return {**manifest,'manifest_digest':digest(manifest)}

def score_external(manifest,results):
    """Score explicitly supplied labels, with provenance; never infer task success from retrieval."""
    sealed=seal_manifest({k:v for k,v in manifest.items() if k!='manifest_digest'})
    if sealed!=manifest:raise ValueError('manifest digest mismatch')
    if not isinstance(results,list) or len(results)!=len(manifest['queries']):raise ValueError('incomplete results')
    expected={(q['scenario_id'],q['session'],q['query_id'],q['arm']):q for q in manifest['queries']}
    metrics={name:[] for name in ('answer_correct','evidence_supported','abstention_correct','task_success')};seen=set();methods=set()
    for r in results:
        required={'manifest_digest','scenario_id','session','query_id','arm','visible_input_digest','answer','abstained','usage','labels'}
        if not isinstance(r,dict) or set(r)!=required:raise ValueError('invalid result fields')
        key=(r['scenario_id'],r['session'],r['query_id'],r['arm'])
        if key in seen or key not in expected:raise ValueError('duplicate or unknown result')
        seen.add(key)
        if r['manifest_digest']!=manifest['manifest_digest'] or r['visible_input_digest']!=expected[key]['visible_input_digest']:raise ValueError('result binding mismatch')
        if not isinstance(r['answer'],str) or type(r['abstained'])is not bool:raise ValueError('invalid answer')
        if set(r['usage'])!=set(manifest['budgets']) or any(type(v)is not int or v<0 or v>manifest['budgets'][k] for k,v in r['usage'].items()):raise ValueError('budget exceeded or invalid usage')
        if set(r['labels'])!={'method',*metrics} or r['labels']['method'] not in ('human','deterministic','model_judge'):raise ValueError('invalid label provenance')
        methods.add(r['labels']['method'])
        for k in metrics:
            value=r['labels'][k]
            if value is not None and type(value)is not bool:raise ValueError('invalid outcome label')
            if value is not None:metrics[k].append(value)
    arms={}
    for arm in manifest['arms']:
        rows=[r for r in results if r['arm']==arm]
        arms[arm]={}
        for metric in metrics:
            values=[r['labels'][metric] for r in rows if r['labels'][metric] is not None]
            arms[arm][metric]={'value':sum(values)/len(values) if values else None,'measured':len(values),'total':len(rows)}
    return {'schema':'project-memory:longitudinal-score:v1','manifest_digest':manifest['manifest_digest'],
            'label_methods':sorted(methods),'label_truth_independently_verified':False,'arms':arms,
            'metrics':{k:{'value':sum(v)/len(v) if v else None,'measured':len(v),'total':len(results)} for k,v in metrics.items()},
            'promotion_eligible':False,'boundary':'binding and arithmetic verified; held-out integrity and label truth require separate evidence'}

def claim_heldout(manifest, registry_root):
    """Reserve one cohort read; the persistent marker survives crashes and changed run IDs."""
    if seal_manifest({k:v for k,v in manifest.items() if k!='manifest_digest'})!=manifest:
        raise ValueError('manifest digest mismatch')
    if manifest['cohort']['split']!='heldout':raise ValueError('heldout cohort required')
    registry=Path(registry_root)
    if registry.is_symlink():raise ValueError('registry must not be a symlink')
    registry.mkdir(mode=0o700,parents=True,exist_ok=True)
    if registry.stat().st_uid!=os.getuid() or registry.stat().st_mode & 0o077:raise ValueError('registry must be owner-only')
    marker=registry/(manifest['cohort']['digest']+'.read.json')
    try:fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    except FileExistsError as exc:raise ValueError('cohort already reserved; use a disjoint heldout cohort') from exc
    try:
        raw=d.canonical_json({'manifest_digest':manifest['manifest_digest'],'cohort_digest':manifest['cohort']['digest'],'state':'consumed_before_execution'})
        os.write(fd,raw);os.fsync(fd)
    finally:os.close(fd)
    d._fsync_directory(registry)
    return {'reserved':True,'manifest_digest':manifest['manifest_digest'],'marker':str(marker)}

if __name__=='__main__':
    if sys.argv[1:]!=['--worker']:raise SystemExit('internal worker entry only')
    print(json.dumps(worker(json.load(sys.stdin)),sort_keys=True))
