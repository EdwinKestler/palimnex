#!/usr/bin/env python3
"""Offline checks for the Phase 0 draft concept-registry contract."""

from __future__ import annotations

import hashlib
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from palimnex.durable import canonical_json  # noqa: E402
from palimnex.locators import SourceLocator, resolve_locator  # noqa: E402
from palimnex.security import scan_bytes  # noqa: E402


SCHEMA_PATH = HERE / "concept-registry.v1.schema.json"
LOCATOR_SCHEMA_PATH = ROOT / "palimnex/schemas/source-locator.v1.schema.json"
CONFIG_PATH = ROOT / ".palimnex.json"
MAX_REGISTRY_BYTES = 1_000_000
CONCEPT_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
SHARED_DEFS = {"alias", "conceptId", "projectIdentity"}


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def load_json(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    if len(raw) > MAX_REGISTRY_BYTES:
        raise ValueError("registry exceeds 1000000-byte limit")
    value = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_object_without_duplicates,
        parse_constant=_reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("registry must be a JSON object")
    return value, raw


def normalize_alias(value: str) -> str:
    folded = unicodedata.normalize("NFKC", value).casefold()
    mapped: list[str] = []
    for character in folded:
        category = unicodedata.category(character)
        if category.startswith("C"):
            raise ValueError("alias contains a forbidden Unicode category")
        if category.startswith(("P", "Z")) or character.isspace():
            mapped.append(" ")
        else:
            mapped.append(character)
    result = " ".join("".join(mapped).split())
    if not result or len(result) > 128:
        raise ValueError("normalized alias is empty or exceeds 128 code points")
    return result


def registry_digest(document: dict[str, Any]) -> str:
    body = dict(document)
    body.pop("registry_digest", None)
    return hashlib.sha256(canonical_json(body)).hexdigest()


def semantic_errors(document: dict[str, Any], *, verify_sources: bool) -> list[str]:
    errors: list[str] = []
    config, _ = load_json(CONFIG_PATH)
    expected_project = {
        "project_slug": config.get("project_slug"),
        "project_id": config.get("project_id"),
    }
    if document.get("project") != expected_project:
        errors.append("project identity does not match .palimnex.json")

    concepts = document.get("concepts")
    if not isinstance(concepts, list):
        return errors

    by_id: dict[str, dict[str, Any]] = {}
    for concept in concepts:
        if not isinstance(concept, dict) or not isinstance(concept.get("concept_id"), str):
            continue
        concept_id = concept["concept_id"]
        if concept_id in by_id:
            errors.append(f"duplicate concept ID: {concept_id}")
        by_id[concept_id] = concept

    kind = document.get("registry_kind")
    for concept_id, concept in by_id.items():
        status = concept.get("status")
        if kind == "approved_registry" and status == "candidate":
            errors.append(f"candidate appears in approved registry: {concept_id}")
        if kind == "candidate_set" and status not in {"candidate", "withdrawn"}:
            errors.append(f"trusted status appears in candidate set: {concept_id}")

        matching_keys: set[str] = set()
        try:
            canonical_key = normalize_alias(concept.get("canonical_name", ""))
            matching_keys.add(canonical_key)
        except (TypeError, ValueError) as exc:
            errors.append(f"invalid canonical name for {concept_id}: {exc}")
        for alias in concept.get("aliases", []):
            try:
                normalized = normalize_alias(alias)
            except (TypeError, ValueError) as exc:
                errors.append(f"invalid alias for {concept_id}: {exc}")
                continue
            if normalized != alias:
                errors.append(f"alias is not stored normalized for {concept_id}")
            if normalized in matching_keys:
                errors.append(f"duplicate matching key within {concept_id}")
            matching_keys.add(normalized)

        seen_relations: set[tuple[str, str]] = set()
        for relation in concept.get("relations", []):
            if not isinstance(relation, dict):
                continue
            relation_key = (
                relation.get("relation_type", ""),
                relation.get("target_concept_id", ""),
            )
            if relation_key in seen_relations:
                errors.append(f"duplicate relation in {concept_id}")
            seen_relations.add(relation_key)
            if relation_key[1] not in by_id:
                errors.append(f"relation target is absent for {concept_id}")

        if verify_sources:
            for binding in concept.get("source_bindings", []):
                try:
                    locator = SourceLocator.from_dict(binding)
                    resolve_locator(locator, ROOT, {})
                except (TypeError, ValueError):
                    errors.append(f"source binding is stale or invalid for {concept_id}")

    successor_counts: dict[str, int] = {}
    for concept_id, concept in by_id.items():
        predecessor = concept.get("predecessor_concept_id")
        if predecessor is None:
            continue
        if predecessor == concept_id:
            errors.append(f"self supersession for {concept_id}")
        if predecessor not in by_id:
            errors.append(f"missing predecessor for {concept_id}")
            continue
        successor_counts[predecessor] = successor_counts.get(predecessor, 0) + 1
        if by_id[predecessor].get("status") != "superseded":
            errors.append(f"predecessor is not superseded for {concept_id}")
        if concept.get("status") not in {"approved", "superseded"}:
            errors.append(f"successor has invalid status for {concept_id}")
    for predecessor, count in successor_counts.items():
        if count > 1:
            errors.append(f"supersession fork at {predecessor}")

    for start in by_id:
        seen: set[str] = set()
        current: str | None = start
        while current in by_id:
            if current in seen:
                errors.append(f"supersession cycle containing {start}")
                break
            seen.add(current)
            predecessor = by_id[current].get("predecessor_concept_id")
            current = predecessor if isinstance(predecessor, str) else None

    expected_digest = document.get("registry_digest")
    if isinstance(expected_digest, str) and registry_digest(document) != expected_digest:
        errors.append("registry digest mismatch")
    return errors


def main() -> int:
    schema, _ = load_json(SCHEMA_PATH)
    locator_schema, _ = load_json(LOCATOR_SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator.check_schema(locator_schema)
    local_registry = Registry().with_resource(
        locator_schema["$id"], Resource.from_contents(locator_schema)
    )
    validator = Draft202012Validator(schema, registry=local_registry)

    failures: list[str] = []
    definitions = schema.get("$defs", {})
    if not SHARED_DEFS.issubset(definitions):
        failures.append("registry schema must retain shared $defs names")
    concept_id = definitions.get("conceptId", {})
    if concept_id.get("pattern") != CONCEPT_ID_PATTERN:
        failures.append("conceptId pattern does not match the reconciled contract")
    if concept_id.get("minLength") != 3 or concept_id.get("maxLength") != 128:
        failures.append("conceptId bounds do not match the reconciled contract")
    concept = definitions.get("concept", {}).get("properties", {})
    if concept.get("aliases", {}).get("items", {}).get("$ref") != "#/$defs/alias":
        failures.append("concept aliases must use the shared alias definition")
    if schema.get("properties", {}).get("project", {}).get("$ref") != "#/$defs/projectIdentity":
        failures.append("project must use the shared projectIdentity definition")

    valid_paths = sorted((HERE / "examples/valid").glob("*.json"))
    invalid_paths = sorted((HERE / "examples/invalid").glob("*.json"))
    if len(valid_paths) < 3:
        failures.append("at least three valid examples are required")
    if len(invalid_paths) < 6:
        failures.append("at least six invalid examples are required")

    underscore_id_covered = False
    for path in valid_paths:
        try:
            document, _ = load_json(path)
            underscore_id_covered = underscore_id_covered or any(
                isinstance(item, dict)
                and isinstance(item.get("concept_id"), str)
                and "_" in item["concept_id"]
                for item in document.get("concepts", [])
            )
            schema_errors = sorted(validator.iter_errors(document), key=lambda item: list(item.path))
            semantic = semantic_errors(document, verify_sources=True)
            if schema_errors or semantic:
                details = [error.message for error in schema_errors] + semantic
                failures.append(f"valid example {path.name} failed: {'; '.join(details)}")
            else:
                print(f"PASS valid {path.name}")
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            failures.append(f"valid example {path.name} could not be checked: {exc}")

    doubled_separator_covered = False
    for path in invalid_paths:
        try:
            document, _ = load_json(path)
            doubled_separator_covered = doubled_separator_covered or any(
                isinstance(item, dict) and item.get("concept_id") == "a__b"
                for item in document.get("concepts", [])
            )
            schema_errors = list(validator.iter_errors(document))
            semantic = semantic_errors(document, verify_sources=False) if not schema_errors else []
            if not schema_errors and not semantic:
                failures.append(f"invalid example unexpectedly passed: {path.name}")
            else:
                print(f"PASS invalid {path.name}")
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            print(f"PASS invalid {path.name}")

    if not underscore_id_covered:
        failures.append("a valid underscore concept ID example is required")
    if not doubled_separator_covered:
        failures.append("an invalid doubled-separator concept ID example is required")

    canary = "".join(("gh", "p_", "A7b9" * 6))
    findings = scan_bytes(("candidate=" + canary).encode("utf-8"))
    if not findings or canary in repr(findings):
        failures.append("privacy canary was not refused without value echo")
    else:
        print("PASS privacy admission precedes derivation and does not echo values")

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1
    print(
        f"PASS concept registry contract: {len(valid_paths)} valid, "
        f"{len(invalid_paths)} invalid"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
