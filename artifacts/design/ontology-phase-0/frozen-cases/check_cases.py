#!/usr/bin/env python3
"""Offline structural and privacy checks for the Phase 0 frozen case matrix."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from palimnex.durable import canonical_json  # noqa: E402
from palimnex.security import scan_bytes, scan_text  # noqa: E402


HERE = Path(__file__).resolve().parent
CASES_PATH = HERE / "cases.v0.json"
REGISTRY_SCHEMA_PATH = ROOT / "artifacts/design/ontology-phase-0/registry/concept-registry.v1.schema.json"
LOCATOR_SCHEMA_PATH = ROOT / "palimnex/schemas/source-locator.v1.schema.json"
OWNED_DIRECTORIES = (
    ROOT / "artifacts/design/ontology-phase-0/threat-model",
    ROOT / "artifacts/design/ontology-phase-0/frozen-cases",
)
RECEIPT_PATH = (
    ROOT
    / "artifacts/ontology/phase-0/receipts/ontology-phase-0-threat-cases.implementation-receipt.json"
)
STATUSES = {"answerable", "partial", "ambiguous", "unanswerable"}
OUTCOMES = {"error", "receipt"}
CATEGORIES = {
    "positive",
    "partial",
    "ambiguous",
    "negative/unrelated",
    "stale-source",
    "secret",
    "truncation",
    "byte-budget",
    "supersession",
    "withdrawn",
    "candidate-non-influence",
    "path-traversal/symlink",
    "cross-project",
    "normalization",
}
REQUIRED_CASE_FIELDS = {
    "case_id",
    "category",
    "description",
    "registry_fixture",
    "query",
    "expected_status",
    "expected_recognized_concept_ids",
    "expected_covered_concept_ids",
    "expected_uncovered_concept_ids",
    "expected_ambiguous_concept_ids",
    "expected_stale_concept_ids",
    "expected_outcome",
    "gates_phase",
}
EXPECTED_LIST_FIELDS = (
    "expected_recognized_concept_ids",
    "expected_covered_concept_ids",
    "expected_uncovered_concept_ids",
    "expected_ambiguous_concept_ids",
    "expected_stale_concept_ids",
)


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def _owned_files(errors: list[str]) -> list[Path]:
    files: list[Path] = []
    for directory in OWNED_DIRECTORIES:
        if not directory.is_dir() or directory.is_symlink():
            errors.append(f"owned directory is missing or symlinked: {directory.relative_to(ROOT)}")
            continue
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                errors.append(f"owned path must not be a symlink: {path.relative_to(ROOT)}")
            elif path.is_file():
                files.append(path)
    if RECEIPT_PATH.exists():
        if RECEIPT_PATH.is_symlink() or not RECEIPT_PATH.is_file():
            errors.append(f"receipt must be a regular non-symlink file: {RECEIPT_PATH.relative_to(ROOT)}")
        else:
            files.append(RECEIPT_PATH)
    return sorted(set(files))


def _check_privacy(files: list[Path], errors: list[str]) -> None:
    for path in files:
        try:
            findings = scan_bytes(path.read_bytes())
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"privacy scan failed for {path.relative_to(ROOT)}: {type(exc).__name__}")
            continue
        for finding in findings:
            errors.append(
                f"privacy finding in {path.relative_to(ROOT)}:{finding.line}: {finding.rule}"
            )


def _check_expected_lists(case: dict[str, Any], concept_ids: set[str], errors: list[str]) -> None:
    case_id = case.get("case_id", "<unknown>")
    values: dict[str, set[str]] = {}
    for field in EXPECTED_LIST_FIELDS:
        items = case.get(field)
        valid = (
            isinstance(items, list)
            and all(isinstance(item, str) and item for item in items)
            and len(items) == len(set(items))
            and items == sorted(items)
        )
        _require(valid, f"{case_id}: {field} must be a sorted unique string list", errors)
        values[field] = set(items) if isinstance(items, list) else set()
        _require(
            values[field] <= concept_ids,
            f"{case_id}: {field} references a concept absent from the fixture",
            errors,
        )

    recognized = values["expected_recognized_concept_ids"]
    covered = values["expected_covered_concept_ids"]
    uncovered = values["expected_uncovered_concept_ids"]
    ambiguous = values["expected_ambiguous_concept_ids"]
    stale = values["expected_stale_concept_ids"]
    categorized = covered | uncovered | ambiguous | stale
    _require(categorized == recognized, f"{case_id}: recognized must equal covered + uncovered + stale + ambiguous", errors)
    outcome_sets = (covered, uncovered, ambiguous, stale)
    _require(
        sum(len(items) for items in outcome_sets) == len(categorized),
        f"{case_id}: covered, uncovered, stale, and ambiguous must be disjoint",
        errors,
    )

    status = case.get("expected_status")
    if ambiguous:
        _require(status == "ambiguous", f"{case_id}: ambiguity must win status precedence", errors)
    elif status == "answerable":
        _require(bool(covered) and not uncovered and not ambiguous, f"{case_id}: inconsistent answerable outcome", errors)
        _require(not stale and covered == recognized, f"{case_id}: answerable requires all recognized concepts covered", errors)
    elif status == "partial":
        _require(bool(covered) and covered != recognized, f"{case_id}: inconsistent partial outcome", errors)
    elif status == "unanswerable":
        _require(not covered, f"{case_id}: inconsistent unanswerable outcome", errors)


def _normalize_alias(value: str) -> str:
    folded = unicodedata.normalize("NFKC", value).casefold()
    mapped: list[str] = []
    for character in folded:
        category = unicodedata.category(character)
        if category.startswith("C"):
            raise ValueError("forbidden Unicode category")
        mapped.append(" " if category.startswith(("P", "Z")) or character.isspace() else character)
    return " ".join("".join(mapped).split())


def _registry_digest(fixture: dict[str, Any]) -> str:
    body = dict(fixture)
    body.pop("registry_digest", None)
    return hashlib.sha256(canonical_json(body)).hexdigest()


def _check_fixture(
    case: dict[str, Any],
    placeholder_digest: str,
    validator: Draft202012Validator,
    errors: list[str],
) -> set[str]:
    case_id = case.get("case_id", "<unknown>")
    concept_ids: list[str] = []
    placeholder_count = 0
    fixture_names = ["registry_fixture"]
    if "candidate_registry_fixture" in case:
        fixture_names.append("candidate_registry_fixture")
    for fixture_name in fixture_names:
        fixture = case.get(fixture_name)
        if not isinstance(fixture, dict):
            errors.append(f"{case_id}: {fixture_name} must be an object")
            continue
        schema_errors = sorted(validator.iter_errors(fixture), key=lambda item: list(item.absolute_path))
        for schema_error in schema_errors:
            location = "/".join(str(part) for part in schema_error.absolute_path) or "<root>"
            errors.append(f"{case_id}: {fixture_name}/{location}: {schema_error.message}")
        _require(
            fixture.get("registry_digest") == _registry_digest(fixture),
            f"{case_id}: {fixture_name} registry_digest mismatch",
            errors,
        )
        concepts = fixture.get("concepts", [])
        if not isinstance(concepts, list):
            continue
        for index, concept in enumerate(concepts):
            label = f"{case_id}: {fixture_name}.concepts[{index}]"
            if not isinstance(concept, dict):
                continue
            concept_id = concept.get("concept_id")
            if isinstance(concept_id, str):
                concept_ids.append(concept_id)
            aliases = concept.get("aliases", [])
            if isinstance(aliases, list):
                for alias in aliases:
                    try:
                        normalized = _normalize_alias(alias)
                    except (TypeError, ValueError):
                        normalized = None
                    _require(normalized == alias, f"{label} alias is not stored normalized", errors)
            bindings = concept.get("source_bindings", [])
            if not isinstance(bindings, list):
                continue
            for binding in bindings:
                if not isinstance(binding, dict):
                    continue
                if binding.get("digest") == placeholder_digest:
                    placeholder_count += 1

    _require(len(concept_ids) == len(set(concept_ids)), f"{case_id}: duplicate concept_id across fixtures", errors)
    if placeholder_count:
        _require(
            case.get("binding_digests_are_placeholders") is True,
            f"{case_id}: placeholder bindings require one case-level flag",
            errors,
        )
    else:
        _require(
            "binding_digests_are_placeholders" not in case,
            f"{case_id}: placeholder flag is present without a placeholder binding",
            errors,
        )
    return set(concept_ids)


def _check_digest_only_locator_probe(
    cases: list[Any], placeholder_digest: str, validator: Draft202012Validator, errors: list[str]
) -> bool:
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("registry_fixture"), dict):
            continue
        probe = copy.deepcopy(case["registry_fixture"])
        for concept in probe.get("concepts", []):
            bindings = concept.get("source_bindings", []) if isinstance(concept, dict) else []
            if bindings:
                bindings[0] = {"digest": placeholder_digest}
                probe["registry_digest"] = _registry_digest(probe)
                _require(
                    bool(list(validator.iter_errors(probe))),
                    "digest-only source locator adversarial probe unexpectedly passed",
                    errors,
                )
                return True
    errors.append("no source binding was available for the digest-only locator probe")
    return False


def _check_canary(case: dict[str, Any], errors: list[str]) -> None:
    case_id = case.get("case_id", "<unknown>")
    recipe = case.get("canary_recipe")
    if case.get("category") != "secret":
        _require(recipe is None, f"{case_id}: only secret cases may define canary_recipe", errors)
        return
    if not isinstance(recipe, dict) or recipe.get("operation") != "join":
        errors.append(f"{case_id}: secret case requires a join canary_recipe")
        return
    fragments = recipe.get("fragments")
    if not (
        isinstance(fragments, list)
        and len(fragments) >= 2
        and all(isinstance(fragment, str) and fragment for fragment in fragments)
    ):
        errors.append(f"{case_id}: canary fragments must be at least two non-empty strings")
        return
    if any(scan_text(fragment) for fragment in fragments):
        errors.append(f"{case_id}: a stored canary fragment is independently credential-shaped")
        return
    canary = "".join(fragments)
    findings = scan_text(canary)
    _require(bool(findings), f"{case_id}: reconstructed canary was not detected", errors)


def main() -> int:
    errors: list[str] = []
    owned_files = _owned_files(errors)
    _check_privacy(owned_files, errors)

    try:
        raw = CASES_PATH.read_bytes()
        document = json.loads(raw)
        registry_schema = json.loads(REGISTRY_SCHEMA_PATH.read_bytes())
        locator_schema = json.loads(LOCATOR_SCHEMA_PATH.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "errors": [f"contract input unreadable: {type(exc).__name__}"]}, sort_keys=True))
        return 1

    try:
        Draft202012Validator.check_schema(registry_schema)
        Draft202012Validator.check_schema(locator_schema)
        local_registry = Registry().with_resource(
            locator_schema["$id"], Resource.from_contents(locator_schema)
        )
        registry_validator = Draft202012Validator(registry_schema, registry=local_registry)
    except (KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "errors": [f"registry schema setup failed: {type(exc).__name__}"]}, sort_keys=True))
        return 1

    _require(isinstance(document, dict), "case matrix must be an object", errors)
    if not isinstance(document, dict):
        print(json.dumps({"status": "failed", "errors": errors}, sort_keys=True))
        return 1
    _require(document.get("schema") == "palimnex:ontology-frozen-cases:v0", "unexpected matrix schema", errors)
    placeholder_digest = document.get("placeholder_locator_digest")
    _require(
        isinstance(placeholder_digest, str)
        and len(placeholder_digest) == 64
        and set(placeholder_digest) <= set("0123456789abcdef"),
        "placeholder_locator_digest must be lowercase SHA-256-shaped text",
        errors,
    )
    cases = document.get("cases")
    _require(isinstance(cases, list) and bool(cases), "cases must be a non-empty array", errors)
    if not isinstance(cases, list):
        cases = []

    identifiers: list[str] = []
    categories: Counter[str] = Counter()
    normalization_dimensions: set[str] = set()
    ambiguous_with_covered = False
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            errors.append(f"case[{index}] must be an object")
            continue
        case_id = case.get("case_id", f"case[{index}]")
        _require(REQUIRED_CASE_FIELDS <= set(case), f"{case_id}: missing required fields", errors)
        _require(isinstance(case_id, str) and case_id.startswith("ONT-"), f"case[{index}] has invalid case_id", errors)
        if isinstance(case_id, str):
            identifiers.append(case_id)
        category = case.get("category")
        _require(category in CATEGORIES, f"{case_id}: unsupported category", errors)
        if isinstance(category, str):
            categories[category] += 1
        _require(
            isinstance(case.get("description"), str) and bool(case["description"].strip()),
            f"{case_id}: description must be non-empty",
            errors,
        )
        _require(
            isinstance(case.get("query"), str) and bool(case["query"].strip()),
            f"{case_id}: query must be non-empty",
            errors,
        )
        _require(case.get("expected_status") in STATUSES, f"{case_id}: invalid expected_status", errors)
        _require(case.get("gates_phase") in {1, 2, 3}, f"{case_id}: gates_phase must be 1, 2, or 3", errors)
        disputed = case.get("expected_status_disputed", False)
        _require(type(disputed) is bool, f"{case_id}: expected_status_disputed must be boolean", errors)
        if disputed:
            _require(
                isinstance(case.get("dispute_reason"), str) and bool(case["dispute_reason"].strip()),
                f"{case_id}: disputed status requires a reason",
                errors,
            )
        outcome = case.get("expected_outcome")
        _require(outcome in OUTCOMES, f"{case_id}: expected_outcome must be error or receipt", errors)
        if category in {"secret", "path-traversal/symlink", "cross-project"}:
            _require(outcome == "error", f"{case_id}: R7 requires a typed operation error", errors)
            _require(disputed, f"{case_id}: R7 error default must remain disputed", errors)
            _require("R7" in str(case.get("dispute_reason", "")), f"{case_id}: R7 dispute reason is required", errors)
        elif category == "stale-source":
            _require(outcome == "receipt", f"{case_id}: R7 requires stale source to emit a receipt", errors)
            _require(disputed, f"{case_id}: R7 stale default must remain disputed", errors)
            _require("R7" in str(case.get("dispute_reason", "")), f"{case_id}: R7 dispute reason is required", errors)
        else:
            _require(outcome == "receipt", f"{case_id}: ordinary coverage cases require a receipt", errors)
        concept_ids = _check_fixture(case, placeholder_digest, registry_validator, errors)
        _check_expected_lists(case, concept_ids, errors)
        _check_canary(case, errors)
        if case.get("expected_status") == "ambiguous" and case.get("expected_covered_concept_ids"):
            ambiguous_with_covered = True
        stale_ids = case.get("expected_stale_concept_ids")
        if category == "stale-source":
            _require(bool(stale_ids), f"{case_id}: stale-source case requires stale concepts", errors)
        else:
            _require(stale_ids == [], f"{case_id}: only stale-source cases may expect stale concepts", errors)
        if category == "normalization" and isinstance(case.get("normalization_dimension"), str):
            normalization_dimensions.add(case["normalization_dimension"])

    _require(len(identifiers) == len(set(identifiers)), "case_id values must be unique", errors)
    for category in sorted(CATEGORIES):
        _require(categories[category] >= 2, f"category {category} requires at least two cases", errors)
    _require(
        {"case", "unicode", "whitespace"} <= normalization_dimensions,
        "normalization cases must cover case, unicode, and whitespace",
        errors,
    )
    _require(
        ambiguous_with_covered,
        "at least one ambiguous case must retain a disjoint covered concept",
        errors,
    )
    digest_only_probe_rejected = _check_digest_only_locator_probe(
        cases, placeholder_digest, registry_validator, errors
    )

    if errors:
        print(json.dumps({"status": "failed", "error_count": len(errors), "errors": errors}, sort_keys=True))
        return 1
    report = {
        "status": "passed",
        "schema": document["schema"],
        "case_count": len(cases),
        "category_counts": dict(sorted(categories.items())),
        "matrix_sha256": hashlib.sha256(raw).hexdigest(),
        "owned_files_scanned": len(owned_files),
        "canary_cases_verified": categories["secret"],
        "registry_fixtures_validated": sum(
            1 + ("candidate_registry_fixture" in case)
            for case in cases
            if isinstance(case, dict)
        ),
        "digest_only_locator_probe_rejected": digest_only_probe_rejected,
        "network_used": False,
        "live_state_touched": False,
    }
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
