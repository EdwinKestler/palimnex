"""Bounded, deterministic concept-registry v1 parsing and matching.

The registry is an optional, source-backed retrieval-support artifact.  It is
never an authority for external actions and this module does not touch cache,
ledger, configuration defaults, retrieval, or the network.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NoReturn, cast

from .cache_v3 import project_id
from .core import project_slug
from .durable import canonical_json
from .locators import (
    RepositoryResolver,
    ResolvedSource,
    SourceLocator,
    SourceResolver,
    resolve_locator,
)
from .security import read_bounded_file, scan_bytes


REGISTRY_SCHEMA = "palimnex:concept-registry:v1"
REGISTRY_VERSION = 1
REGISTRY_KINDS = frozenset({"approved_registry", "candidate_set"})
CONCEPT_STATUSES = frozenset({"candidate", "approved", "superseded", "withdrawn"})
RELATION_TYPES = frozenset(
    {"broader_than", "narrower_than", "related_to", "depends_on"}
)
PROVENANCE_ORIGINS = frozenset({"manual", "deterministic", "model_candidate"})

MAX_REGISTRY_BYTES = 1_000_000
MAX_CONCEPTS = 512
MIN_CONCEPT_ID_CHARS = 3
MAX_CONCEPT_ID_CHARS = 128
MAX_CANONICAL_NAME_CHARS = 256
MAX_ALIASES_PER_CONCEPT = 32
MAX_ALIAS_CHARS = 128
MAX_DEFINITION_CHARS = 4096
MAX_RELATIONS_PER_CONCEPT = 32
MAX_SOURCE_BINDINGS_PER_CONCEPT = 32
MAX_PROJECT_SLUG_CHARS = 128

_CONCEPT_ID_RE = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*")
_PROJECT_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_PROJECT_ID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_PLACEHOLDER_LOCATOR_DIGEST = "0" * 64

RegistryKind = Literal["approved_registry", "candidate_set"]


class ConceptRegistryError(ValueError):
    """A non-echoing registry refusal with a stable machine reason."""

    def __init__(self, reason: str, field: str = "registry") -> None:
        self.reason = reason
        self.field = field
        super().__init__(f"concept registry refused: {reason} at {field}")


@dataclass(frozen=True)
class ProjectIdentity:
    project_slug: str
    project_id: str


@dataclass(frozen=True)
class ConceptRelation:
    relation_type: str
    target_concept_id: str


@dataclass(frozen=True)
class ConceptProvenance:
    origin: str


@dataclass(frozen=True)
class Concept:
    concept_id: str
    canonical_name: str
    aliases: tuple[str, ...]
    definition: str
    relations: tuple[ConceptRelation, ...]
    source_bindings: tuple[SourceLocator, ...]
    status: str
    predecessor_concept_id: str | None
    provenance: ConceptProvenance


@dataclass(frozen=True)
class ConceptRegistry:
    schema: str
    project: ProjectIdentity
    registry_version: int
    registry_kind: RegistryKind
    concepts: tuple[Concept, ...]
    registry_digest: str
    authority: str
    authorizes_actions: bool

    @property
    def active_concepts(self) -> tuple[Concept, ...]:
        """Approved concepts eligible for matching, in concept-ID order."""
        if self.registry_kind != "approved_registry":
            return ()
        return tuple(item for item in self.concepts if item.status == "approved")


@dataclass(frozen=True)
class RecognizedConcept:
    concept_id: str
    matched_aliases: tuple[str, ...]


@dataclass(frozen=True)
class AliasAmbiguity:
    matched_alias: str
    concept_ids: tuple[str, ...]


@dataclass(frozen=True)
class ConceptMatchResult:
    recognized_concepts: tuple[RecognizedConcept, ...]
    ambiguities: tuple[AliasAmbiguity, ...]

    @property
    def recognized_concept_ids(self) -> tuple[str, ...]:
        return tuple(item.concept_id for item in self.recognized_concepts)

    @property
    def ambiguous_concept_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted({concept_id for item in self.ambiguities for concept_id in item.concept_ids})
        )


@dataclass(frozen=True)
class BindingVerification:
    concept_id: str
    binding_index: int
    verified: bool
    reason: str


@dataclass(frozen=True)
class SourceVerificationResult:
    bindings: tuple[BindingVerification, ...]
    verified_concept_ids: tuple[str, ...]
    stale_concept_ids: tuple[str, ...]


def normalize_alias(text: str) -> str:
    """Return the accepted NFKC/casefold/punctuation-to-space matching key."""
    if not isinstance(text, str):
        raise ConceptRegistryError("invalid_type", "alias")
    folded = unicodedata.normalize("NFKC", text).casefold()
    mapped: list[str] = []
    for character in folded:
        category = unicodedata.category(character)
        if category.startswith("C"):
            raise ConceptRegistryError("forbidden_unicode", "alias")
        if character.isspace() or category.startswith(("P", "Z")):
            mapped.append(" ")
        else:
            mapped.append(character)
    normalized = " ".join("".join(mapped).split())
    if not normalized or len(normalized) > MAX_ALIAS_CHARS:
        raise ConceptRegistryError("alias_bound", "alias")
    return normalized


def canonical_registry_digest(document: Mapping[str, Any]) -> str:
    """Hash canonical registry content with the top-level digest excluded."""
    if not isinstance(document, Mapping):
        raise ConceptRegistryError("invalid_type", "registry")
    body = dict(document)
    body.pop("registry_digest", None)
    try:
        raw = canonical_json(body)
    except (RecursionError, TypeError, ValueError) as exc:
        raise ConceptRegistryError("canonicalization_failed", "registry") from exc
    return hashlib.sha256(raw).hexdigest()


def _reject_constant(_value: str) -> NoReturn:
    raise ConceptRegistryError("non_finite_number", "registry")


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ConceptRegistryError("duplicate_key", "registry")
        result[key] = value
    return result


def _decode_registry(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_REGISTRY_BYTES:
        raise ConceptRegistryError("registry_byte_bound", "registry")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ConceptRegistryError("invalid_utf8", "registry") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_constant,
        )
    except ConceptRegistryError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ConceptRegistryError("invalid_json", "registry") from exc
    if not isinstance(value, dict):
        raise ConceptRegistryError("invalid_type", "registry")
    return cast(dict[str, Any], value)


def _require_object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConceptRegistryError("invalid_type", field)
    return cast(dict[str, Any], value)


def _require_exact_fields(
    value: Mapping[str, Any],
    required: frozenset[str],
    optional: frozenset[str],
    field: str,
) -> None:
    keys = set(value)
    if not required.issubset(keys) or keys - required - optional:
        raise ConceptRegistryError("invalid_fields", field)


def _require_string(
    value: object,
    field: str,
    *,
    minimum: int,
    maximum: int,
    pattern: re.Pattern[str] | None = None,
    bounded_text: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ConceptRegistryError("invalid_type", field)
    if not minimum <= len(value) <= maximum:
        raise ConceptRegistryError("field_bound", field)
    if pattern is not None and pattern.fullmatch(value) is None:
        raise ConceptRegistryError("invalid_pattern", field)
    if bounded_text and any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ConceptRegistryError("forbidden_control", field)
    return value


def _require_list(value: object, field: str, *, minimum: int, maximum: int) -> list[Any]:
    if not isinstance(value, list):
        raise ConceptRegistryError("invalid_type", field)
    if not minimum <= len(value) <= maximum:
        raise ConceptRegistryError("collection_bound", field)
    return cast(list[Any], value)


def _unique_items(values: list[Any], field: str) -> None:
    try:
        encoded = [canonical_json(value) for value in values]
    except (RecursionError, TypeError, ValueError) as exc:
        raise ConceptRegistryError("invalid_value", field) from exc
    if len(encoded) != len(set(encoded)):
        raise ConceptRegistryError("duplicate_item", field)


def _expected_project(root: Path) -> ProjectIdentity:
    try:
        return ProjectIdentity(project_slug(root), project_id(root))
    except (OSError, TypeError, ValueError) as exc:
        raise ConceptRegistryError("project_identity_unavailable", "project") from exc


def _parse_project(value: object, root: Path) -> ProjectIdentity:
    project = _require_object(value, "project")
    _require_exact_fields(
        project,
        frozenset({"project_slug", "project_id"}),
        frozenset(),
        "project",
    )
    slug = _require_string(
        project["project_slug"],
        "project.project_slug",
        minimum=1,
        maximum=MAX_PROJECT_SLUG_CHARS,
        pattern=_PROJECT_SLUG_RE,
    )
    identity = _require_string(
        project["project_id"],
        "project.project_id",
        minimum=36,
        maximum=36,
        pattern=_PROJECT_ID_RE,
    )
    parsed = ProjectIdentity(slug, identity)
    if parsed != _expected_project(root):
        raise ConceptRegistryError("project_mismatch", "project")
    return parsed


def _parse_relation(value: object, field: str) -> ConceptRelation:
    relation = _require_object(value, field)
    _require_exact_fields(
        relation,
        frozenset({"relation_type", "target_concept_id"}),
        frozenset(),
        field,
    )
    relation_type = _require_string(
        relation["relation_type"], field + ".relation_type", minimum=10, maximum=13
    )
    if relation_type not in RELATION_TYPES:
        raise ConceptRegistryError("invalid_value", field + ".relation_type")
    target = _require_string(
        relation["target_concept_id"],
        field + ".target_concept_id",
        minimum=MIN_CONCEPT_ID_CHARS,
        maximum=MAX_CONCEPT_ID_CHARS,
        pattern=_CONCEPT_ID_RE,
    )
    return ConceptRelation(relation_type, target)


def _parse_provenance(value: object, field: str) -> ConceptProvenance:
    provenance = _require_object(value, field)
    _require_exact_fields(provenance, frozenset({"origin"}), frozenset(), field)
    origin = _require_string(provenance["origin"], field + ".origin", minimum=6, maximum=15)
    if origin not in PROVENANCE_ORIGINS:
        raise ConceptRegistryError("invalid_value", field + ".origin")
    return ConceptProvenance(origin)


def _parse_binding(
    value: object,
    field: str,
    *,
    allow_placeholder_digests: bool,
) -> SourceLocator:
    binding = _require_object(value, field)
    try:
        locator = SourceLocator.from_dict(binding)
    except (TypeError, ValueError) as exc:
        raise ConceptRegistryError("invalid_source_binding", field) from exc
    if locator.digest == _PLACEHOLDER_LOCATOR_DIGEST and not allow_placeholder_digests:
        raise ConceptRegistryError("placeholder_digest", field + ".digest")
    return locator


def _parse_concept(
    value: object,
    index: int,
    *,
    registry_kind: RegistryKind,
    allow_placeholder_digests: bool,
) -> Concept:
    field = f"concepts[{index}]"
    concept = _require_object(value, field)
    _require_exact_fields(
        concept,
        frozenset(
            {
                "concept_id",
                "canonical_name",
                "aliases",
                "definition",
                "source_bindings",
                "status",
                "provenance",
            }
        ),
        frozenset({"relations", "predecessor_concept_id"}),
        field,
    )
    concept_id = _require_string(
        concept["concept_id"],
        field + ".concept_id",
        minimum=MIN_CONCEPT_ID_CHARS,
        maximum=MAX_CONCEPT_ID_CHARS,
        pattern=_CONCEPT_ID_RE,
    )
    canonical_name = _require_string(
        concept["canonical_name"],
        field + ".canonical_name",
        minimum=1,
        maximum=MAX_CANONICAL_NAME_CHARS,
        bounded_text=True,
    )
    aliases_value = _require_list(
        concept["aliases"],
        field + ".aliases",
        minimum=0,
        maximum=MAX_ALIASES_PER_CONCEPT,
    )
    _unique_items(aliases_value, field + ".aliases")
    aliases: list[str] = []
    matching_keys = {normalize_alias(canonical_name)}
    for alias_index, alias_value in enumerate(aliases_value):
        alias_field = f"{field}.aliases[{alias_index}]"
        alias = _require_string(
            alias_value,
            alias_field,
            minimum=1,
            maximum=MAX_ALIAS_CHARS,
            bounded_text=True,
        )
        normalized = normalize_alias(alias)
        if normalized != alias:
            raise ConceptRegistryError("alias_not_normalized", alias_field)
        if normalized in matching_keys:
            raise ConceptRegistryError("duplicate_matching_key", alias_field)
        matching_keys.add(normalized)
        aliases.append(alias)

    definition = _require_string(
        concept["definition"],
        field + ".definition",
        minimum=1,
        maximum=MAX_DEFINITION_CHARS,
        bounded_text=True,
    )
    relations_value = _require_list(
        concept.get("relations", []),
        field + ".relations",
        minimum=0,
        maximum=MAX_RELATIONS_PER_CONCEPT,
    )
    _unique_items(relations_value, field + ".relations")
    relations = tuple(
        _parse_relation(item, f"{field}.relations[{relation_index}]")
        for relation_index, item in enumerate(relations_value)
    )

    bindings_value = _require_list(
        concept["source_bindings"],
        field + ".source_bindings",
        minimum=0,
        maximum=MAX_SOURCE_BINDINGS_PER_CONCEPT,
    )
    _unique_items(bindings_value, field + ".source_bindings")
    bindings = tuple(
        _parse_binding(
            item,
            f"{field}.source_bindings[{binding_index}]",
            allow_placeholder_digests=allow_placeholder_digests,
        )
        for binding_index, item in enumerate(bindings_value)
    )

    status = _require_string(concept["status"], field + ".status", minimum=8, maximum=10)
    if status not in CONCEPT_STATUSES:
        raise ConceptRegistryError("invalid_value", field + ".status")
    allowed_statuses = (
        {"approved", "superseded", "withdrawn"}
        if registry_kind == "approved_registry"
        else {"candidate", "withdrawn"}
    )
    if status not in allowed_statuses:
        raise ConceptRegistryError("registry_kind_status", field + ".status")
    if status == "approved" and not bindings:
        raise ConceptRegistryError("approved_source_required", field + ".source_bindings")

    predecessor_value = concept.get("predecessor_concept_id")
    predecessor = None
    if predecessor_value is not None:
        predecessor = _require_string(
            predecessor_value,
            field + ".predecessor_concept_id",
            minimum=MIN_CONCEPT_ID_CHARS,
            maximum=MAX_CONCEPT_ID_CHARS,
            pattern=_CONCEPT_ID_RE,
        )
    provenance = _parse_provenance(concept["provenance"], field + ".provenance")
    return Concept(
        concept_id,
        canonical_name,
        tuple(aliases),
        definition,
        relations,
        bindings,
        status,
        predecessor,
        provenance,
    )


def _validate_concept_graph(concepts: tuple[Concept, ...]) -> None:
    by_id: dict[str, Concept] = {}
    for concept in concepts:
        if concept.concept_id in by_id:
            raise ConceptRegistryError("duplicate_concept_id", "concepts")
        by_id[concept.concept_id] = concept

    successor_counts: dict[str, int] = {}
    for concept in concepts:
        for relation in concept.relations:
            if relation.target_concept_id not in by_id:
                raise ConceptRegistryError("missing_relation_target", "concepts.relations")
        predecessor = concept.predecessor_concept_id
        if predecessor is None:
            continue
        if predecessor == concept.concept_id or predecessor not in by_id:
            raise ConceptRegistryError("invalid_predecessor", "concepts.predecessor_concept_id")
        if by_id[predecessor].status != "superseded":
            raise ConceptRegistryError("predecessor_not_superseded", "concepts")
        if concept.status not in {"approved", "superseded"}:
            raise ConceptRegistryError("invalid_successor_status", "concepts")
        successor_counts[predecessor] = successor_counts.get(predecessor, 0) + 1
        if successor_counts[predecessor] > 1:
            raise ConceptRegistryError("supersession_fork", "concepts")

    for concept in concepts:
        seen: set[str] = set()
        current: str | None = concept.concept_id
        while current is not None:
            if current in seen:
                raise ConceptRegistryError("supersession_cycle", "concepts")
            seen.add(current)
            parent = by_id[current].predecessor_concept_id
            current = parent


def parse_registry(
    document: Mapping[str, Any],
    *,
    root: Path,
    expected_kind: RegistryKind | None = None,
    allow_placeholder_digests: bool = False,
) -> ConceptRegistry:
    """Validate and parse an in-memory concept-registry document."""
    if not isinstance(document, Mapping):
        raise ConceptRegistryError("invalid_type", "registry")
    try:
        raw = canonical_json(document)
    except (RecursionError, TypeError, ValueError) as exc:
        raise ConceptRegistryError("canonicalization_failed", "registry") from exc
    try:
        findings = scan_bytes(raw)
    except UnicodeError as exc:
        raise ConceptRegistryError("invalid_utf8", "registry") from exc
    if findings:
        raise ConceptRegistryError("registry_privacy_refused", "registry")
    value = dict(document)
    _require_exact_fields(
        value,
        frozenset(
            {
                "schema",
                "project",
                "registry_version",
                "registry_kind",
                "concepts",
                "registry_digest",
                "authority",
                "authorizes_actions",
            }
        ),
        frozenset(),
        "registry",
    )
    if value["schema"] != REGISTRY_SCHEMA:
        raise ConceptRegistryError("schema_mismatch", "schema")
    if type(value["registry_version"]) is not int or value["registry_version"] != REGISTRY_VERSION:
        raise ConceptRegistryError("version_mismatch", "registry_version")
    kind_value = value["registry_kind"]
    if not isinstance(kind_value, str) or kind_value not in REGISTRY_KINDS:
        raise ConceptRegistryError("invalid_value", "registry_kind")
    registry_kind = cast(RegistryKind, kind_value)
    if expected_kind is not None and registry_kind != expected_kind:
        raise ConceptRegistryError("registry_kind_mismatch", "registry_kind")

    project = _parse_project(value["project"], root)
    concepts_value = _require_list(
        value["concepts"], "concepts", minimum=1, maximum=MAX_CONCEPTS
    )
    concepts = tuple(
        _parse_concept(
            item,
            index,
            registry_kind=registry_kind,
            allow_placeholder_digests=allow_placeholder_digests,
        )
        for index, item in enumerate(concepts_value)
    )
    _validate_concept_graph(concepts)

    digest = _require_string(
        value["registry_digest"],
        "registry_digest",
        minimum=64,
        maximum=64,
        pattern=_DIGEST_RE,
    )
    if digest != canonical_registry_digest(value):
        raise ConceptRegistryError("registry_digest_mismatch", "registry_digest")
    if value["authority"] != "historical_only":
        raise ConceptRegistryError("authority_mismatch", "authority")
    if value["authorizes_actions"] is not False:
        raise ConceptRegistryError("authorizes_actions", "authorizes_actions")

    return ConceptRegistry(
        REGISTRY_SCHEMA,
        project,
        REGISTRY_VERSION,
        registry_kind,
        tuple(sorted(concepts, key=lambda item: item.concept_id)),
        digest,
        "historical_only",
        False,
    )


def load_registry(
    path: str | Path,
    *,
    root: Path,
    expected_kind: RegistryKind | None = None,
    allow_placeholder_digests: bool = False,
) -> ConceptRegistry:
    """Boundedly load, privacy-scan, validate, and digest-check a registry."""
    try:
        raw = read_bounded_file(root, path, max_bytes=MAX_REGISTRY_BYTES)
    except (OSError, TypeError, ValueError) as exc:
        raise ConceptRegistryError("registry_read_refused", "path") from exc
    try:
        findings = scan_bytes(raw)
    except UnicodeError as exc:
        raise ConceptRegistryError("invalid_utf8", "registry") from exc
    if findings:
        raise ConceptRegistryError("registry_privacy_refused", "registry")
    document = _decode_registry(raw)
    return parse_registry(
        document,
        root=root,
        expected_kind=expected_kind,
        allow_placeholder_digests=allow_placeholder_digests,
    )


def _contains_token_sequence(query_tokens: tuple[str, ...], key: str) -> bool:
    key_tokens = tuple(key.split(" "))
    width = len(key_tokens)
    return any(
        query_tokens[offset : offset + width] == key_tokens
        for offset in range(len(query_tokens) - width + 1)
    )


def match_aliases(registry: ConceptRegistry, query: str) -> ConceptMatchResult:
    """Match normalized alias token sequences without resolving collisions."""
    if not isinstance(registry, ConceptRegistry):
        raise ConceptRegistryError("invalid_type", "registry")
    if not isinstance(query, str):
        raise ConceptRegistryError("invalid_type", "query")
    raw = query.encode("utf-8")
    if scan_bytes(raw):
        raise ConceptRegistryError("query_privacy_refused", "query")
    admitted_query = "".join(
        " " if character.isspace() else character for character in query
    )
    try:
        normalized_query = normalize_alias(admitted_query)
    except ConceptRegistryError as exc:
        raise ConceptRegistryError(exc.reason, "query") from exc
    query_tokens = tuple(normalized_query.split(" "))

    index: dict[str, set[str]] = {}
    for concept in registry.active_concepts:
        keys = (normalize_alias(concept.canonical_name), *concept.aliases)
        for key in keys:
            index.setdefault(key, set()).add(concept.concept_id)

    matched_by_concept: dict[str, set[str]] = {}
    ambiguities: list[AliasAmbiguity] = []
    for key in sorted(index):
        if not _contains_token_sequence(query_tokens, key):
            continue
        concept_ids = tuple(sorted(index[key]))
        for concept_id in concept_ids:
            matched_by_concept.setdefault(concept_id, set()).add(key)
        if len(concept_ids) > 1:
            ambiguities.append(AliasAmbiguity(key, concept_ids))

    recognized = tuple(
        RecognizedConcept(concept_id, tuple(sorted(matched_by_concept[concept_id])))
        for concept_id in sorted(matched_by_concept)
    )
    return ConceptMatchResult(recognized, tuple(ambiguities))


def _check_repository_path(root: Path, source_id: str) -> None:
    relative = Path(source_id)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ConceptRegistryError("source_path_refused", "source_bindings.source_id")
    try:
        current = root.resolve(strict=True)
    except OSError as exc:
        raise ConceptRegistryError("source_root_refused", "root") from exc
    for part in relative.parts:
        current = current / part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            return
        except OSError:
            return
        if stat.S_ISLNK(metadata.st_mode):
            raise ConceptRegistryError("source_symlink_refused", "source_bindings.source_id")


def _binding_is_current(
    locator: SourceLocator,
    *,
    root: Path,
    expected_project: ProjectIdentity,
    resolvers: Mapping[str, SourceResolver],
) -> bool:
    if locator.scheme == "repo":
        _check_repository_path(root, locator.source_id)
        resolver: SourceResolver | None = RepositoryResolver(root)
    else:
        resolver = resolvers.get(locator.scheme)
    if resolver is None or resolver.api_version != 1:
        return False
    # SourceResolver v1 predates ontology project binding.  A resolver that
    # exposes either scope attribute is making an explicit project claim; a
    # foreign or malformed claim is a typed refusal, not ordinary drift.
    resolver_project_id = getattr(resolver, "project_id", None)
    resolver_project_slug = getattr(resolver, "project_slug", None)
    if resolver_project_id is not None and resolver_project_id != expected_project.project_id:
        raise ConceptRegistryError("source_project_mismatch", "source_bindings")
    if resolver_project_slug is not None and resolver_project_slug != expected_project.project_slug:
        raise ConceptRegistryError("source_project_mismatch", "source_bindings")
    try:
        source = resolver.resolve(locator.source_id, locator.version)
    except Exception:
        return False
    if not isinstance(source, ResolvedSource) or source.version != locator.version:
        return False
    try:
        findings = scan_bytes(source.content)
    except (TypeError, UnicodeError, ValueError):
        return False
    if findings:
        raise ConceptRegistryError("source_privacy_refused", "source_bindings")
    try:
        # Resolve again through the public locator contract.  The second read
        # makes source changes between admission and verification stale.
        resolve_locator(locator, root, resolvers)
    except ValueError:
        return False
    return True


def verify_source_bindings(
    registry: ConceptRegistry,
    *,
    root: Path,
    resolvers: Mapping[str, SourceResolver] | None = None,
) -> SourceVerificationResult:
    """Verify active bindings, reporting ordinary drift and refusing unsafe input."""
    if not isinstance(registry, ConceptRegistry):
        raise ConceptRegistryError("invalid_type", "registry")
    if registry.project != _expected_project(root):
        raise ConceptRegistryError("project_mismatch", "project")
    active_resolvers: Mapping[str, SourceResolver] = {} if resolvers is None else resolvers
    binding_results: list[BindingVerification] = []
    verified_ids: list[str] = []
    stale_ids: list[str] = []
    for concept in registry.active_concepts:
        concept_is_current = True
        for index, locator in enumerate(concept.source_bindings):
            current = _binding_is_current(
                locator,
                root=root,
                expected_project=registry.project,
                resolvers=active_resolvers,
            )
            binding_results.append(
                BindingVerification(
                    concept.concept_id,
                    index,
                    current,
                    "verified" if current else "source_drift",
                )
            )
            concept_is_current = concept_is_current and current
        if concept_is_current:
            verified_ids.append(concept.concept_id)
        else:
            stale_ids.append(concept.concept_id)
    return SourceVerificationResult(
        tuple(binding_results), tuple(verified_ids), tuple(stale_ids)
    )
