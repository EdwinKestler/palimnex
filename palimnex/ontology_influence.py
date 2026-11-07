"""Opt-in, evidence-bound ontology retrieval influence activation.

Registry presence is data, not authority.  Influence becomes active only when
the repository setting, approved registry, current source bindings, and
promotion evidence all agree.  This module performs no cache, ledger, network,
configuration, or persistence writes.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, NoReturn, cast

from .concepts import (
    ConceptRegistry,
    ConceptRegistryError,
    load_registry,
    normalize_alias,
    verify_source_bindings,
)
from .core import project_config
from .durable import canonical_json
from .locators import SourceResolver
from .ontology_shadow import OntologyChannel
from .security import read_bounded_file, scan_bytes, scan_text


INFLUENCE_MODES = ("off", "shadow", "enabled")
PROMOTION_EVIDENCE_SCHEMA = "palimnex:ontology-promotion-evidence:v1"
CONTEXT_V2_SCHEMA = "project-memory:context:v2"
EXPLAIN_SEARCH_V2_SCHEMA = "palimnex:explain-search:v2"

DEFAULT_REGISTRY_PATH = "ontology/concept-registry.v1.json"
MAX_INFLUENCE_PATH_CHARS = 512
MAX_PROMOTION_EVIDENCE_BYTES = 1_000_000
MAX_IMPLEMENTATION_SOURCE_BYTES = 1_000_000
MAX_EVALUATION_COUNT = 1_000_000
MAX_EVALUATION_LIMIT = 100
MAX_REGRESSED_CASE_IDS = 64
MAX_CASE_ID_CHARS = 128

_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_SETTING_BASE_FIELDS = frozenset({"mode"})
_SETTING_ENABLED_REQUIRED_FIELDS = frozenset(
    {"mode", "registry_digest", "promotion_evidence", "promotion_evidence_digest"}
)
_SETTING_ENABLED_OPTIONAL_FIELDS = frozenset({"registry"})
_EVIDENCE_FIELDS = frozenset(
    {
        "schema",
        "status",
        "registry",
        "implementation_digest",
        "fixture_digests",
        "limit",
        "backends",
        "activation_authorized",
        "authority",
        "authorizes_actions",
        "evidence_digest",
    }
)
_SUITE_NAMES = frozenset({"v27", "challenges_v26", "cohort"})
_METRIC_FIELDS = frozenset(
    {
        "case_count",
        "cases_passed",
        "critical_case_count",
        "critical_pass_count",
        "forbidden_path_hits",
        "recall_at_limit",
        "mrr",
        "negative_abstention",
        "negative_case_count",
    }
)
_COUNT_METRIC_FIELDS = (
    "case_count",
    "cases_passed",
    "critical_case_count",
    "critical_pass_count",
    "forbidden_path_hits",
    "negative_case_count",
)
_RATE_METRIC_FIELDS = ("recall_at_limit", "mrr", "negative_abstention")
_GATE_FIELDS = frozenset(
    {
        "off_identical",
        "no_critical_regression",
        "no_case_regression",
        "no_new_forbidden",
        "abstention_not_regressed",
        "registry_unambiguous",
        "registry_current",
        "channels_visible",
        "bounded",
        "deterministic",
    }
)

_PACKAGE_ROOT = Path(__file__).resolve().parent
_IMPLEMENTATION_SOURCE_PATHS: tuple[tuple[str, Path], ...] = (
    ("palimnex.concepts", _PACKAGE_ROOT / "concepts.py"),
    ("palimnex.ontology_influence", Path(__file__).resolve()),
    ("palimnex.ontology_shadow", _PACKAGE_ROOT / "ontology_shadow.py"),
    ("palimnex.retrieval", _PACKAGE_ROOT / "retrieval.py"),
)


class OntologyInfluenceError(ValueError):
    """A non-echoing influence refusal with a stable machine reason."""

    def __init__(self, reason: str, field: str = "ontology_influence") -> None:
        self.reason = reason
        self.field = field
        super().__init__(f"ontology influence refused: {reason} at {field}")


@dataclass(frozen=True)
class InfluenceSetting:
    mode: str
    registry_path: str | None
    registry_digest: str | None
    promotion_evidence: str | None
    promotion_evidence_digest: str | None


@dataclass(frozen=True)
class ActiveInfluence:
    setting: InfluenceSetting
    registry: ConceptRegistry
    evidence_digest: str
    implementation_digest: str


def _fail(reason: str, field: str) -> NoReturn:
    raise OntologyInfluenceError(reason, field)


def _require_exact_fields(
    value: Mapping[str, Any], expected: frozenset[str], field: str
) -> None:
    if set(value) != expected:
        _fail("evidence_invalid", field)


def _digest(value: object, field: str, *, setting: bool = False) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        _fail("setting_invalid" if setting else "evidence_invalid", field)
    return value


def _repository_path(value: object, field: str, *, setting: bool = False) -> str:
    reason = "setting_invalid" if setting else "evidence_invalid"
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= MAX_INFLUENCE_PATH_CHARS
        or "\\" in value
        or Path(value).is_absolute()
        or PureWindowsPath(value).is_absolute()
    ):
        _fail(reason, field)
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        _fail(reason, field)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        _fail(reason, field)
    if scan_text(value):
        _fail(reason, field)
    return value


def _setting_from_value(value: object) -> InfluenceSetting:
    if not isinstance(value, Mapping):
        _fail("setting_invalid", "ontology_influence")
    if set(value) == set() or "mode" not in value:
        _fail("setting_invalid", "ontology_influence")
    mode = value["mode"]
    if not isinstance(mode, str) or mode not in INFLUENCE_MODES:
        _fail("setting_invalid", "ontology_influence.mode")
    if mode in {"off", "shadow"}:
        if set(value) != _SETTING_BASE_FIELDS:
            _fail("setting_invalid", "ontology_influence")
        return InfluenceSetting(mode, None, None, None, None)
    keys = set(value)
    if (
        not _SETTING_ENABLED_REQUIRED_FIELDS.issubset(keys)
        or keys - _SETTING_ENABLED_REQUIRED_FIELDS - _SETTING_ENABLED_OPTIONAL_FIELDS
    ):
        _fail("setting_invalid", "ontology_influence")
    registry_path = _repository_path(
        value.get("registry", DEFAULT_REGISTRY_PATH),
        "ontology_influence.registry",
        setting=True,
    )
    registry_digest = _digest(
        value["registry_digest"], "ontology_influence.registry_digest", setting=True
    )
    evidence_path = _repository_path(
        value["promotion_evidence"],
        "ontology_influence.promotion_evidence",
        setting=True,
    )
    evidence_digest = _digest(
        value["promotion_evidence_digest"],
        "ontology_influence.promotion_evidence_digest",
        setting=True,
    )
    return InfluenceSetting(
        mode,
        registry_path,
        registry_digest,
        evidence_path,
        evidence_digest,
    )


def read_influence_setting(root: Path) -> InfluenceSetting:
    """Read and strictly validate the repository influence setting."""
    try:
        config = project_config(root)
    except (OSError, TypeError, ValueError) as exc:
        raise OntologyInfluenceError("setting_invalid", "ontology_influence") from exc
    if "ontology_influence" not in config:
        return InfluenceSetting("off", None, None, None, None)
    return _setting_from_value(config["ontology_influence"])


def _registry_has_ambiguity(registry: ConceptRegistry) -> bool:
    keys: dict[str, str] = {}
    try:
        for concept in registry.active_concepts:
            for key in (normalize_alias(concept.canonical_name), *concept.aliases):
                existing = keys.get(key)
                if existing is not None and existing != concept.concept_id:
                    return True
                keys[key] = concept.concept_id
    except ConceptRegistryError as exc:
        raise OntologyInfluenceError(exc.reason, exc.field) from exc
    return False


def _implementation_source_bytes(path: Path) -> bytes:
    try:
        return read_bounded_file(
            path.parent,
            path.name,
            max_bytes=MAX_IMPLEMENTATION_SOURCE_BYTES,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise OntologyInfluenceError(
            "implementation_source_unavailable", "implementation_digest"
        ) from exc


def influence_implementation_digest() -> str:
    """Bind the exact source bytes of every ontology-influence module."""
    rows = [
        [module, hashlib.sha256(_implementation_source_bytes(path)).hexdigest()]
        for module, path in sorted(_IMPLEMENTATION_SOURCE_PATHS)
    ]
    return hashlib.sha256(canonical_json(rows)).hexdigest()


def _canonical_evidence_bytes(document: Mapping[str, Any]) -> bytes:
    try:
        return canonical_json(document)
    except (RecursionError, TypeError, ValueError) as exc:
        raise OntologyInfluenceError("evidence_invalid", "evidence") from exc


def _evidence_object(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("evidence_invalid", field)
    return cast(Mapping[str, Any], value)


def _bounded_count(value: object, field: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_EVALUATION_COUNT:
        _fail("evidence_invalid", field)
    return cast(int, value)


def _bounded_rate(value: object, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0.0 <= value <= 1.0
    ):
        _fail("evidence_invalid", field)
    return float(value)


def _validate_metrics(value: object, field: str) -> None:
    metrics = _evidence_object(value, field)
    _require_exact_fields(metrics, _METRIC_FIELDS, field)
    counts = {
        name: _bounded_count(metrics[name], field + "." + name)
        for name in _COUNT_METRIC_FIELDS
    }
    for name in _RATE_METRIC_FIELDS:
        _bounded_rate(metrics[name], field + "." + name)
    if (
        counts["cases_passed"] > counts["case_count"]
        or counts["critical_case_count"] > counts["case_count"]
        or counts["critical_pass_count"] > counts["critical_case_count"]
        or counts["negative_case_count"] > counts["case_count"]
    ):
        _fail("evidence_invalid", field)


def _validate_case_ids(value: object, field: str, case_count: int) -> None:
    if not isinstance(value, list) or len(value) > MAX_REGRESSED_CASE_IDS:
        _fail("evidence_invalid", field)
    identifiers: list[str] = []
    for index, item in enumerate(value):
        if (
            not isinstance(item, str)
            or not 1 <= len(item) <= MAX_CASE_ID_CHARS
            or any(ord(character) < 32 or ord(character) == 127 for character in item)
        ):
            _fail("evidence_invalid", f"{field}[{index}]")
        identifiers.append(item)
    if identifiers != sorted(identifiers) or len(identifiers) != len(set(identifiers)):
        _fail("evidence_invalid", field)
    if len(identifiers) > case_count:
        _fail("evidence_invalid", field)


def _validate_suite(value: object, field: str) -> None:
    suite = _evidence_object(value, field)
    expected = frozenset(
        {"baseline", "influenced", "changed_ranking_count", "regressed_case_ids"}
    )
    _require_exact_fields(suite, expected, field)
    _validate_metrics(suite["baseline"], field + ".baseline")
    _validate_metrics(suite["influenced"], field + ".influenced")
    baseline = _evidence_object(suite["baseline"], field + ".baseline")
    influenced = _evidence_object(suite["influenced"], field + ".influenced")
    baseline_count = cast(int, baseline["case_count"])
    influenced_count = cast(int, influenced["case_count"])
    if baseline_count != influenced_count:
        _fail("evidence_invalid", field)
    changed = _bounded_count(suite["changed_ranking_count"], field + ".changed_ranking_count")
    if changed > baseline_count:
        _fail("evidence_invalid", field + ".changed_ranking_count")
    _validate_case_ids(suite["regressed_case_ids"], field + ".regressed_case_ids", baseline_count)


def _validate_backend(value: object, field: str) -> bool:
    backend = _evidence_object(value, field)
    _require_exact_fields(backend, frozenset({"suites", "gates"}), field)
    suites = _evidence_object(backend["suites"], field + ".suites")
    _require_exact_fields(suites, _SUITE_NAMES, field + ".suites")
    for name in sorted(_SUITE_NAMES):
        _validate_suite(suites[name], field + ".suites." + name)
    gates = _evidence_object(backend["gates"], field + ".gates")
    _require_exact_fields(gates, _GATE_FIELDS, field + ".gates")
    for name in sorted(_GATE_FIELDS):
        if type(gates[name]) is not bool:
            _fail("evidence_invalid", field + ".gates." + name)
    return all(cast(bool, gates[name]) for name in _GATE_FIELDS)


def _promotion_evidence_digest(document: Mapping[str, Any]) -> str:
    body = dict(document)
    body.pop("evidence_digest", None)
    return hashlib.sha256(_canonical_evidence_bytes(body)).hexdigest()


def validate_promotion_evidence(document: Mapping[str, Any]) -> None:
    """Validate the bounded promotion-evidence v1 runtime contract."""
    if not isinstance(document, Mapping):
        _fail("evidence_invalid", "evidence")
    admitted = _canonical_evidence_bytes(document)
    try:
        findings = scan_bytes(admitted)
    except UnicodeError as exc:
        raise OntologyInfluenceError("evidence_invalid", "evidence") from exc
    if findings:
        _fail("evidence_privacy_refused", "evidence")
    _require_exact_fields(document, _EVIDENCE_FIELDS, "evidence")
    if document["schema"] != PROMOTION_EVIDENCE_SCHEMA:
        _fail("evidence_invalid", "schema")
    if (
        not isinstance(document["status"], str)
        or document["status"] not in ("promotable", "held")
    ):
        _fail("evidence_invalid", "status")

    registry = _evidence_object(document["registry"], "registry")
    _require_exact_fields(registry, frozenset({"path", "digest"}), "registry")
    _repository_path(registry["path"], "registry.path")
    _digest(registry["digest"], "registry.digest")
    _digest(document["implementation_digest"], "implementation_digest")

    fixtures = _evidence_object(document["fixture_digests"], "fixture_digests")
    fixture_names = frozenset({"v27", "v26", "cohort"})
    _require_exact_fields(fixtures, fixture_names, "fixture_digests")
    for name in sorted(fixture_names):
        _digest(fixtures[name], "fixture_digests." + name)

    limit = document["limit"]
    if type(limit) is not int or not 1 <= limit <= MAX_EVALUATION_LIMIT:
        _fail("evidence_invalid", "limit")
    backends = _evidence_object(document["backends"], "backends")
    _require_exact_fields(backends, frozenset({"local", "cache"}), "backends")
    backend_gate_results = tuple(
        _validate_backend(backends[name], "backends." + name)
        for name in ("local", "cache")
    )
    all_gates = all(backend_gate_results)
    expected_status = "promotable" if all_gates else "held"
    if document["status"] != expected_status:
        _fail("evidence_invalid", "status")
    if document["activation_authorized"] is not False:
        _fail("evidence_invalid", "activation_authorized")
    if document["authority"] != "evidence_only":
        _fail("evidence_invalid", "authority")
    if document["authorizes_actions"] is not False:
        _fail("evidence_invalid", "authorizes_actions")
    evidence_digest = _digest(document["evidence_digest"], "evidence_digest")
    if evidence_digest != _promotion_evidence_digest(document):
        _fail("evidence_invalid", "evidence_digest")


def _reject_constant(_value: str) -> NoReturn:
    _fail("evidence_invalid", "evidence")


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("evidence_invalid", "evidence")
        result[key] = value
    return result


def _decode_evidence(raw: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_constant,
        )
    except OntologyInfluenceError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise OntologyInfluenceError("evidence_invalid", "evidence") from exc
    if not isinstance(value, Mapping):
        _fail("evidence_invalid", "evidence")
    return cast(Mapping[str, Any], value)


def _read_evidence(setting: InfluenceSetting, root: Path) -> Mapping[str, Any]:
    path = setting.promotion_evidence
    expected_digest = setting.promotion_evidence_digest
    if path is None or expected_digest is None:
        _fail("setting_invalid", "ontology_influence")
    try:
        raw = read_bounded_file(root, path, max_bytes=MAX_PROMOTION_EVIDENCE_BYTES)
    except (OSError, TypeError, ValueError) as exc:
        raise OntologyInfluenceError("evidence_missing", "promotion_evidence") from exc
    try:
        findings = scan_bytes(raw)
    except UnicodeError as exc:
        raise OntologyInfluenceError("evidence_invalid", "evidence") from exc
    if findings:
        _fail("evidence_privacy_refused", "evidence")
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        _fail("evidence_digest_mismatch", "promotion_evidence_digest")
    return _decode_evidence(raw)


def _backends_complete(document: Mapping[str, Any]) -> bool:
    backends = document.get("backends")
    return isinstance(backends, Mapping) and set(backends) == {"local", "cache"}


def activate_influence(
    setting: InfluenceSetting,
    *,
    root: Path,
    resolvers: Mapping[str, SourceResolver] | None = None,
) -> ActiveInfluence | None:
    """Activate enabled influence only after every ordered check succeeds."""
    if not isinstance(setting, InfluenceSetting):
        _fail("setting_invalid", "ontology_influence")
    if setting.mode in ("off", "shadow"):
        if any(
            value is not None
            for value in (
                setting.registry_path,
                setting.registry_digest,
                setting.promotion_evidence,
                setting.promotion_evidence_digest,
            )
        ):
            _fail("setting_invalid", "ontology_influence")
    elif setting.mode == "enabled":
        validated_setting = _setting_from_value(
            {
                "mode": setting.mode,
                "registry": setting.registry_path,
                "registry_digest": setting.registry_digest,
                "promotion_evidence": setting.promotion_evidence,
                "promotion_evidence_digest": setting.promotion_evidence_digest,
            }
        )
        if validated_setting != setting:
            _fail("setting_invalid", "ontology_influence")
    else:
        _fail("setting_invalid", "ontology_influence.mode")
    if setting.mode in ("off", "shadow"):
        return None
    if setting.registry_path is None or setting.registry_digest is None:
        _fail("setting_invalid", "ontology_influence")

    try:
        registry = load_registry(
            setting.registry_path,
            root=root,
            expected_kind="approved_registry",
        )
    except ConceptRegistryError as exc:
        raise OntologyInfluenceError(exc.reason, exc.field) from exc
    if registry.registry_digest != setting.registry_digest:
        _fail("registry_digest_mismatch", "registry_digest")

    if _registry_has_ambiguity(registry):
        _fail("registry_ambiguous", "registry.concepts")

    try:
        verification = verify_source_bindings(registry, root=root, resolvers=resolvers)
    except ConceptRegistryError as exc:
        raise OntologyInfluenceError(exc.reason, exc.field) from exc
    if verification.stale_concept_ids:
        _fail("registry_stale", "registry.source_bindings")

    evidence = _read_evidence(setting, root)
    try:
        validate_promotion_evidence(evidence)
    except OntologyInfluenceError as exc:
        if not _backends_complete(evidence):
            raise OntologyInfluenceError(
                "evidence_backends_incomplete", "backends"
            ) from exc
        raise

    evidence_registry = _evidence_object(evidence["registry"], "registry")
    if evidence_registry["digest"] != setting.registry_digest:
        _fail("evidence_registry_mismatch", "registry.digest")
    implementation_digest = influence_implementation_digest()
    if evidence["implementation_digest"] != implementation_digest:
        _fail("evidence_implementation_mismatch", "implementation_digest")
    if evidence["status"] != "promotable":
        _fail("evidence_not_promotable", "status")
    if not _backends_complete(evidence):
        _fail("evidence_backends_incomplete", "backends")

    evidence_digest = setting.promotion_evidence_digest
    if evidence_digest is None:
        _fail("setting_invalid", "ontology_influence.promotion_evidence_digest")
    return ActiveInfluence(
        setting,
        registry,
        evidence_digest,
        implementation_digest,
    )


def influence_disclosure(
    active: ActiveInfluence, channel: OntologyChannel
) -> dict[str, Any]:
    """Return the exact additive influence disclosure for a ranked channel."""
    if not isinstance(active, ActiveInfluence):
        _fail("active_influence_invalid", "active")
    if not isinstance(channel, OntologyChannel):
        _fail("channel_invalid", "channel")
    return {
        "mode": "enabled",
        "channel": "ontology",
        "retrieval_influence": True,
        "registry_digest": active.registry.registry_digest,
        "promotion_evidence_digest": active.evidence_digest,
        "implementation_digest": active.implementation_digest,
        "contributing_concept_ids": list(channel.contributing_concept_ids),
    }


def context_v2(
    context_v1: Mapping[str, Any], disclosure: Mapping[str, Any]
) -> dict[str, Any]:
    """Deep-copy context v1 into the additive context v2 contract."""
    if not isinstance(context_v1, Mapping) or not isinstance(disclosure, Mapping):
        _fail("wrapper_invalid", "context")
    result = copy.deepcopy(dict(context_v1))
    result["schema"] = CONTEXT_V2_SCHEMA
    result["ontology_influence"] = copy.deepcopy(dict(disclosure))
    return result


def explain_search_v2(
    explain_v1: Mapping[str, Any], disclosure: Mapping[str, Any]
) -> dict[str, Any]:
    """Deep-copy explain-search v1 into the additive v2 contract."""
    if not isinstance(explain_v1, Mapping) or not isinstance(disclosure, Mapping):
        _fail("wrapper_invalid", "explain_search")
    result = copy.deepcopy(dict(explain_v1))
    result["schema"] = EXPLAIN_SEARCH_V2_SCHEMA
    result["ranking_influence"] = copy.deepcopy(dict(disclosure))
    return result
