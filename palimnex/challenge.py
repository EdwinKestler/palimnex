"""Separate, pinned development challenges; no models, network, or live state."""
from __future__ import annotations
import hashlib
import json
import math
import tempfile
import time
from pathlib import Path

from . import cache_v3, core
from .retrieval import budget_items, retrieve_sources
from .tests.fake_redis import FakeRedis
from .tests.support import write_project

FIXTURE_SHA256 = '8a1de2e3275fba858990c144f2eab34bf9a111c351f04eef8547fba48137abf3'


def evaluate_challenges() -> dict:
    raw = (Path(__file__).parent / 'evaluation/v26.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != FIXTURE_SHA256:
        raise ValueError('challenge fixture digest mismatch')
    fixture = json.loads(raw)
    reports = {}
    with tempfile.TemporaryDirectory(prefix='pm-challenge-') as directory:
        root = Path(directory)
        write_project(root, fixture['documents'])
        redis = FakeRedis()
        cache_v3.build_index(redis, root)
        snapshot = cache_v3.source_snapshot(root)
        corpus = frozenset(s.path for s in snapshot.files)
        for backend in ('files_lexical', 'v25_cache', 'v26_context'):
            outcomes, samples, sizes = [], [], []
            for case in fixture['cases']:
                result = []
                for repeat in range(3):
                    start = time.perf_counter_ns()
                    if backend == 'v26_context':
                        result = retrieve_sources(case['query'], root=root, limit=5, byte_budget=8192)['results']
                    elif backend == 'v25_cache':
                        result, _ = budget_items(cache_v3.search(redis, case['query'], 5, root)['results'], 8192)
                    else:
                        terms = set(core.tokenize(case['query']))
                        ranked = []
                        for source in cache_v3.source_snapshot(root).files:
                            overlap = len(terms & set(core.tokenize(source.text)))
                            if overlap:
                                ranked.append({'path': source.path, 'text': source.text, 'score': overlap})
                        ranked.sort(key=lambda item: (-item['score'], item['path']))
                        result, _ = budget_items(ranked[:5], 8192)
                    samples.append((time.perf_counter_ns()-start)/1_000_000)
                paths = {item['path'] for item in result}
                if not paths <= corpus:
                    raise AssertionError('retrieval escaped the admitted corpus')
                sizes.append(len(json.dumps(result, ensure_ascii=False, sort_keys=True).encode()))
                expected = set(case['expected_paths'])
                outcomes.append({'id': case['id'], 'expected_paths': sorted(expected),
                                 'returned_paths': sorted(paths), 'found': len(expected & paths),
                                 'expected': len(expected), 'abstained': not result,
                                 'passed': expected <= paths if expected else not result})
            found = sum(o['found'] for o in outcomes)
            expected_total = sum(o['expected'] for o in outcomes)
            negative = [o for o in outcomes if not o['expected']]
            ordered = sorted(samples)
            reports[backend] = {'expected_path_recall': found/expected_total,
                                'negative_query_abstention': sum(o['abstained'] for o in negative)/len(negative),
                                'cases_passed': sum(o['passed'] for o in outcomes),
                                'cases': len(outcomes), 'outcomes': outcomes,
                                'mean_output_bytes': sum(sizes)/len(sizes),
                                'p50_ms': ordered[math.ceil(len(ordered)*.5)-1],
                                'p95_ms': ordered[math.ceil(len(ordered)*.95)-1],
                                'samples': len(samples)}
    candidate = reports['v26_context']
    nonregressing = all(candidate['expected_path_recall'] >= reports[b]['expected_path_recall']
                        and candidate['negative_query_abstention'] >= reports[b]['negative_query_abstention']
                        for b in ('files_lexical','v25_cache'))
    return {'schema': 'project-memory:challenge-report:v1', 'status': 'passed' if nonregressing else 'failed',
            'gate': 'development evidence recall and abstention nonregression only',
            'fixture_sha256': FIXTURE_SHA256, 'backends': reports,
            'latency_boundary': 'local CPU with FakeRedis; not Redis I/O or model latency',
            'quality_boundary': 'synthetic development source retrieval; not held-out answer or task success',
            'model_calls': 0, 'promotion_eligible': False, 'live_state_touched': False}
