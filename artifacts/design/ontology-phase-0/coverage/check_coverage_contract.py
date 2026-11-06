#!/usr/bin/env python3
"""Offline checks for the Phase 0 retrieval-coverage contract draft."""

from __future__ import annotations

import hashlib
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from palimnex.cache_v3 import index_policy_digest, source_snapshot
from palimnex.durable import canonical_json
from palimnex.locators import SourceLocator, resolve_locator


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SCHEMA_PATH = HERE / "retrieval-coverage.v1.schema.json"
REGISTRY_SCHEMA_PATH = HERE.parent / "registry" / "concept-registry.v1.schema.json"
LOCATOR_SCHEMA_PATH = ROOT / "palimnex" / "schemas" / "source-locator.v1.schema.json"
CONFIG_PATH = ROOT / ".palimnex.json"
VALID_DIR = HERE / "examples" / "valid"
INVALID_DIR = HERE / "examples" / "invalid"
REGISTRY_SCHEMA_ID = "https://palimnex.dev/schemas/concept-registry.v1.schema.json"
CONCEPT_ID_REF = f"{REGISTRY_SCHEMA_ID}#/$defs/conceptId"
ALIAS_REF = f"{REGISTRY_SCHEMA_ID}#/$defs/alias"
PROJECT_IDENTITY_REF = f"{REGISTRY_SCHEMA_ID}#/$defs/projectIdentity"
COLLECTIONS = (
    "recognized_concepts",
    "covered_concepts",
    "uncovered_concepts",
    "ambiguous_concepts",
    "stale_concepts",
)


def load_json(path: Path) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant {value} is forbidden")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)


def schema_validator() -> Draft202012Validator:
    schema = load_json(SCHEMA_PATH)
    registry_schema = load_json(REGISTRY_SCHEMA_PATH)
    locator_schema = load_json(LOCATOR_SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator.check_schema(registry_schema)
    Draft202012Validator.check_schema(locator_schema)
    registry = Registry().with_resources(
        [
            (registry_schema["$id"], Resource.from_contents(registry_schema)),
            (locator_schema["$id"], Resource.from_contents(locator_schema)),
        ]
    )
    return Draft202012Validator(schema, registry=registry)


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
    return " ".join("".join(mapped).split())


def all_refs(value: Any) -> list[str]:
    if isinstance(value, dict):
        refs = [value["$ref"]] if isinstance(value.get("$ref"), str) else []
        return refs + [ref for child in value.values() for ref in all_refs(child)]
    if isinstance(value, list):
        return [ref for child in value for ref in all_refs(child)]
    return []


def schema_contract_errors() -> list[str]:
    schema = load_json(SCHEMA_PATH)
    errors: list[str] = []
    definitions = schema.get("$defs", {})
    if "conceptId" in definitions or "alias" in definitions:
        errors.append("coverage schema must not copy registry conceptId or alias definitions")
    project_ref = (
        definitions.get("identities", {}).get("properties", {})
        .get("project", {}).get("$ref")
    )
    if project_ref != PROJECT_IDENTITY_REF:
        errors.append("coverage project identity must reference the registry definition")
    refs = all_refs(schema)
    if CONCEPT_ID_REF not in refs or ALIAS_REF not in refs:
        errors.append("coverage concept and alias fields must reference registry definitions")
    if any(ref in {"#/$defs/conceptId", "#/$defs/alias"} for ref in refs):
        errors.append("coverage schema retains a local concept or alias reference")
    return errors


def current_source_errors(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    config = load_json(CONFIG_PATH)
    identities = document["identities"]
    expected_project = {
        "project_id": config.get("project_id"),
        "project_slug": config.get("project_slug"),
    }
    if identities["project"] != expected_project:
        errors.append("project identity does not match .palimnex.json")
    expected_checkout = hashlib.sha256(str(ROOT.resolve()).encode("utf-8", errors="strict")).hexdigest()
    if identities["checkout"]["checkout_id"] != expected_checkout:
        errors.append("checkout identity does not match the resolved repository root")
    snapshot = source_snapshot(ROOT)
    if identities["corpus"]["fingerprint"] != snapshot.fingerprint:
        errors.append("corpus fingerprint does not match current admitted source")
    if identities["corpus"]["index_policy_digest"] != index_policy_digest(ROOT):
        errors.append("index policy digest does not match current source-admission policy")
    for item in document["covered_concepts"]["items"]:
        for binding in item["verified_bindings"]:
            try:
                resolve_locator(SourceLocator.from_dict(binding), ROOT, {})
            except (TypeError, ValueError):
                errors.append(f"covered source binding is not current for {item['concept_id']}")
    for item in document["stale_concepts"]["items"]:
        for binding in item["stale_bindings"]:
            try:
                resolve_locator(SourceLocator.from_dict(binding), ROOT, {})
            except (TypeError, ValueError):
                continue
            errors.append(f"stale source binding unexpectedly resolves for {item['concept_id']}")
    return errors


def visible_count(collection: dict[str, Any], errors: list[str], label: str) -> None:
    items = collection["items"]
    total = collection["total_count"]
    if type(total) is not int:
        errors.append(f"{label}.total_count must be a JSON integer")
        return
    if total < len(items):
        errors.append(f"{label}.total_count is smaller than its visible list")
    if not collection["truncated"] and total != len(items):
        errors.append(f"{label}.total_count must equal visible length when not truncated")


def nested_count(
    item: dict[str, Any], list_key: str, count_key: str, truncated_key: str,
    errors: list[str], label: str,
) -> None:
    values = item[list_key]
    total = item[count_key]
    if type(total) is not int:
        errors.append(f"{label}.{count_key} must be a JSON integer")
        return
    if total < len(values):
        errors.append(f"{label}.{count_key} is smaller than its visible list")
    if not item[truncated_key] and total != len(values):
        errors.append(f"{label}.{count_key} must equal visible length when not truncated")


def strictly_sorted_unique(values: list[Any]) -> bool:
    return values == sorted(values) and len(values) == len(set(values))


def locator_key(locator: dict[str, Any]) -> tuple[Any, ...]:
    bounds = locator["range"]
    return (
        locator["scheme"], locator["source_id"], locator["version"],
        bounds["unit"], bounds["start"], bounds["end"], locator["digest"],
    )


def cross_field_errors(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for name in COLLECTIONS:
        visible_count(document[name], errors, name)

    recognized_items = document["recognized_concepts"]["items"]
    covered_items = document["covered_concepts"]["items"]
    uncovered_ids = document["uncovered_concepts"]["items"]
    ambiguous_items = document["ambiguous_concepts"]["items"]
    stale_items = document["stale_concepts"]["items"]

    recognized_ids = [item["concept_id"] for item in recognized_items]
    covered_ids = [item["concept_id"] for item in covered_items]
    stale_ids = [item["concept_id"] for item in stale_items]
    if not strictly_sorted_unique(recognized_ids):
        errors.append("recognized concepts must be sorted by unique concept_id")
    if not strictly_sorted_unique(covered_ids):
        errors.append("covered concepts must be sorted by unique concept_id")
    if not strictly_sorted_unique(uncovered_ids):
        errors.append("uncovered concepts must be sorted and unique")
    if not strictly_sorted_unique(stale_ids):
        errors.append("stale concepts must be sorted by unique concept_id")

    for index, item in enumerate(recognized_items):
        nested_count(item, "matched_aliases", "matched_alias_count", "matched_aliases_truncated", errors, f"recognized[{index}]")
        if not strictly_sorted_unique(item["matched_aliases"]):
            errors.append(f"recognized[{index}] aliases must be sorted and unique")
        for alias in item["matched_aliases"]:
            try:
                normalized = normalize_alias(alias)
            except (TypeError, ValueError) as exc:
                errors.append(f"recognized[{index}] alias is invalid: {exc}")
                continue
            if alias != normalized:
                errors.append(f"recognized[{index}] alias is not stored normalized")
    for index, item in enumerate(covered_items):
        nested_count(item, "verified_bindings", "verified_binding_count", "verified_bindings_truncated", errors, f"covered[{index}]")
        keys = [locator_key(value) for value in item["verified_bindings"]]
        if not strictly_sorted_unique(keys):
            errors.append(f"covered[{index}] bindings must be sorted and unique")
    for index, item in enumerate(stale_items):
        nested_count(item, "stale_bindings", "stale_binding_count", "stale_bindings_truncated", errors, f"stale[{index}]")
        keys = [locator_key(value) for value in item["stale_bindings"]]
        if not strictly_sorted_unique(keys):
            errors.append(f"stale[{index}] bindings must be sorted and unique")

    ambiguity_keys: list[tuple[Any, ...]] = []
    ambiguous_visible: set[str] = set()
    ambiguity_details_truncated = False
    for index, item in enumerate(ambiguous_items):
        nested_count(item, "candidate_concept_ids", "candidate_count", "candidates_truncated", errors, f"ambiguous[{index}]")
        candidates = item["candidate_concept_ids"]
        if not strictly_sorted_unique(candidates):
            errors.append(f"ambiguous[{index}] candidates must be sorted and unique")
        ambiguous_visible.update(candidates)
        ambiguity_keys.append((item["matched_alias"], tuple(candidates)))
        ambiguity_details_truncated |= item["candidates_truncated"]
        try:
            normalized_alias = normalize_alias(item["matched_alias"])
        except (TypeError, ValueError) as exc:
            errors.append(f"ambiguous[{index}] alias is invalid: {exc}")
        else:
            if item["matched_alias"] != normalized_alias:
                errors.append(f"ambiguous[{index}] alias is not stored normalized")
    if ambiguity_keys != sorted(ambiguity_keys) or len(ambiguity_keys) != len(set(ambiguity_keys)):
        errors.append("ambiguity records must be sorted and unique")

    recognized_set = set(recognized_ids)
    covered_set = set(covered_ids)
    uncovered_set = set(uncovered_ids)
    stale_set = set(stale_ids)
    categorized_visible = covered_set | uncovered_set | stale_set | ambiguous_visible
    if not categorized_visible <= recognized_set:
        errors.append("every visible categorized concept must be recognized")
    categories = (covered_set, uncovered_set, stale_set, ambiguous_visible)
    if any(categories[i] & categories[j] for i in range(len(categories)) for j in range(i + 1, len(categories))):
        errors.append("covered, uncovered, stale, and ambiguous candidate concepts must be disjoint")

    ambiguity = document["ambiguous_concepts"]
    candidate_total = ambiguity["distinct_candidate_concept_count"]
    if type(candidate_total) is not int:
        errors.append("distinct_candidate_concept_count must be a JSON integer")
    else:
        if candidate_total < len(ambiguous_visible):
            errors.append("distinct ambiguity candidate count is smaller than visible candidates")
        if not ambiguity["truncated"] and not ambiguity_details_truncated and candidate_total != len(ambiguous_visible):
            errors.append("distinct ambiguity candidate count must equal the complete visible union")

    counts = {
        "R": document["recognized_concepts"]["total_count"],
        "C": document["covered_concepts"]["total_count"],
        "U": document["uncovered_concepts"]["total_count"],
        "S": document["stale_concepts"]["total_count"],
        "A": candidate_total,
    }
    coverage = document["coverage"]
    for key in ("numerator", "denominator"):
        if type(coverage[key]) is not int:
            errors.append(f"coverage.{key} must be a JSON integer, not a float")
    if all(type(value) is int for value in counts.values()):
        if counts["R"] != counts["C"] + counts["U"] + counts["S"] + counts["A"]:
            errors.append("recognized total must equal covered + uncovered + stale + distinct ambiguous candidates")
        if type(coverage["numerator"]) is int and coverage["numerator"] != counts["C"]:
            errors.append("coverage numerator must equal covered total")
        if type(coverage["denominator"]) is int and coverage["denominator"] != counts["R"]:
            errors.append("coverage denominator must equal recognized total")

        if document["ambiguous_concepts"]["total_count"] > 0:
            expected_status = "ambiguous"
        elif counts["R"] == 0:
            expected_status = "unanswerable"
        elif counts["C"] == counts["R"]:
            expected_status = "answerable"
        elif counts["C"] > 0:
            expected_status = "partial"
        else:
            expected_status = "unanswerable"
        if document["status"] != expected_status:
            errors.append(f"status must be {expected_status} for the declared counts")

    all_detail_truncated = any(document[name]["truncated"] for name in COLLECTIONS)
    all_detail_truncated |= any(item["matched_aliases_truncated"] for item in recognized_items)
    all_detail_truncated |= any(item["verified_bindings_truncated"] for item in covered_items)
    all_detail_truncated |= any(item["candidates_truncated"] for item in ambiguous_items)
    all_detail_truncated |= any(item["stale_bindings_truncated"] for item in stale_items)
    state = document["retrieval_state"]
    if state["coverage_output_truncated"] is not all_detail_truncated:
        errors.append("coverage_output_truncated must reflect every coverage detail list")
    budget = state["byte_budget_omission"]
    for key in ("omitted_item_count", "byte_budget", "used_bytes"):
        if type(budget[key]) is not int:
            errors.append(f"byte_budget_omission.{key} must be a JSON integer")
    if type(budget["used_bytes"]) is int and type(budget["byte_budget"]) is int and budget["used_bytes"] > budget["byte_budget"]:
        errors.append("used_bytes must not exceed byte_budget")
    if budget["omitted"] is not (budget["omitted_item_count"] > 0):
        errors.append("byte-budget omitted flag must match omitted_item_count")

    supplied_digest = document["receipt_digest"]
    body = {key: value for key, value in document.items() if key != "receipt_digest"}
    expected_digest = hashlib.sha256(canonical_json(body)).hexdigest()
    if supplied_digest != expected_digest:
        errors.append("receipt_digest does not match canonical receipt content")
    return errors


def validate_document(validator: Draft202012Validator, document: Any) -> list[str]:
    schema_errors = sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path))
    if schema_errors:
        return [f"schema at {'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}" for error in schema_errors]
    if not isinstance(document, dict):
        return ["receipt must be an object"]
    return cross_field_errors(document)


def main() -> int:
    validator = schema_validator()
    valid_paths = sorted(VALID_DIR.glob("*.json"))
    invalid_paths = sorted(INVALID_DIR.glob("*.json"))
    required_valid = {
        "answerable.json", "partial.json", "ambiguous.json", "unanswerable.json",
        "answerable-truncated.json", "byte-budget-omission.json", "partial-stale.json",
    }
    required_invalid = {
        "float-ratio.json", "raw-query-field.json", "authorizes-actions-true.json",
        "ambiguous-concept-counted-as-covered.json", "unknown-status.json", "oversize-list.json",
    }
    failures: list[str] = schema_contract_errors()
    if {path.name for path in valid_paths} != required_valid:
        failures.append("valid example set does not match the required frozen names")
    if not required_invalid <= {path.name for path in invalid_paths}:
        failures.append("invalid example set is missing a required single-reason case")

    valid_statuses: set[str] = set()
    for path in valid_paths:
        document = load_json(path)
        errors = validate_document(validator, document)
        if not errors:
            errors = current_source_errors(document)
        if errors:
            failures.append(f"{path.relative_to(HERE)} unexpectedly failed: {'; '.join(errors)}")
        else:
            valid_statuses.add(document["status"])
    if valid_statuses != {"answerable", "partial", "ambiguous", "unanswerable"}:
        failures.append("valid examples do not cover every status")

    for path in invalid_paths:
        document = load_json(path)
        errors = validate_document(validator, document)
        if not errors:
            failures.append(f"{path.relative_to(HERE)} unexpectedly passed")

    truncated = load_json(VALID_DIR / "answerable-truncated.json")
    if truncated["status"] != "answerable" or not truncated["retrieval_state"]["coverage_output_truncated"]:
        failures.append("truncated example must remain answerable with explicit output truncation")
    omitted = load_json(VALID_DIR / "byte-budget-omission.json")
    if omitted["status"] == "unanswerable" or not omitted["retrieval_state"]["byte_budget_omission"]["omitted"]:
        failures.append("byte-budget omission example must not become unanswerable")
    stale = load_json(VALID_DIR / "partial-stale.json")
    if stale["status"] != "partial" or stale["stale_concepts"]["total_count"] == 0:
        failures.append("stale example must remain partial with explicit stale concepts")
    ambiguous = load_json(VALID_DIR / "ambiguous.json")
    if ambiguous["status"] != "ambiguous" or ambiguous["covered_concepts"]["total_count"] == 0:
        failures.append("ambiguous example must allow a disjoint covered concept")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print(
        f"coverage contract valid: schema + {len(valid_paths)} valid examples + "
        f"{len(invalid_paths)} rejected examples"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
