#!/usr/bin/env python3
"""Offline structural and privacy checks for the Phase 0 frozen case matrix."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from palimnex.security import scan_bytes, scan_text  # noqa: E402


HERE = Path(__file__).resolve().parent
CASES_PATH = HERE / "cases.v0.json"
OWNED_DIRECTORIES = (
    ROOT / "artifacts/design/ontology-phase-0/threat-model",
    ROOT / "artifacts/design/ontology-phase-0/frozen-cases",
)
RECEIPT_PATH = (
    ROOT
    / "artifacts/ontology/phase-0/receipts/ontology-phase-0-threat-cases.implementation-receipt.json"
)
STATUSES = {"answerable", "partial", "ambiguous", "unanswerable"}
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
    "gates_phase",
}
EXPECTED_LIST_FIELDS = (
    "expected_recognized_concept_ids",
    "expected_covered_concept_ids",
    "expected_uncovered_concept_ids",
    "expected_ambiguous_concept_ids",
)
LIFECYCLE_STATUSES = {"candidate", "approved", "superseded", "withdrawn"}


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
    _require(covered | uncovered | ambiguous <= recognized, f"{case_id}: outcomes must be recognized", errors)
    _require(not (covered & uncovered), f"{case_id}: covered and uncovered overlap", errors)
    _require(not (covered & ambiguous), f"{case_id}: covered and ambiguous overlap", errors)
    _require(not (uncovered & ambiguous), f"{case_id}: uncovered and ambiguous overlap", errors)

    status = case.get("expected_status")
    if status == "answerable":
        _require(bool(covered) and not uncovered and not ambiguous, f"{case_id}: inconsistent answerable outcome", errors)
    elif status == "partial":
        _require(bool(covered) and bool(uncovered) and not ambiguous, f"{case_id}: inconsistent partial outcome", errors)
    elif status == "ambiguous":
        _require(bool(ambiguous) and not covered, f"{case_id}: inconsistent ambiguous outcome", errors)
    elif status == "unanswerable":
        _require(not covered and not ambiguous, f"{case_id}: inconsistent unanswerable outcome", errors)


def _check_fixture(
    case: dict[str, Any], placeholder_digest: str, errors: list[str]
) -> set[str]:
    case_id = case.get("case_id", "<unknown>")
    fixture = case.get("registry_fixture")
    if not isinstance(fixture, dict):
        errors.append(f"{case_id}: registry_fixture must be an object")
        return set()
    concepts = fixture.get("concepts")
    if not isinstance(concepts, list):
        errors.append(f"{case_id}: registry_fixture.concepts must be an array")
        return set()

    concept_ids: list[str] = []
    for index, concept in enumerate(concepts):
        label = f"{case_id}: concept[{index}]"
        if not isinstance(concept, dict):
            errors.append(f"{label} must be an object")
            continue
        concept_id = concept.get("concept_id")
        _require(isinstance(concept_id, str) and concept_id.startswith("concept."), f"{label} has invalid concept_id", errors)
        if isinstance(concept_id, str):
            concept_ids.append(concept_id)
        aliases = concept.get("aliases")
        _require(
            isinstance(aliases, list)
            and bool(aliases)
            and all(isinstance(alias, str) and alias.strip() for alias in aliases)
            and len(aliases) == len(set(aliases)),
            f"{label} aliases must be a non-empty unique string list",
            errors,
        )
        _require(
            concept.get("lifecycle_status") in LIFECYCLE_STATUSES,
            f"{label} has invalid lifecycle_status",
            errors,
        )
        bindings = concept.get("source_bindings")
        if not isinstance(bindings, list):
            errors.append(f"{label} source_bindings must be an array")
            continue
        for binding_index, binding in enumerate(bindings):
            binding_label = f"{label}.source_bindings[{binding_index}]"
            if not isinstance(binding, dict):
                errors.append(f"{binding_label} must be an object")
                continue
            locator = binding.get("locator")
            _require(isinstance(locator, dict), f"{binding_label} locator must be an object", errors)
            if isinstance(locator, dict):
                _require(
                    locator.get("digest") == placeholder_digest,
                    f"{binding_label} must use the declared placeholder digest",
                    errors,
                )
            _require(
                binding.get("digest_is_placeholder") is True,
                f"{binding_label} must mark its digest as a placeholder",
                errors,
            )
    _require(len(concept_ids) == len(set(concept_ids)), f"{case_id}: duplicate concept_id", errors)
    return set(concept_ids)


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
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "errors": [f"cases file unreadable: {type(exc).__name__}"]}, sort_keys=True))
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
        concept_ids = _check_fixture(case, placeholder_digest, errors)
        _check_expected_lists(case, concept_ids, errors)
        _check_canary(case, errors)
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
        "network_used": False,
        "live_state_touched": False,
    }
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
