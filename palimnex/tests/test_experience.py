from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from palimnex import cache_v3, core, durable
from palimnex.durable import MemoryLedger
from palimnex.experience import (CLAIM_SCHEMA, apply_capture, assemble_context,
                                       build_capsule, capture_candidate)
from palimnex.retrieval import retrieve_sources
from palimnex.tests.fake_redis import FakeRedis
from palimnex.tests.support import PROJECT_ID, write_project


class ExperienceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        write_project(self.root)
        self.ledger = MemoryLedger(self.root / '.private/memory.sqlite3', project_id=PROJECT_ID,
                                   project_slug='memory-fixture', root=self.root)
        self.session = self.ledger.start_session('cobalt recovery')['session_id']

    def event(self, *, payload=None, **kwargs):
        return self.ledger.append_event(self.session, 'fact', subject='cobalt recovery',
            payload=payload or {'claim': 'unsupported interpretation'}, retention='durable',
            evidence=[{'kind': 'source', 'locator': 'docs/alpha.md:3'}], **kwargs)

    def test_source_integrity_does_not_establish_claim_support(self):
        self.event()
        item = self.ledger.recall('cobalt')['results'][0]
        self.assertEqual(item['source_integrity'], 'current')
        self.assertEqual(item['claim_support'], 'not_assessed')
        self.ledger.close_session(self.session, outcome='recorded')
        self.assertEqual(self.ledger.consolidate(self.session, require_claim_support=True)['promoted_count'], 0)

    def test_exact_quote_support_and_stale_rejection(self):
        claim = 'The cobalt orchard recovery rule is deterministic.'
        self.event(payload={'schema': CLAIM_SCHEMA, 'claim': claim,
                            'support': {'kind': 'exact_quote', 'locator': 'docs/alpha.md:3'}})
        self.assertEqual(self.ledger.recall('cobalt')['results'][0]['claim_support'], 'exact_source_quote')
        self.ledger.close_session(self.session, outcome='recorded')
        self.assertEqual(self.ledger.consolidate(self.session, require_claim_support=True)['promoted_count'], 1)
        (self.root / 'docs/alpha.md').write_text('# Alpha\n\nchanged evidence\n')
        self.assertEqual(build_capsule('cobalt', ledger=self.ledger)['items'], [])

    def test_forged_quote_support_is_not_accepted(self):
        self.event(payload={'schema': CLAIM_SCHEMA, 'claim': 'An unsupported assertion',
                            'support': {'kind': 'exact_quote', 'locator': 'docs/alpha.md:3'}})
        self.assertEqual(self.ledger.recall('cobalt')['results'][0]['claim_support'], 'not_assessed')

    def test_sensitivity_filter_applies_before_candidate_cap(self):
        public = self.event(sensitivity='public', payload={'claim': 'cobalt public'})
        self.event(sensitivity='restricted')
        with mock.patch('palimnex.durable.MAX_RECALL_CANDIDATES', 1):
            result = self.ledger.recall('cobalt', max_sensitivity='public')
        self.assertEqual([e['event_id'] for e in result['results']], [public['event_id']])
        self.assertFalse(result['candidate_scan_truncated'])

    def test_current_visibility_keeps_other_sessions_private(self):
        transient = self.ledger.append_event(self.session, 'fact', subject='cobalt', payload={'hint': 'cobalt'}, retention='session')
        self.assertEqual(self.ledger.recall('cobalt', visibility='current')['results'], [])
        visible = self.ledger.recall('cobalt', visibility='current', session_id=self.session)['results']
        self.assertIn(transient['event_id'], [e['event_id'] for e in visible])
        self.ledger.close_session(self.session, outcome='done')
        self.assertEqual(self.ledger.recall('cobalt', visibility='current', session_id=self.session)['results'], [])
        self.assertTrue(self.ledger.recall('cobalt')['results'])

    def test_revocation_hides_fact_but_history_remains(self):
        fact = self.event()
        self.ledger.append_event(self.session, 'revocation', subject='cobalt recovery', payload={'reason': 'cobalt invalid'},
                                 supersedes=fact['event_id'], retention='durable')
        self.assertEqual(self.ledger.recall('cobalt', visibility='current')['results'], [])
        self.assertIn(fact['event_id'], [e['event_id'] for e in self.ledger.recall('cobalt', include_history=True)['results']])
        with self.assertRaisesRegex(ValueError, 'requires'):
            self.ledger.append_event(self.session, 'revocation', subject='cobalt', payload={})

    def spec(self):
        return {'subject': 'cobalt recovery', 'outcome': 'isolated tests passed',
                'failure': 'cache connection refused', 'attribution': 'environment',
                'evidence': ['docs/alpha.md:3']}

    def test_capture_is_atomic_and_retry_is_idempotent(self):
        candidate = capture_candidate(self.ledger, self.session, self.spec())
        before = self.ledger.status()['counts']['events']
        original = self.ledger._append_event_tx
        def fail_close(*args, **kwargs):
            if len(args) > 2 and args[2] == 'session_closed':
                raise RuntimeError('injected close failure')
            return original(*args, **kwargs)
        with mock.patch.object(self.ledger, '_append_event_tx', side_effect=fail_close):
            with self.assertRaisesRegex(RuntimeError, 'injected'):
                apply_capture(self.ledger, candidate)
        self.assertEqual(self.ledger.status()['counts']['events'], before)
        first = apply_capture(self.ledger, candidate)
        second = apply_capture(self.ledger, candidate)
        self.assertEqual(first['event_id'], second['event_id'])
        self.assertEqual(second['status'], 'already_captured')
        self.assertEqual(self.ledger.status()['counts']['events'], before + 2)
        self.assertEqual(self.ledger.status()['integrity'], 'ok')

    def test_imported_capture_cannot_acknowledge_local_completion(self):
        candidate = capture_candidate(self.ledger, self.session, self.spec())
        apply_capture(self.ledger, candidate)
        document = self.ledger.logical_document()
        imported = MemoryLedger(self.root/'.private/imported.sqlite3', project_id=PROJECT_ID,
                                project_slug='memory-fixture', root=self.root)
        imported.restore_untrusted_document(document, source_logical_digest=hashlib.sha256(durable.canonical_json(document)).hexdigest(), authenticated=True)
        with self.assertRaisesRegex(ValueError, 'completed local capture'):
            apply_capture(imported, candidate)
        self.assertEqual(build_capsule('cobalt',ledger=imported)['items'], [])

    def test_capture_rejects_tampering_and_changed_source(self):
        candidate = capture_candidate(self.ledger, self.session, self.spec())
        forged = {**candidate, 'claim_support': 'verified'}
        with self.assertRaisesRegex(ValueError, 'digest'):
            apply_capture(self.ledger, forged)
        (self.root / 'docs/beta.md').write_text('# Beta\nchanged\n')
        with self.assertRaisesRegex(ValueError, 'changed'):
            apply_capture(self.ledger, candidate)

    def test_capture_checkout_scope_does_not_apply_after_source_change(self):
        candidate = capture_candidate(self.ledger, self.session, self.spec())
        apply_capture(self.ledger, candidate)
        self.assertTrue(build_capsule('cobalt', ledger=self.ledger)['items'])
        (self.root / 'docs/beta.md').write_text('# Beta\nchanged\n')
        self.assertEqual(build_capsule('cobalt', ledger=self.ledger)['items'], [])

    def test_capsules_quote_evidence_not_unverified_claim(self):
        event = self.event(payload={'claim': 'A deliberately unsupported conclusion'})
        capsule = build_capsule('cobalt', ledger=self.ledger)
        self.assertEqual(capsule['items'][0]['parent_event_id'], event['event_id'])
        self.assertNotIn('unsupported conclusion', json.dumps(capsule))
        self.assertEqual(capsule['items'][0]['event_claim_support'], 'not_assessed')
        self.assertFalse(capsule['persisted'])
        self.assertFalse(capsule['authorizes_actions'])

    def test_contradictory_evidence_is_not_merged_away(self):
        original = self.event()
        other = self.ledger.append_event(self.session, 'fact', subject='cobalt recovery', payload={'claim': 'cobalt disagreement'},
             retention='durable', contradicts=original['event_id'], evidence=[{'kind':'source','locator':'docs/beta.md:3'}])
        capsule = build_capsule('cobalt', ledger=self.ledger)
        self.assertEqual({e['parent_event_id'] for e in capsule['items']}, {original['event_id'], other['event_id']})
        self.assertTrue(any(e['contradicts'] == original['event_id'] for e in capsule['items']))

    def test_context_is_bounded_and_reports_missing_history(self):
        result = assemble_context('cobalt', root=self.root, byte_budget=1024, ledger=None)
        self.assertEqual(result['ledger_status'], 'missing')
        self.assertFalse(result['cache_consulted'])
        self.assertLessEqual(len(json.dumps(result['items'], ensure_ascii=False, sort_keys=True).encode()), 1024)
        self.assertTrue(assemble_context('xylophonicnothing', root=self.root)['abstained'])

    def test_untrusted_claims_are_not_capsule_ingredients(self):
        self.event(trust='untrusted')
        self.assertEqual(build_capsule('cobalt', ledger=self.ledger)['items'], [])

    def test_malformed_capture_envelope_is_safely_excluded(self):
        self.event(payload={"schema": "project-memory:capture:v1"})
        self.assertEqual(build_capsule('cobalt', ledger=self.ledger)['items'], [])
        context = assemble_context('cobalt', root=self.root, ledger=self.ledger)
        self.assertFalse(any(i['type'] == 'historical_event' for i in context['items']))

    def test_excluded_source_evidence_is_omitted_from_capsule(self):
        (self.root/'private-note.txt').write_text('cobalt private note')
        self.ledger.append_event(self.session, 'fact', subject='cobalt', payload={'claim':'cobalt'}, retention='durable',
             evidence=[{'kind':'source','locator':'private-note.txt:1'}])
        capsule = build_capsule('cobalt', ledger=self.ledger)
        self.assertEqual(capsule['items'], [])
        self.assertEqual(capsule['omitted_evidence'], 1)

    def test_claim_second_read_must_match_verified_digest(self):
        from palimnex.experience import claim_support
        event = {'imported':False, 'claimed_trust':'observed', 'source_integrity':'current',
                 'payload':{'schema':CLAIM_SCHEMA, 'claim':'changed after first read',
                            'support':{'kind':'exact_quote','locator':'docs/alpha.md:3'}},
                 'evidence':[{'kind':1,'locator':'docs/alpha.md:3','content_digest':hashlib.sha256(b'original').hexdigest()}]}
        with mock.patch('palimnex.experience.source_quote', return_value='changed after first read'):
            self.assertEqual(claim_support(event,self.root),'not_assessed')

    def test_checkout_filter_precedes_recall_output_limit(self):
        retained = self.event(payload={'claim':'cobalt older applicable observation'})
        candidate = capture_candidate(self.ledger, self.session, self.spec())
        candidate['checkout_id'] = '0'*64
        candidate.pop('candidate_digest')
        candidate['candidate_digest'] = hashlib.sha256(durable.canonical_json(candidate)).hexdigest()
        with self.ledger.connection(create=False, write=True) as connection:
            timestamp = durable.now_ms()
            sid = bytes.fromhex(self.session)
            for _ in range(101):
                self.ledger._append_event_tx(connection, sid, 'outcome', subject='cobalt recovery', payload=candidate,
                     evidence_rows=[], retention='durable', observed_at=timestamp, valid_from=timestamp)
        context = assemble_context('cobalt', root=self.root, ledger=self.ledger)
        self.assertIn(retained['event_id'], [i.get('event_id') for i in context['items']])
        self.assertFalse(context['candidate_scan_truncated'])

    def test_current_promoted_recall_respects_unpromoted_revocation(self):
        event = self.event()
        self.ledger.close_session(self.session, outcome='recorded')
        self.ledger.consolidate(self.session)
        self.assertTrue(self.ledger.recall('cobalt',visibility='current',promoted_only=True)['results'])
        session = self.ledger.start_session('revoke prior fact')['session_id']
        self.ledger.append_event(session,'revocation',subject='cobalt recovery',payload={'reason':'cobalt withdrawn'},
             retention='durable',supersedes=event['event_id'])
        self.assertEqual(self.ledger.recall('cobalt',visibility='current',promoted_only=True)['results'],[])

    def test_capture_privacy_refusal_does_not_echo_secret(self):
        spec = self.spec()
        token = 'gh' + 'p_' + 'a' * 30
        spec['outcome'] = token
        with self.assertRaises(ValueError) as raised:
            capture_candidate(self.ledger, self.session, spec)
        self.assertNotIn(token, str(raised.exception))


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        write_project(self.root, {'docs/alpha.md': '# Quasar\n\nQuasar recovery uses [manual](beta.md).\n',
                                 'docs/beta.md': '# Manual\n\nRestore the amber orchard snapshot.\n'})

    def test_graph_finds_neighbor_without_shared_query_terms(self):
        result = retrieve_sources('quasar', root=self.root)
        beta = [r for r in result['results'] if r['path'] == 'docs/beta.md']
        self.assertTrue(beta)
        self.assertIn('graph', beta[0]['channels'])
        self.assertNotIn('lexical', beta[0]['channels'])
        without = retrieve_sources('quasar', root=self.root, include_graph=False)
        self.assertNotIn('docs/beta.md', [r['path'] for r in without['results']])

    def test_local_results_change_with_source_and_exclude_fixture(self):
        first = retrieve_sources('quasar', root=self.root)
        (self.root / 'docs/alpha.md').write_text('# Quasar\n\nQuasar changed.\n')
        second = retrieve_sources('quasar', root=self.root)
        self.assertNotEqual(first['corpus_fingerprint'], second['corpus_fingerprint'])
        self.assertNotIn('palimnex/evaluation/v25.json', [r['path'] for r in second['results']])

    def test_cache_path_keeps_poisoning_checks_and_does_not_downgrade(self):
        redis = FakeRedis()
        cache_v3.build_index(redis, self.root)
        result = retrieve_sources('quasar', root=self.root, client=redis)
        self.assertTrue(result['cache_consulted'])
        with mock.patch('palimnex.cache_v3._posting_candidates', side_effect=ValueError('poisoned posting')):
            with self.assertRaisesRegex(ValueError, 'poisoned'):
                retrieve_sources('quasar', root=self.root, client=redis)
        with mock.patch('palimnex.cache_v3._fresh_context', side_effect=core.RedisError('unavailable')):
            with self.assertRaises(core.RedisError):
                retrieve_sources('quasar', root=self.root, client=redis)

    def test_privacy_refuses_admitted_secret_without_echo(self):
        token = 'gh' + 'p_' + 'a' * 30
        (self.root/'docs/alpha.md').write_text(token)
        with self.assertRaises(ValueError) as raised:
            retrieve_sources('quasar', root=self.root)
        self.assertNotIn(token, str(raised.exception))

    def test_budget_never_truncates_evidence_into_misleading_quote(self):
        result = retrieve_sources('quasar', root=self.root, byte_budget=128)
        self.assertEqual(result['results'], [])
        self.assertGreater(result['omitted_count'], 0)
        with self.assertRaises(ValueError):
            retrieve_sources('quasar', root=self.root, byte_budget=-1)


if __name__ == '__main__':
    unittest.main()
