import copy
import json
import tempfile
import unittest
from pathlib import Path
from palimnex.longitudinal import scenarios, worker, seal_manifest, score_external

class LongitudinalTests(unittest.TestCase):
    def manifest(self):
        return seal_manifest({'schema':'project-memory:longitudinal-run:v1','run_id':'trial',
            'cohort':{'id':'development','split':'development','digest':'a'*64,'generator_digest':'b'*64,'config_digest':'c'*64},
            'code_digest':'d'*64,'model':{'id':'external','version':'pinned'},'prompt_digest':'e'*64,'model_config_digest':'f'*64,
            'budgets':{'input_tokens':1000,'output_tokens':100,'context_bytes':8192},'arms':['history'],
            'queries':[{'scenario_id':'one','session':1,'query_id':'q','arm':'history','visible_input_digest':'a'*64}],
            'scoring_protocol':'independent-labels:v1'})
    def result(self,m):
        return {**m['queries'][0],'manifest_digest':m['manifest_digest'],'answer':'answer','abstained':False,
                'usage':{'input_tokens':100,'output_tokens':10,'context_bytes':200},
                'labels':{'method':'human','answer_correct':True,'evidence_supported':True,'abstention_correct':None,'task_success':None}}
    def test_future_actions_not_given_to_worker_and_scope_isolation(self):
        scenario=scenarios(1)[0]
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'one';root.mkdir()
            first=scenario['steps'][0]
            result=worker({'root':str(root),'arm':'history','actions':first['actions'],'query':first['query'],'cleanup':False})
            self.assertTrue(result['context']['abstained'])
            second=scenario['steps'][1]
            result=worker({'root':str(root),'arm':'history','actions':second['actions'],'query':second['query'],'cleanup':False})
            self.assertIn(second['expected'],json.dumps(result['context']['items']))
            other=Path(t)/'other';other.mkdir()
            result=worker({'root':str(other),'arm':'history','actions':[],'query':second['query'],'cleanup':False})
            self.assertTrue(result['context']['abstained'])
    def test_worker_rejects_gold_in_envelope(self):
        with self.assertRaisesRegex(ValueError,'envelope'):worker({'expected':'answer'})
    def test_family_count_not_independent_task_claim(self):
        cases=scenarios();self.assertEqual(len(cases),30);self.assertEqual(len({c['family'] for c in cases}),6)
        self.assertTrue(all(len(c['steps'])==6 for c in cases))
    def test_external_score_preserves_unmeasured_outcomes(self):
        m=self.manifest();score=score_external(m,[self.result(m)])
        self.assertEqual(score['metrics']['answer_correct']['value'],1)
        self.assertIsNone(score['metrics']['task_success']['value'])
        self.assertEqual(score['metrics']['task_success']['measured'],0)
        self.assertFalse(score['promotion_eligible'])
    def test_external_rejects_wrong_binding_duplicates_and_budget(self):
        m=self.manifest();r=self.result(m)
        for field in ('manifest_digest','visible_input_digest'):
            bad=copy.deepcopy(r);bad[field]='0'*64
            with self.assertRaisesRegex(ValueError,'binding'):score_external(m,[bad])
        with self.assertRaises(ValueError):score_external(m,[r,r])
        bad=copy.deepcopy(r);bad['usage']['output_tokens']=101
        with self.assertRaisesRegex(ValueError,'budget'):score_external(m,[bad])
        bad=copy.deepcopy(m);bad['model']['version']='changed'
        with self.assertRaisesRegex(ValueError,'digest'):score_external(bad,[r])
    def test_heldout_reservation_survives_changed_run_id(self):
        from palimnex.longitudinal import claim_heldout
        m=self.manifest();raw={k:v for k,v in m.items() if k!='manifest_digest'};raw['cohort']['split']='heldout';m=seal_manifest(raw)
        with tempfile.TemporaryDirectory() as temp:
            registry=Path(temp)/'registry'
            self.assertTrue(claim_heldout(m,registry)['reserved'])
            raw['run_id']='another-attempt';m=seal_manifest(raw)
            with self.assertRaisesRegex(ValueError,'already reserved'):claim_heldout(m,registry)
