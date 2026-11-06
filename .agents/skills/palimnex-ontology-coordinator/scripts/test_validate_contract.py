#!/usr/bin/env python3
"""Regression tests for ontology parallel-work contract validation."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

from jsonschema import ValidationError


MODULE_PATH = Path(__file__).with_name("validate_contract.py")
SPEC = importlib.util.spec_from_file_location("ontology_contract_validator", MODULE_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def task() -> dict:
    design = {"path": "docs/ONTOLOGY_ADOPTION.md", "sha256": "a" * 64}
    proposal = {
        "path": "artifacts/design/Ontologyadoptionplan.md",
        "sha256": "b" * 64,
    }
    approval = {
        "schema": "palimnex:ontology-approval-evidence:v1",
        "authority_source": "user_message",
        "evidence_locator": "conversation-turn-1",
        "grantor_claim": "repository owner",
        "design_identity": design,
        "source_proposal_identity": proposal,
        "approved_phases": [1, 2],
        "authorized_actions": [
            "ontology_phase_1_registry",
            "ontology_phase_2_coverage",
        ],
        "excluded_actions": ["ontology_phase_3_shadow"],
        "recorded_at": "2026-11-05T12:00:00Z",
        "implementation_authorized": True,
        "network_authorized": False,
        "git_write_authorized": False,
        "live_state_authorized": False,
    }
    return {
        "schema": "palimnex:ontology-workstream-task:v1",
        "workstream_id": "ontology-registry",
        "phase": 1,
        "action_id": "ontology_phase_1_registry",
        "objective": "Implement the approved registry contract.",
        "exclusions": [],
        "approved_design_identity": design,
        "approval_evidence": approval,
        "owned_paths": ["palimnex/ontology.py"],
        "read_only_paths": ["palimnex/retrieval.py"],
        "forbidden_paths": [".palimnex"],
        "dependencies": [],
        "acceptance_commands": ["python3 -m unittest"],
        "required_output": "ImplementationReceipt",
        "network_authority": False,
        "git_write_authority": False,
        "live_state_authority": False,
    }


def manifest() -> dict:
    return {
        "schema": "palimnex:ontology-workstream-manifest:v1",
        "approved_phase": 1,
        "design_identity": {
            "path": "docs/ONTOLOGY_ADOPTION.md",
            "sha256": "a" * 64,
        },
        "workstreams": ["registry", "coverage", "integration"],
        "dependency_dag": [
            {"from": "registry", "to": "integration"},
            {"from": "coverage", "to": "integration"},
        ],
        "exclusive_file_ownership": {
            "registry": ["palimnex/ontology.py"],
            "coverage": ["palimnex/coverage.py"],
            "integration": ["palimnex/core.py"],
        },
        "shared_file_owner": "integration",
        "acceptance_gates": ["focused tests pass"],
        "authority_limits": ["no Git writes"],
        "status": "ready",
    }


def bundle_tasks() -> list[dict]:
    value = manifest()
    incoming = {workstream: [] for workstream in value["workstreams"]}
    for edge in value["dependency_dag"]:
        incoming[edge["to"]].append(edge["from"])
    tasks = []
    for workstream in value["workstreams"]:
        card = task()
        card["workstream_id"] = workstream
        card["owned_paths"] = value["exclusive_file_ownership"][workstream]
        card["dependencies"] = incoming[workstream]
        tasks.append(card)
    return tasks


class ContractValidationTests(unittest.TestCase):
    def test_task_accepts_matching_phase_and_action(self) -> None:
        self.assertIn("task_digest", VALIDATOR.validate_task(task()))

    def test_task_rejects_cross_phase_action(self) -> None:
        value = task()
        value["action_id"] = "ontology_phase_2_coverage"
        with self.assertRaisesRegex(ValueError, "does not match its phase"):
            VALIDATOR.validate_task(value)

    def test_manifest_accepts_disjoint_acyclic_work(self) -> None:
        self.assertEqual(VALIDATOR.validate_manifest(manifest())["status"], "valid")

    def test_manifest_rejects_overlapping_ownership(self) -> None:
        value = manifest()
        value["exclusive_file_ownership"]["coverage"] = ["palimnex"]
        with self.assertRaisesRegex(ValueError, "ownership overlaps"):
            VALIDATOR.validate_manifest(value)

    def test_manifest_rejects_dependency_cycle(self) -> None:
        value = manifest()
        value["dependency_dag"].append({"from": "integration", "to": "registry"})
        with self.assertRaisesRegex(ValueError, "contains a cycle"):
            VALIDATOR.validate_manifest(value)

    def test_bundle_accepts_exact_manifest_tasks(self) -> None:
        self.assertEqual(
            VALIDATOR.validate_workstream_bundle(manifest(), bundle_tasks())["status"],
            "valid",
        )

    def test_bundle_rejects_task_ownership_mismatch(self) -> None:
        tasks = bundle_tasks()
        tasks[1]["owned_paths"] = ["palimnex/registry.py"]
        with self.assertRaisesRegex(ValueError, "ownership differs"):
            VALIDATOR.validate_workstream_bundle(manifest(), tasks)

    def test_bundle_rejects_task_dependency_mismatch(self) -> None:
        tasks = bundle_tasks()
        tasks[2]["dependencies"] = []
        with self.assertRaisesRegex(ValueError, "dependencies differ"):
            VALIDATOR.validate_workstream_bundle(manifest(), tasks)

    def test_patch_schema_rejects_traversal(self) -> None:
        schemas, registry = VALIDATOR._schemas()
        patch = {
            "schema": "palimnex:ontology-integration-patch-proposal:v1",
            "workstream_id": "ontology-registry",
            "task_digest": "c" * 64,
            "approval_evidence_digest": "d" * 64,
            "design_identity": {
                "path": "docs/ONTOLOGY_ADOPTION.md",
                "sha256": "a" * 64,
            },
            "target_path": "../../etc/passwd",
            "requested_change": "none",
            "rationale": "negative test",
            "dependency_effect": "none",
            "compatibility_effect": "none",
            "status": "proposed",
        }
        with self.assertRaises(ValidationError):
            VALIDATOR.Draft202012Validator(
                schemas["patch"], registry=registry
            ).validate(patch)


if __name__ == "__main__":
    unittest.main()
