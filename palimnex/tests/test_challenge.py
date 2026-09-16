import unittest
from unittest import mock
from palimnex.challenge import evaluate_challenges


class ChallengeTests(unittest.TestCase):
    def test_pinned_development_comparison_preserves_visible_paraphrase_failure(self):
        report = evaluate_challenges()
        self.assertEqual(report['status'], 'passed')
        self.assertFalse(report['promotion_eligible'])
        self.assertEqual(report['model_calls'], 0)
        candidate = report['backends']['v26_context']
        self.assertGreater(candidate['expected_path_recall'], report['backends']['v25_cache']['expected_path_recall'])
        paraphrase = next(x for x in candidate['outcomes'] if x['id']=='unresolved-paraphrase')
        self.assertFalse(paraphrase['passed'])

    def test_fixture_tampering_is_refused(self):
        with mock.patch('pathlib.Path.read_bytes',return_value=b'{}'):
            with self.assertRaisesRegex(ValueError,'digest'):
                evaluate_challenges()
