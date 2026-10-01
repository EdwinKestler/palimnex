from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from palimnex import cache_v3
from palimnex import core as legacy
from palimnex.tests.fake_redis import FakeRedis


V25_SHA256 = "9cca022d5ac60a527783d4990ff745ba033c25f3fc789ad245bcfe703f0de569"
V27_SHA256 = "a2d295cae4a50cdffedffdd2c9c91d5546fad62e5b385909ebe5fa518918bd38"


class FrozenCheckoutEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[2]
        cls.client = FakeRedis()
        cls.index = cache_v3.build_index(cls.client, cls.root)
        cls.result = cache_v3.evaluate(cls.client, 5, cls.root)

    def test_frozen_fixture_is_excluded_and_cannot_contaminate_results(self) -> None:
        fixture = self.root / "palimnex/evaluation/v27.json"
        historical = self.root / "palimnex/evaluation/v25.json"
        config = legacy.project_config(self.root)
        self.assertEqual(config["evaluation_fixture"], "palimnex/evaluation/v27.json")
        self.assertEqual(config["evaluation_fixture_sha256"], V27_SHA256)
        self.assertEqual(hashlib.sha256(fixture.read_bytes()).hexdigest(), V27_SHA256)
        included = legacy.included_files(self.root)
        self.assertNotIn(fixture, included)
        self.assertNotIn(historical, included)
        self.assertEqual(hashlib.sha256(historical.read_bytes()).hexdigest(), V25_SHA256)
        manifest_key = self.client.execute(
            "GET", f"{cache_v3.namespace(self.root)}:active-generation"
        ).decode()
        manifest = cache_v3._load_manifest(self.client, manifest_key, self.root)
        self.assertNotIn("palimnex/evaluation/v27.json", manifest["files"])
        self.assertNotIn("palimnex/evaluation/v25.json", manifest["files"])
        fixture_description = json.loads(fixture.read_text(encoding="utf-8"))["description"]
        self.assertFalse(
            fixture_description.encode("utf-8") in self.client.all_stored_bytes(),
            "excluded fixture prose leaked into the cache",
        )
        for outcome in self.result["outcomes"]:
            self.assertNotIn("palimnex/evaluation/v27.json", outcome["returned_paths"])

    def test_frozen_recall_at_five_and_critical_cases_pass(self) -> None:
        self.assertEqual(self.result["cases"], 20)
        self.assertGreaterEqual(self.result["recall_at_limit"], 0.95)
        critical = [item for item in self.result["outcomes"] if item["critical"]]
        self.assertTrue(critical)
        self.assertTrue(all(item["passed"] for item in critical), critical)
        for item in critical:
            ranks = [
                item["returned_paths"].index(path) + 1
                for path in item["expected_paths"]
            ]
            self.assertLessEqual(max(ranks), 3, item)
        self.assertTrue(self.result["critical_passed"])
        self.assertEqual(self.result["critical_margin_warnings"], [])
        self.assertEqual(self.result["status"], "passed")


if __name__ == "__main__":
    unittest.main()
