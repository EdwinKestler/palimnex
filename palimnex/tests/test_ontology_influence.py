from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import palimnex.ontology_influence as influence_module
from palimnex.concepts import canonical_registry_digest, load_registry
from palimnex.durable import canonical_json
from palimnex.ontology_influence import (
    CONTEXT_V2_SCHEMA,
    EXPLAIN_SEARCH_V2_SCHEMA,
    PROMOTION_EVIDENCE_SCHEMA,
    ActiveInfluence,
    InfluenceSetting,
    OntologyInfluenceError,
    activate_influence,
    context_v2,
    explain_search_v2,
    influence_disclosure,
    influence_implementation_digest,
    read_influence_setting,
    validate_promotion_evidence,
)
from palimnex.ontology_shadow import OntologyChannel


PROJECT_ID = "11111111-1111-4111-8111-111111111111"
FOREIGN_PROJECT_ID = "22222222-2222-4222-8222-222222222222"
REGISTRY_PATH = "ontology/concept-registry.v1.json"
EVIDENCE_PATH = "artifacts/ontology/promotion-evidence.json"


class OntologyInfluenceTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "docs").mkdir()
        self.source = self.root / "docs/source.md"
        self.source.write_bytes(b"current ontology source\n")
        self.write_config({})

    def write_config(self, extra: dict[str, Any]) -> None:
        document: dict[str, Any] = {
            "project_slug": "fixture",
            "project_id": PROJECT_ID,
        }
        document.update(extra)
        (self.root / ".palimnex.json").write_text(
            json.dumps(document), encoding="utf-8"
        )

    def binding(self) -> dict[str, Any]:
        raw = self.source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        return {
            "scheme": "repo",
            "source_id": "docs/source.md",
            "version": digest,
            "range": {"unit": "bytes", "start": 0, "end": len(raw)},
            "digest": digest,
        }

    def concept(
        self,
        concept_id: str = "concept.alpha",
        *,
        canonical_name: str | None = None,
        aliases: list[str] | None = None,
        status: str = "approved",
        definition: str = "A bounded ontology influence concept.",
    ) -> dict[str, Any]:
        return {
            "concept_id": concept_id,
            "canonical_name": canonical_name or concept_id.replace(".", " "),
            "aliases": aliases if aliases is not None else [concept_id.split(".")[-1] + " ontology"],
            "definition": definition,
            "source_bindings": [self.binding()] if status == "approved" else [],
            "status": status,
            "provenance": {"origin": "manual"},
        }

    def registry_document(
        self,
        concepts: list[dict[str, Any]] | None = None,
        *,
        kind: str = "approved_registry",
        project_slug: str = "fixture",
        project_id: str = PROJECT_ID,
    ) -> dict[str, Any]:
        document: dict[str, Any] = {
            "schema": "palimnex:concept-registry:v1",
            "project": {"project_slug": project_slug, "project_id": project_id},
            "registry_version": 1,
            "registry_kind": kind,
            "concepts": concepts or [self.concept()],
            "registry_digest": "0" * 64,
            "authority": "historical_only",
            "authorizes_actions": False,
        }
        document["registry_digest"] = canonical_registry_digest(document)
        return document

    def write_registry(self, document: dict[str, Any]) -> str:
        target = self.root / REGISTRY_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(canonical_json(document))
        return str(document["registry_digest"])

    def metrics(self) -> dict[str, Any]:
        return {
            "case_count": 1,
            "cases_passed": 1,
            "critical_case_count": 1,
            "critical_pass_count": 1,
            "forbidden_path_hits": 0,
            "recall_at_limit": 1.0,
            "mrr": 1.0,
            "negative_abstention": 1.0,
            "negative_case_count": 0,
        }

    def suite(self) -> dict[str, Any]:
        return {
            "baseline": self.metrics(),
            "influenced": self.metrics(),
            "changed_ranking_count": 0,
            "regressed_case_ids": [],
        }

    def gates(self, *, enabled: bool = True) -> dict[str, bool]:
        return {
            "off_identical": enabled,
            "no_critical_regression": enabled,
            "no_case_regression": enabled,
            "no_new_forbidden": enabled,
            "abstention_not_regressed": enabled,
            "registry_unambiguous": enabled,
            "registry_current": enabled,
            "channels_visible": enabled,
            "bounded": enabled,
            "deterministic": enabled,
        }

    def promotion_document(
        self,
        registry_digest: str,
        *,
        implementation_digest: str | None = None,
        promotable: bool = True,
    ) -> dict[str, Any]:
        backend = {
            "suites": {
                "v27": self.suite(),
                "challenges_v26": self.suite(),
                "cohort": self.suite(),
            },
            "gates": self.gates(enabled=promotable),
        }
        document: dict[str, Any] = {
            "schema": PROMOTION_EVIDENCE_SCHEMA,
            "status": "promotable" if promotable else "held",
            "registry": {"path": REGISTRY_PATH, "digest": registry_digest},
            "implementation_digest": (
                influence_implementation_digest()
                if implementation_digest is None
                else implementation_digest
            ),
            "fixture_digests": {
                "v27": "1" * 64,
                "v26": "2" * 64,
                "cohort": "3" * 64,
            },
            "limit": 5,
            "backends": {"local": backend, "cache": copy.deepcopy(backend)},
            "activation_authorized": False,
            "authority": "evidence_only",
            "authorizes_actions": False,
            "evidence_digest": "0" * 64,
        }
        self.refresh_evidence_digest(document)
        return document

    def refresh_evidence_digest(self, document: dict[str, Any]) -> None:
        body = copy.deepcopy(document)
        body.pop("evidence_digest", None)
        document["evidence_digest"] = hashlib.sha256(canonical_json(body)).hexdigest()

    def write_evidence(self, document: dict[str, Any]) -> str:
        target = self.root / EVIDENCE_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = canonical_json(document)
        target.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def setting(
        self,
        registry_digest: str,
        evidence_digest: str,
        *,
        evidence_path: str = EVIDENCE_PATH,
    ) -> InfluenceSetting:
        return InfluenceSetting(
            "enabled",
            REGISTRY_PATH,
            registry_digest,
            evidence_path,
            evidence_digest,
        )

    def activated(self) -> ActiveInfluence:
        registry_digest = self.write_registry(self.registry_document())
        evidence_digest = self.write_evidence(
            self.promotion_document(registry_digest)
        )
        active = activate_influence(
            self.setting(registry_digest, evidence_digest), root=self.root
        )
        self.assertIsInstance(active, ActiveInfluence)
        return active  # type: ignore[return-value]

    def assert_reason(
        self,
        reason: str,
        setting: InfluenceSetting,
    ) -> OntologyInfluenceError:
        with self.assertRaises(OntologyInfluenceError) as raised:
            activate_influence(setting, root=self.root)
        self.assertEqual(raised.exception.reason, reason)
        return raised.exception

    def test_missing_off_and_shadow_settings_are_inactive(self) -> None:
        missing = read_influence_setting(self.root)
        self.assertEqual(missing, InfluenceSetting("off", None, None, None, None))
        self.assertIsNone(activate_influence(missing, root=self.root))
        for mode in ("off", "shadow"):
            with self.subTest(mode=mode):
                self.write_config({"ontology_influence": {"mode": mode}})
                parsed = read_influence_setting(self.root)
                self.assertEqual(parsed.mode, mode)
                self.assertIsNone(activate_influence(parsed, root=self.root))

    def test_setting_parser_rejects_every_malformed_variant(self) -> None:
        enabled = {
            "mode": "enabled",
            "registry_digest": "a" * 64,
            "promotion_evidence": EVIDENCE_PATH,
            "promotion_evidence_digest": "b" * 64,
        }
        variants: list[object] = [
            [],
            {},
            {"mode": 1},
            {"mode": "unknown"},
            {"mode": "off", "extra": True},
            {"mode": "shadow", "registry": REGISTRY_PATH},
            {"mode": "enabled"},
            {**enabled, "extra": True},
            {**enabled, "registry": "/absolute.json"},
            {**enabled, "registry": "ontology/../registry.json"},
            {**enabled, "registry": "C:/absolute.json"},
            {**enabled, "promotion_evidence": "../evidence.json"},
            {**enabled, "registry_digest": "A" * 64},
            {**enabled, "promotion_evidence_digest": "short"},
        ]
        for index, value in enumerate(variants):
            with self.subTest(index=index):
                self.write_config({"ontology_influence": value})
                with self.assertRaises(OntologyInfluenceError) as raised:
                    read_influence_setting(self.root)
                self.assertEqual(raised.exception.reason, "setting_invalid")

    def test_malformed_configuration_is_a_typed_setting_error(self) -> None:
        (self.root / ".palimnex.json").write_text("{", encoding="utf-8")
        with self.assertRaises(OntologyInfluenceError) as raised:
            read_influence_setting(self.root)
        self.assertEqual(raised.exception.reason, "setting_invalid")

    def test_enabled_setting_defaults_registry_and_happy_path_activates(self) -> None:
        registry_digest = self.write_registry(self.registry_document())
        evidence_digest = self.write_evidence(
            self.promotion_document(registry_digest)
        )
        self.write_config(
            {
                "ontology_influence": {
                    "mode": "enabled",
                    "registry_digest": registry_digest,
                    "promotion_evidence": EVIDENCE_PATH,
                    "promotion_evidence_digest": evidence_digest,
                }
            }
        )
        parsed = read_influence_setting(self.root)
        self.assertEqual(parsed.registry_path, REGISTRY_PATH)
        active = activate_influence(parsed, root=self.root)
        self.assertIsNotNone(active)
        self.assertEqual(active.registry.registry_digest, registry_digest)  # type: ignore[union-attr]
        self.assertEqual(active.evidence_digest, evidence_digest)  # type: ignore[union-attr]

    def test_registry_load_and_digest_refusals_precede_evidence(self) -> None:
        registry_digest = self.write_registry(self.registry_document())
        error = self.assert_reason(
            "registry_digest_mismatch",
            self.setting("f" * 64, "0" * 64, evidence_path="missing.json"),
        )
        self.assertNotIn(registry_digest, str(error))

        candidate = self.registry_document(
            [self.concept(status="candidate")], kind="candidate_set"
        )
        candidate_digest = self.write_registry(candidate)
        self.assert_reason(
            "registry_kind_mismatch",
            self.setting(candidate_digest, "0" * 64, evidence_path="missing.json"),
        )

        foreign = self.registry_document(
            project_slug="foreign", project_id=FOREIGN_PROJECT_ID
        )
        foreign_digest = self.write_registry(foreign)
        self.assert_reason(
            "project_mismatch",
            self.setting(foreign_digest, "0" * 64, evidence_path="missing.json"),
        )

    def test_alias_and_canonical_name_collisions_are_ambiguous(self) -> None:
        cases = (
            [
                self.concept("concept.alpha", aliases=["shared alias"]),
                self.concept("concept.beta", aliases=["shared alias"]),
            ],
            [
                self.concept(
                    "concept.alpha", canonical_name="Shared Name", aliases=["alpha unique"]
                ),
                self.concept(
                    "concept.beta", canonical_name="shared-name", aliases=["beta unique"]
                ),
            ],
        )
        for concepts in cases:
            with self.subTest(concepts=[item["concept_id"] for item in concepts]):
                registry_digest = self.write_registry(self.registry_document(concepts))
                self.assert_reason(
                    "registry_ambiguous",
                    self.setting(registry_digest, "0" * 64, evidence_path="missing.json"),
                )

    def test_stale_binding_precedes_evidence(self) -> None:
        registry_digest = self.write_registry(self.registry_document())
        self.source.write_bytes(b"changed after registry binding\n")
        self.assert_reason(
            "registry_stale",
            self.setting(registry_digest, "0" * 64, evidence_path="missing.json"),
        )

    def test_registry_privacy_refusal_never_echoes_canary(self) -> None:
        canary = "".join(("sk", "-", "InfluenceCanary", "9876543210"))
        document = self.registry_document(
            [self.concept(definition=canary)]
        )
        registry_digest = self.write_registry(document)
        error = self.assert_reason(
            "registry_privacy_refused",
            self.setting(registry_digest, "0" * 64, evidence_path="missing.json"),
        )
        self.assertNotIn(canary, str(error))
        self.assertNotIn(canary, repr(error))

    def test_missing_and_tampered_evidence_are_distinct_refusals(self) -> None:
        registry_digest = self.write_registry(self.registry_document())
        self.assert_reason(
            "evidence_missing",
            self.setting(registry_digest, "0" * 64, evidence_path="missing.json"),
        )

        evidence = self.promotion_document(registry_digest)
        exact_digest = self.write_evidence(evidence)
        (self.root / EVIDENCE_PATH).write_bytes(canonical_json(evidence) + b"\n")
        self.assert_reason(
            "evidence_digest_mismatch",
            self.setting(registry_digest, exact_digest),
        )

    def test_evidence_privacy_refusal_never_echoes_canary(self) -> None:
        registry_digest = self.write_registry(self.registry_document())
        canary = "".join(("gh", "p_", "InfluenceEvidence", "9876543210"))
        evidence = self.promotion_document(registry_digest)
        evidence["backends"]["local"]["suites"]["v27"]["regressed_case_ids"] = [canary]
        self.refresh_evidence_digest(evidence)
        evidence_digest = self.write_evidence(evidence)
        error = self.assert_reason(
            "evidence_privacy_refused",
            self.setting(registry_digest, evidence_digest),
        )
        self.assertNotIn(canary, str(error))
        self.assertNotIn(canary, repr(error))

    def test_evidence_registry_implementation_status_and_backend_refusals(self) -> None:
        registry_digest = self.write_registry(self.registry_document())
        cases: list[tuple[str, dict[str, Any]]] = []

        other_registry = self.promotion_document("f" * 64)
        cases.append(("evidence_registry_mismatch", other_registry))

        other_implementation = self.promotion_document(
            registry_digest, implementation_digest="f" * 64
        )
        cases.append(("evidence_implementation_mismatch", other_implementation))

        held = self.promotion_document(registry_digest, promotable=False)
        cases.append(("evidence_not_promotable", held))

        incomplete = self.promotion_document(registry_digest)
        incomplete["backends"].pop("cache")
        self.refresh_evidence_digest(incomplete)
        cases.append(("evidence_backends_incomplete", incomplete))

        for reason, document in cases:
            with self.subTest(reason=reason):
                evidence_digest = self.write_evidence(document)
                self.assert_reason(
                    reason,
                    self.setting(registry_digest, evidence_digest),
                )

    def test_promotion_evidence_validator_checks_exact_shape_bounds_and_digest(self) -> None:
        registry_digest = self.write_registry(self.registry_document())
        valid = self.promotion_document(registry_digest)
        validate_promotion_evidence(valid)

        mutations = []
        extra = copy.deepcopy(valid)
        extra["extra"] = True
        mutations.append(extra)
        bad_bound = copy.deepcopy(valid)
        bad_bound["backends"]["local"]["suites"]["v27"]["baseline"]["case_count"] = -1
        mutations.append(bad_bound)
        bad_constant = copy.deepcopy(valid)
        bad_constant["activation_authorized"] = True
        mutations.append(bad_constant)
        bad_status = copy.deepcopy(valid)
        bad_status["status"] = "held"
        self.refresh_evidence_digest(bad_status)
        mutations.append(bad_status)
        bad_digest = copy.deepcopy(valid)
        bad_digest["evidence_digest"] = "f" * 64
        mutations.append(bad_digest)
        unsorted_ids = copy.deepcopy(valid)
        suite = unsorted_ids["backends"]["local"]["suites"]["v27"]
        suite["baseline"]["case_count"] = 2
        suite["influenced"]["case_count"] = 2
        suite["regressed_case_ids"] = ["case-b", "case-a"]
        self.refresh_evidence_digest(unsorted_ids)
        mutations.append(unsorted_ids)

        for index, document in enumerate(mutations):
            with self.subTest(index=index):
                with self.assertRaises(OntologyInfluenceError) as raised:
                    validate_promotion_evidence(document)
                self.assertEqual(raised.exception.reason, "evidence_invalid")

    def test_direct_setting_instances_are_revalidated(self) -> None:
        malformed = InfluenceSetting(
            "enabled", "../registry.json", "a" * 64, EVIDENCE_PATH, "b" * 64
        )
        self.assert_reason("setting_invalid", malformed)
        self.assert_reason(
            "setting_invalid",
            InfluenceSetting("off", REGISTRY_PATH, None, None, None),
        )

    def test_implementation_digest_is_stable_and_binds_all_four_sources(self) -> None:
        first = influence_implementation_digest()
        self.assertEqual(first, influence_implementation_digest())

        copy_root = self.root / "implementation"
        copy_root.mkdir()
        copied: list[tuple[str, Path]] = []
        for module, source in influence_module._IMPLEMENTATION_SOURCE_PATHS:
            target = copy_root / source.name
            target.write_bytes(source.read_bytes())
            copied.append((module, target))
        with patch.object(
            influence_module, "_IMPLEMENTATION_SOURCE_PATHS", tuple(copied)
        ):
            self.assertEqual(influence_implementation_digest(), first)
            for index, (module, target) in enumerate(copied):
                original = target.read_bytes()
                target.write_bytes(original + b"\n")
                changed = influence_implementation_digest()
                self.assertNotEqual(changed, first, module)
                target.write_bytes(original)
                self.assertEqual(influence_implementation_digest(), first, module)

    def test_disclosure_has_exact_shape(self) -> None:
        active = self.activated()
        channel = OntologyChannel(
            (0,),
            ("concept.alpha",),
            (),
            ("concept.alpha",),
            (),
            (),
            (),
            1,
            False,
        )
        disclosure = influence_disclosure(active, channel)
        self.assertEqual(
            list(disclosure),
            [
                "mode",
                "channel",
                "retrieval_influence",
                "registry_digest",
                "promotion_evidence_digest",
                "implementation_digest",
                "contributing_concept_ids",
            ],
        )
        self.assertEqual(disclosure["mode"], "enabled")
        self.assertEqual(disclosure["channel"], "ontology")
        self.assertIs(disclosure["retrieval_influence"], True)
        self.assertEqual(disclosure["contributing_concept_ids"], ["concept.alpha"])

    def test_v2_wrappers_keep_every_v1_key_and_mutate_no_input(self) -> None:
        disclosure = {
            "mode": "enabled",
            "channel": "ontology",
            "retrieval_influence": True,
            "registry_digest": "a" * 64,
            "promotion_evidence_digest": "b" * 64,
            "implementation_digest": "c" * 64,
            "contributing_concept_ids": ["concept.alpha"],
        }
        context = {
            "schema": "project-memory:context:v1",
            "items": [{"pointer": "docs/source.md:1"}],
            "authorizes_actions": False,
        }
        explain = {
            "schema": "palimnex:explain-search:v1",
            "search": {"results": [{"pointer": "docs/source.md:1"}]},
            "coverage": None,
        }
        context_before = copy.deepcopy(context)
        explain_before = copy.deepcopy(explain)
        disclosure_before = copy.deepcopy(disclosure)

        wrapped_context = context_v2(context, disclosure)
        wrapped_explain = explain_search_v2(explain, disclosure)

        self.assertEqual(context, context_before)
        self.assertEqual(explain, explain_before)
        self.assertEqual(disclosure, disclosure_before)
        self.assertEqual(wrapped_context["schema"], CONTEXT_V2_SCHEMA)
        self.assertEqual(wrapped_explain["schema"], EXPLAIN_SEARCH_V2_SCHEMA)
        self.assertEqual(set(context) - {"schema"}, set(wrapped_context) - {"schema", "ontology_influence"})
        self.assertEqual(set(explain) - {"schema"}, set(wrapped_explain) - {"schema", "ranking_influence"})

        wrapped_context["items"][0]["pointer"] = "changed"
        wrapped_context["ontology_influence"]["contributing_concept_ids"].append("concept.beta")
        wrapped_explain["search"]["results"][0]["pointer"] = "changed"
        self.assertEqual(context, context_before)
        self.assertEqual(explain, explain_before)
        self.assertEqual(disclosure, disclosure_before)


if __name__ == "__main__":
    unittest.main()
