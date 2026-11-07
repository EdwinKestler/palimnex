from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from palimnex import core, ontology_influence
from palimnex._offline_fixtures import write_project
from palimnex.concepts import canonical_registry_digest
from palimnex.durable import canonical_json
from palimnex.ontology_influence import (
    OntologyInfluenceError,
    activate_influence,
    read_influence_setting,
    validate_promotion_evidence,
)
from palimnex.ontology_promotion import (
    OntologyPromotionError,
    evaluate_ontology_promotion,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = "ontology/concept-registry.v1.json"
EVIDENCE_PATH = "artifacts/ontology/promotion-evidence.json"
PROJECT_ID = "8e7b9c1d-315a-4fe2-9bb0-f4b5e7ef3721"
RETENTION_QUERY = (
    "retention eligibility first winning exclusion legal hold dependency guard "
    "authorized erasure"
)


class OntologyPromotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        cls.root = Path(temporary.name)
        cls._write_checkout(cls.root)
        cls._write_registry(cls.root, [cls._concept(cls.root)])
        with mock.patch.object(
            core,
            "RedisClient",
            side_effect=AssertionError("real Redis client must not be constructed"),
        ):
            cls.first = evaluate_ontology_promotion(cls.root)
            cls.second = evaluate_ontology_promotion(cls.root)

    @staticmethod
    def _write_checkout(root: Path) -> None:
        write_project(
            root,
            {
                "docs/alpha.md": "# Alpha\n\nPromotion sentinel source.\n",
                "docs/beta.md": "# Beta\n\nA bounded comparison source.\n",
                "docs/RETENTION.md": "# Policy\n\n" + RETENTION_QUERY + "\n",
                "docs/distractor.md": "# Retention\n\nRetention material.\n",
            },
        )
        evaluation = root / "palimnex/evaluation"
        evaluation.mkdir(parents=True, exist_ok=True)
        for name in ("v27.json", "v26.json", "ontology-shadow.v1.json"):
            shutil.copyfile(REPOSITORY_ROOT / "palimnex/evaluation" / name, evaluation / name)
        v27_raw = (evaluation / "v27.json").read_bytes()
        config_path = root / ".palimnex.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config.update(
            {
                "project_slug": "promotion-fixture",
                "project_id": PROJECT_ID,
                "include_patterns": [".palimnex.json", "docs/**/*.md"],
                "exclude_directories": ["ontology", "palimnex"],
                "exclude_paths": [
                    "palimnex/evaluation/v27.json",
                    "palimnex/evaluation/v26.json",
                    "palimnex/evaluation/ontology-shadow.v1.json",
                ],
                "evaluation_fixture": "palimnex/evaluation/v27.json",
                "evaluation_fixture_sha256": hashlib.sha256(v27_raw).hexdigest(),
            }
        )
        config_path.write_text(
            json.dumps(config, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _binding(root: Path, relative: str) -> dict[str, Any]:
        raw = (root / relative).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        return {
            "scheme": "repo",
            "source_id": relative,
            "version": digest,
            "range": {"unit": "bytes", "start": 0, "end": len(raw)},
            "digest": digest,
        }

    @classmethod
    def _concept(
        cls,
        root: Path,
        concept_id: str = "promotion.sentinel",
        *,
        canonical_name: str = "Promotion Sentinel Concept",
        alias: str = "promotion sentinel",
        relative: str = "docs/alpha.md",
    ) -> dict[str, Any]:
        return {
            "concept_id": concept_id,
            "canonical_name": canonical_name,
            "aliases": [alias],
            "definition": "A reviewed source-bound promotion test concept.",
            "source_bindings": [cls._binding(root, relative)],
            "status": "approved",
            "provenance": {"origin": "manual"},
        }

    @staticmethod
    def _registry_document(concepts: list[dict[str, Any]]) -> dict[str, Any]:
        document: dict[str, Any] = {
            "schema": "palimnex:concept-registry:v1",
            "project": {
                "project_slug": "promotion-fixture",
                "project_id": PROJECT_ID,
            },
            "registry_version": 1,
            "registry_kind": "approved_registry",
            "concepts": concepts,
            "registry_digest": "0" * 64,
            "authority": "historical_only",
            "authorizes_actions": False,
        }
        document["registry_digest"] = canonical_registry_digest(document)
        return document

    @classmethod
    def _write_registry(
        cls, root: Path, concepts: list[dict[str, Any]]
    ) -> dict[str, Any]:
        document = cls._registry_document(concepts)
        path = root / REGISTRY_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_json(document))
        return document

    @classmethod
    def _fresh_root(cls) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        cls._write_checkout(root)
        return temporary, root

    def test_evidence_is_deterministic_promotable_valid_and_offline(self) -> None:
        self.assertEqual(self.first, self.second)
        validate_promotion_evidence(self.first)
        self.assertEqual(self.first["status"], "promotable")
        self.assertIs(self.first["activation_authorized"], False)
        self.assertIs(self.first["authorizes_actions"], False)
        self.assertEqual(set(self.first["backends"]), {"local", "cache"})
        self.assertTrue(
            all(
                all(backend["gates"].values())
                for backend in self.first["backends"].values()
            )
        )
        self.assertEqual(
            self.first["backends"]["local"]["suites"]["challenges_v26"],
            self.first["backends"]["cache"]["suites"]["challenges_v26"],
        )

        import jsonschema
        from referencing import Registry, Resource

        schema = json.loads(
            (REPOSITORY_ROOT / "palimnex/schemas/ontology-promotion-evidence.v1.schema.json")
            .read_text(encoding="utf-8")
        )
        registry = Registry().with_resource(schema["$id"], Resource.from_contents(schema))
        jsonschema.Draft202012Validator(schema, registry=registry).validate(self.first)

    def test_produced_evidence_activates_and_all_module_changes_invalidate_it(self) -> None:
        evidence_path = self.root / EVIDENCE_PATH
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_raw = canonical_json(self.first)
        evidence_path.write_bytes(evidence_raw)
        config_path = self.root / ".palimnex.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["ontology_influence"] = {
            "mode": "enabled",
            "registry": REGISTRY_PATH,
            "registry_digest": self.first["registry"]["digest"],
            "promotion_evidence": EVIDENCE_PATH,
            "promotion_evidence_digest": hashlib.sha256(evidence_raw).hexdigest(),
        }
        config_path.write_text(
            json.dumps(config, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        setting = read_influence_setting(self.root)
        self.assertIsNotNone(activate_influence(setting, root=self.root))

        source_rows = ontology_influence._IMPLEMENTATION_SOURCE_PATHS
        for index, (module, source_path) in enumerate(source_rows):
            with self.subTest(module=module):
                changed_path = self.root / "changed" / f"module-{index}.py"
                changed_path.parent.mkdir(parents=True, exist_ok=True)
                changed_path.write_bytes(source_path.read_bytes() + b"\n")
                changed_rows = tuple(
                    (name, changed_path if name == module else path)
                    for name, path in source_rows
                )
                with mock.patch.object(
                    ontology_influence,
                    "_IMPLEMENTATION_SOURCE_PATHS",
                    changed_rows,
                ):
                    with self.assertRaises(OntologyInfluenceError) as raised:
                        activate_influence(setting, root=self.root)
                self.assertEqual(
                    raised.exception.reason, "evidence_implementation_mismatch"
                )

    def test_critical_regression_is_held_on_both_backends(self) -> None:
        temporary, root = self._fresh_root()
        self.addCleanup(temporary.cleanup)
        concept = self._concept(
            root,
            "retention.distractor",
            canonical_name="Authorized Erasure Distractor",
            alias=RETENTION_QUERY,
            relative="docs/distractor.md",
        )
        self._write_registry(root, [concept])
        evidence = evaluate_ontology_promotion(root, limit=1)
        self.assertEqual(evidence["status"], "held")
        self.assertIs(evidence["activation_authorized"], False)
        for backend in evidence["backends"].values():
            self.assertFalse(backend["gates"]["no_critical_regression"])
            self.assertFalse(backend["gates"]["no_case_regression"])
            self.assertIn(
                "authorized-erasure",
                backend["suites"]["v27"]["regressed_case_ids"],
            )

    def test_ambiguous_and_stale_registries_return_held_gate_evidence(self) -> None:
        temporary, root = self._fresh_root()
        self.addCleanup(temporary.cleanup)
        ambiguous = [
            self._concept(root, "shared.alpha", canonical_name="Shared Alpha", alias="shared"),
            self._concept(
                root,
                "shared.beta",
                canonical_name="Shared Beta",
                alias="shared",
                relative="docs/beta.md",
            ),
        ]
        self._write_registry(root, ambiguous)
        evidence = evaluate_ontology_promotion(root)
        self.assertEqual(evidence["status"], "held")
        self.assertIs(evidence["activation_authorized"], False)
        self.assertTrue(
            all(
                not backend["gates"]["registry_unambiguous"]
                for backend in evidence["backends"].values()
            )
        )

        stale = self._concept(root)
        stale["source_bindings"][0]["version"] = "f" * 64
        self._write_registry(root, [stale])
        evidence = evaluate_ontology_promotion(root)
        self.assertEqual(evidence["status"], "held")
        self.assertTrue(
            all(
                not backend["gates"]["registry_current"]
                for backend in evidence["backends"].values()
            )
        )

    def test_missing_registry_and_real_checkout_are_typed_refusals(self) -> None:
        temporary, root = self._fresh_root()
        self.addCleanup(temporary.cleanup)
        for checkout in (root, REPOSITORY_ROOT):
            with self.subTest(checkout=checkout):
                with self.assertRaises(OntologyPromotionError) as raised:
                    evaluate_ontology_promotion(checkout)
                self.assertEqual(raised.exception.reason, "registry_read_refused")
                self.assertEqual(raised.exception.field, "path")


if __name__ == "__main__":
    unittest.main()
