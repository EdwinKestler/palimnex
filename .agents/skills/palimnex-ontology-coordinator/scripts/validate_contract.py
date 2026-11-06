#!/usr/bin/env python3
"""Validate ontology task and receipt contracts without network resolution."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from palimnex.durable import canonical_json


HERE = Path(__file__).resolve().parent
COORDINATOR_ASSETS = HERE.parent / "assets"
SKILLS = HERE.parents[1]
WORKSTREAM_ASSETS = SKILLS / "palimnex-ontology-workstream" / "assets"
REVIEW_ASSETS = SKILLS / "palimnex-ontology-review" / "assets"

SCHEMA_PATHS = {
    "approval": COORDINATOR_ASSETS / "approval-evidence.v1.schema.json",
    "task": COORDINATOR_ASSETS / "workstream-task.v1.schema.json",
    "implementation": WORKSTREAM_ASSETS / "implementation-receipt.v1.schema.json",
    "patch": WORKSTREAM_ASSETS / "integration-patch-proposal.v1.schema.json",
    "review": REVIEW_ASSETS / "review-receipt.v1.schema.json",
    "manifest": COORDINATOR_ASSETS / "workstream-manifest.v1.schema.json",
}

PHASE_ACTIONS = {
    0: "ontology_phase_0_contract",
    1: "ontology_phase_1_registry",
    2: "ontology_phase_2_coverage",
    3: "ontology_phase_3_shadow",
    4: "ontology_phase_4_semantic",
    5: "ontology_phase_5_extensions",
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _schemas() -> tuple[dict[str, dict[str, Any]], Registry]:
    schemas = {name: _load(path) for name, path in SCHEMA_PATHS.items()}
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema))
        for schema in schemas.values()
    )
    return schemas, registry


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def validate_task(task: dict[str, Any]) -> dict[str, str]:
    schemas, registry = _schemas()
    Draft202012Validator(
        schemas["task"], registry=registry, format_checker=FormatChecker()
    ).validate(task)
    approval = task["approval_evidence"]
    Draft202012Validator(
        schemas["approval"], registry=registry, format_checker=FormatChecker()
    ).validate(approval)

    if task["phase"] not in approval["approved_phases"]:
        raise ValueError("task phase is outside approval evidence")
    if task["action_id"] != PHASE_ACTIONS[task["phase"]]:
        raise ValueError("task action does not match its phase")
    if task["approved_design_identity"] != approval["design_identity"]:
        raise ValueError("task design identity differs from approval evidence")
    if task["action_id"] not in approval["authorized_actions"]:
        raise ValueError("task action is not authorized")
    if task["action_id"] in approval["excluded_actions"]:
        raise ValueError("task action is explicitly excluded")
    for task_field, approval_field in (
        ("network_authority", "network_authorized"),
        ("git_write_authority", "git_write_authorized"),
        ("live_state_authority", "live_state_authorized"),
    ):
        if task[task_field] and not approval[approval_field]:
            raise ValueError(f"{task_field} exceeds approval evidence")
    if not task["approved_design_identity"]["path"].startswith("docs/"):
        raise ValueError("approved implementation design must be under docs/")
    if not approval["source_proposal_identity"]["path"].startswith("artifacts/design/"):
        raise ValueError("source proposal identity must be under artifacts/design/")
    return {
        "task_digest": digest(task),
        "approval_evidence_digest": digest(approval),
    }


def _is_ancestor_or_same(left: str, right: str) -> bool:
    left_parts = Path(left).parts
    right_parts = Path(right).parts
    return left_parts == right_parts[: len(left_parts)]


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    schemas, registry = _schemas()
    Draft202012Validator(schemas["manifest"], registry=registry).validate(manifest)

    workstreams = set(manifest["workstreams"])
    ownership = manifest["exclusive_file_ownership"]
    if set(ownership) != workstreams:
        raise ValueError("manifest ownership keys must exactly match workstreams")
    if manifest["shared_file_owner"] not in workstreams:
        raise ValueError("shared file owner must name a manifest workstream")

    owned: list[tuple[str, str]] = []
    for owner, paths in ownership.items():
        for path in paths:
            for existing_owner, existing_path in owned:
                if owner != existing_owner and (
                    _is_ancestor_or_same(path, existing_path)
                    or _is_ancestor_or_same(existing_path, path)
                ):
                    raise ValueError(
                        "manifest writable ownership overlaps: "
                        f"{owner}:{path} and {existing_owner}:{existing_path}"
                    )
            owned.append((owner, path))

    adjacency = {workstream: [] for workstream in workstreams}
    indegree = {workstream: 0 for workstream in workstreams}
    seen_edges: set[tuple[str, str]] = set()
    for edge in manifest["dependency_dag"]:
        source, target = edge["from"], edge["to"]
        if source not in workstreams or target not in workstreams:
            raise ValueError("manifest dependency names an unknown workstream")
        if source == target:
            raise ValueError("manifest dependency cannot be a self-edge")
        pair = (source, target)
        if pair in seen_edges:
            raise ValueError("manifest dependency edge is duplicated")
        seen_edges.add(pair)
        adjacency[source].append(target)
        indegree[target] += 1

    ready = [node for node, degree in indegree.items() if degree == 0]
    visited = 0
    while ready:
        node = ready.pop()
        visited += 1
        for target in adjacency[node]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    if visited != len(workstreams):
        raise ValueError("manifest dependency graph contains a cycle")

    return {
        "schema": "palimnex:ontology-manifest-validation:v1",
        "manifest_digest": digest(manifest),
        "status": "valid",
        "authorizes_actions": False,
    }


def validate_workstream_bundle(
    manifest: dict[str, Any], tasks: list[dict[str, Any]]
) -> dict[str, Any]:
    manifest_report = validate_manifest(manifest)
    if not tasks:
        raise ValueError("manifest execution bundle requires task cards")

    tasks_by_id: dict[str, dict[str, Any]] = {}
    task_digests: dict[str, str] = {}
    for task in tasks:
        identities = validate_task(task)
        workstream_id = task["workstream_id"]
        if workstream_id in tasks_by_id:
            raise ValueError(f"duplicate task card for workstream {workstream_id}")
        tasks_by_id[workstream_id] = task
        task_digests[workstream_id] = identities["task_digest"]

    manifest_workstreams = set(manifest["workstreams"])
    if set(tasks_by_id) != manifest_workstreams:
        raise ValueError("bundle task IDs must exactly match manifest workstreams")

    incoming = {workstream: set() for workstream in manifest_workstreams}
    for edge in manifest["dependency_dag"]:
        incoming[edge["to"]].add(edge["from"])

    for workstream_id, task in tasks_by_id.items():
        if task["phase"] != manifest["approved_phase"]:
            raise ValueError(f"task {workstream_id} phase differs from manifest")
        if task["approved_design_identity"] != manifest["design_identity"]:
            raise ValueError(f"task {workstream_id} design differs from manifest")
        if set(task["owned_paths"]) != set(
            manifest["exclusive_file_ownership"][workstream_id]
        ):
            raise ValueError(f"task {workstream_id} ownership differs from manifest")
        if set(task["dependencies"]) != incoming[workstream_id]:
            raise ValueError(f"task {workstream_id} dependencies differ from manifest")

    return {
        "schema": "palimnex:ontology-workstream-bundle-validation:v1",
        "manifest_digest": manifest_report["manifest_digest"],
        "task_digests": dict(sorted(task_digests.items())),
        "status": "valid",
        "authorizes_actions": False,
    }


def validate_receipts(
    task: dict[str, Any],
    implementation: dict[str, Any] | None = None,
    review: dict[str, Any] | None = None,
    patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    schemas, registry = _schemas()
    identities = validate_task(task)
    expected = {
        "workstream_id": task["workstream_id"],
        "design_identity": task["approved_design_identity"],
        **identities,
    }
    if implementation is not None:
        Draft202012Validator(
            schemas["implementation"], registry=registry
        ).validate(implementation)
        for field, value in expected.items():
            if implementation[field] != value:
                raise ValueError(f"implementation receipt {field} mismatch")
        if not set(implementation["files_changed"]) <= set(task["owned_paths"]):
            raise ValueError("implementation receipt names files outside owned paths")
    if review is not None:
        Draft202012Validator(schemas["review"], registry=registry).validate(review)
        for field, value in expected.items():
            if review[field] != value:
                raise ValueError(f"review receipt {field} mismatch")
    if patch is not None:
        Draft202012Validator(schemas["patch"], registry=registry).validate(patch)
        for field, value in expected.items():
            if field in patch and patch[field] != value:
                raise ValueError(f"integration patch proposal {field} mismatch")
    return {
        "schema": "palimnex:ontology-contract-validation:v1",
        **identities,
        "implementation_receipt_validated": implementation is not None,
        "review_receipt_validated": review is not None,
        "integration_patch_proposal_validated": patch is not None,
        "status": "valid",
        "authorizes_actions": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", type=Path, nargs="?")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--task-card", type=Path, action="append", default=[])
    parser.add_argument("--implementation-receipt", type=Path)
    parser.add_argument("--review-receipt", type=Path)
    parser.add_argument("--patch-proposal", type=Path)
    args = parser.parse_args()
    if args.manifest:
        if (
            args.task
            or args.implementation_receipt
            or args.review_receipt
            or args.patch_proposal
        ):
            parser.error("--manifest cannot be combined with task or receipt inputs")
        if args.task_card:
            report = validate_workstream_bundle(
                _load(args.manifest), [_load(path) for path in args.task_card]
            )
        else:
            report = validate_manifest(_load(args.manifest))
        print(json.dumps(report, sort_keys=True))
        return 0
    if args.task_card:
        parser.error("--task-card requires --manifest")
    if not args.task:
        parser.error("a task or --manifest is required")
    report = validate_receipts(
        _load(args.task),
        _load(args.implementation_receipt) if args.implementation_receipt else None,
        _load(args.review_receipt) if args.review_receipt else None,
        _load(args.patch_proposal) if args.patch_proposal else None,
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
