"""Versioned domain model and deterministic JSON codec for Atlas v1."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
import json
import os
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from meta_standards_converter.runtime_contracts import (
    CompletenessStatus,
    EvidenceConfidence,
    ExecutionStatus,
    OperationStatusV2,
    PublicationDisposition,
    ValidationStatus,
)

from ThematicAtlases.miniml_boundary import canonicalize_atlas_metadata


SCHEMA_VERSION = "1.1"
SUPPORTED_SCHEMA_VERSIONS = {"1.0", "1.1"}


class _ValueEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class RunStatus(_ValueEnum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class DatasetStatus(_ValueEnum):
    DISCOVERED = "discovered"
    COLLECTED = "collected"
    REVIEWED = "reviewed"
    HARMONIZED = "harmonized"
    FAILED = "failed"


class DiagnosticSeverity(_ValueEnum):
    WARNING = "warning"
    ERROR = "error"


class Judgement(_ValueEnum):
    RELEVANT = "relevant"
    NOT_RELEVANT = "not_relevant"
    UNSURE = "unsure"


class ArtifactRole(_ValueEnum):
    COLLECTION_SNAPSHOT = "collection_snapshot"
    FINAL_ATLAS = "final_atlas"
    SUMMARY = "summary"
    HARMONIZATION_DETAILS = "harmonization_details"


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR
    path: str | None = None


@dataclass(frozen=True)
class ReviewCriterion:
    criterion: str
    passed: bool | None
    confidence: str | None = None
    evidence: str | None = None


@dataclass(frozen=True)
class PublicationPolicy:
    version: int
    action: str
    exclusion_eligible: bool
    review_required: bool
    reason: str

    def __post_init__(self):
        if type(self.version) is not int or self.version != 1 or self.action not in {"retain", "exclude"}:
            raise ValueError("invalid publication policy version or action")
        if type(self.exclusion_eligible) is not bool or type(self.review_required) is not bool:
            raise ValueError("publication policy flags must be boolean")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("publication policy reason must be nonempty")
        if self.action == "exclude" and not self.exclusion_eligible:
            raise ValueError("ineligible publication cannot be excluded")


@dataclass(frozen=True)
class PublicationReview:
    judgement: Judgement
    criteria: tuple[ReviewCriterion, ...] = ()
    evidence: tuple[Mapping[str, Any], ...] = ()
    confidence: str | None = None
    policy: PublicationPolicy | None = None

    def __post_init__(self):
        if self.confidence not in {None, "low", "medium", "high"}:
            raise ValueError("invalid publication confidence")
        from agentic_curator.publication_policy import publication_policy
        expected = publication_policy(str(self.judgement), self.confidence,
            filtering_enabled=self.policy is not None and self.policy.action == "exclude")
        if self.policy is None:
            object.__setattr__(self, "policy", PublicationPolicy(**expected))
        elif (self.policy.exclusion_eligible != expected["exclusion_eligible"] or
              self.policy.review_required != expected["review_required"]):
            raise ValueError("publication policy contradicts judgement and confidence")


@dataclass(frozen=True)
class OntologyMatch:
    label: str
    accession: str
    framework: str
    confidence: str | None = None


@dataclass(frozen=True)
class HarmonizationTarget:
    raw_value: str
    path: str
    match: OntologyMatch | None = None


@dataclass(frozen=True)
class HarmonizationResult:
    targets: tuple[HarmonizationTarget, ...] = ()
    status: OperationStatusV2 = field(
        default_factory=lambda: OperationStatusV2(
            execution=ExecutionStatus.NOT_RUN,
            completeness=CompletenessStatus.EMPTY,
            evidence_confidence=EvidenceConfidence.NOT_ASSESSED,
            validation=ValidationStatus.NOT_RUN,
            publication=PublicationDisposition.NOT_REQUESTED,
            terminal_reason="harmonization_not_run",
        )
    )


@dataclass(frozen=True)
class DatasetMetadata:
    values: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactReference:
    role: ArtifactRole
    path: str
    media_type: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class AtlasIdentity:
    atlas_id: str
    title: str
    theme: str


@dataclass(frozen=True)
class AtlasConfig:
    queries: tuple[str, ...] = ()
    metadata_repositories: tuple[str, ...] = ()
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AtlasRun:
    run_id: str
    created_at: str
    config: AtlasConfig
    status: RunStatus


@dataclass(frozen=True)
class Dataset:
    dataset_id: str
    source_repository: str
    source_ordinal: int
    status: DatasetStatus
    metadata: Mapping[str, Any] = field(default_factory=dict)
    publication_ids: tuple[str, ...] = ()
    review: PublicationReview | None = None
    harmonization: HarmonizationResult | None = None
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class Publication:
    publication_id: str
    title: str | None = None
    abstract: str | None = None
    review: PublicationReview | None = None


@dataclass(frozen=True)
class AtlasSummary:
    dataset_count: int
    publication_count: int
    completed_dataset_count: int
    failed_dataset_count: int


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {item.name: _plain(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def _nonblank(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")
    return value


def _optional_string(value: Any, name: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{name} must be a string or null")
    return value


def _string_list(value: Any, name: str) -> list[str]:
    values = _list(value, name)
    for index, item in enumerate(values):
        _nonblank(item, f"{name}[{index}]")
    return values


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _only(value: Mapping[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"unknown {name} fields: {', '.join(unknown)}")


def _review(value: Any, name: str = "PublicationReview") -> PublicationReview | None:
    if value is None:
        return None
    data = _mapping(value, name)
    _only(data, {"judgement", "confidence", "policy", "criteria", "evidence"}, name)
    confidence = data.get("confidence")
    if confidence not in {None, "low", "medium", "high"}:
        raise ValueError("invalid publication confidence")
    from agentic_curator.publication_policy import publication_policy
    raw_policy = data.get("policy")
    if raw_policy is None:
        raw_policy = publication_policy(data["judgement"], confidence)
    policy = PublicationPolicy(**raw_policy)
    expected = publication_policy(data["judgement"], confidence, filtering_enabled=policy.action == "exclude")
    if policy.exclusion_eligible != expected["exclusion_eligible"] or policy.review_required != expected["review_required"]:
        raise ValueError("publication policy contradicts judgement and confidence")
    criteria = []
    for index, raw in enumerate(_list(data.get("criteria"), f"{name}.criteria")):
        item_name = f"{name}.criteria[{index}]"
        item = _mapping(raw, item_name)
        _only(
            item,
            {"criterion", "passed", "confidence", "evidence"},
            item_name,
        )
        _nonblank(item.get("criterion"), f"{item_name}.criterion")
        passed = item.get("passed")
        if passed is not None and not isinstance(passed, bool):
            raise ValueError(f"{item_name}.passed must be boolean or null")
        _optional_string(item.get("confidence"), f"{item_name}.confidence")
        _optional_string(item.get("evidence"), f"{item_name}.evidence")
        criteria.append(ReviewCriterion(**item))
    evidence = _list(data.get("evidence"), f"{name}.evidence")
    for index, raw in enumerate(evidence):
        _mapping(raw, f"{name}.evidence[{index}]")
    return PublicationReview(
        judgement=Judgement(data["judgement"]),
        confidence=confidence,
        policy=policy,
        criteria=tuple(criteria),
        evidence=tuple(evidence),
    )


def _harmonization(
    value: Any, name: str = "HarmonizationResult"
) -> HarmonizationResult | None:
    if value is None:
        return None
    data = _mapping(value, name)
    _only(data, {"targets", "status"}, name)
    targets = []
    for index, raw in enumerate(_list(data.get("targets"), f"{name}.targets")):
        item_name = f"{name}.targets[{index}]"
        item = _mapping(raw, item_name)
        _only(item, {"raw_value", "path", "match"}, item_name)
        raw_value = _nonblank(item.get("raw_value"), f"{item_name}.raw_value")
        path = _nonblank(item.get("path"), f"{item_name}.path")
        match = item.get("match")
        if match is not None:
            match = _mapping(match, f"{item_name}.match")
            _only(
                match,
                {"label", "accession", "framework", "confidence"},
                f"{item_name}.match",
            )
            match = OntologyMatch(
                label=_nonblank(match.get("label"), f"{item_name}.match.label"),
                accession=_nonblank(
                    match.get("accession"), f"{item_name}.match.accession"
                ),
                framework=_nonblank(
                    match.get("framework"), f"{item_name}.match.framework"
                ),
                confidence=_optional_string(
                    match.get("confidence"), f"{item_name}.match.confidence"
                ),
            )
        targets.append(
            HarmonizationTarget(raw_value=raw_value, path=path, match=match)
        )
    raw_status = _mapping(data.get("status"), f"{name}.status")
    status = OperationStatusV2.from_dict(raw_status)
    return HarmonizationResult(
        targets=tuple(targets),
        status=status,
    )


@dataclass(frozen=True)
class AtlasDocument:
    atlas: AtlasIdentity
    run: AtlasRun
    datasets: tuple[Dataset, ...]
    publications: tuple[Publication, ...]
    summary: AtlasSummary
    schema_version: str = SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"unsupported Atlas schema version: {self.schema_version!r}"
            )
        if not self.atlas.atlas_id.strip() or not self.run.run_id.strip():
            raise ValueError("atlas_id and run_id must not be blank")
        if not self.atlas.title.strip():
            raise ValueError("atlas title must not be blank")
        if not self.atlas.theme.strip():
            raise ValueError("atlas theme must not be blank")
        _nonblank(self.run.created_at, "run created_at")
        if not isinstance(self.run.status, RunStatus):
            raise ValueError("run status must be a RunStatus")
        if not isinstance(self.run.config.queries, (tuple, list)):
            raise ValueError("queries must be an array")
        _string_list(list(self.run.config.queries), "queries")
        if not isinstance(self.run.config.metadata_repositories, (tuple, list)):
            raise ValueError("metadata_repositories must be an array")
        _string_list(
            list(self.run.config.metadata_repositories), "metadata_repositories"
        )
        _mapping(self.run.config.options, "options")
        dataset_ids = [item.dataset_id for item in self.datasets]
        if len(dataset_ids) != len(set(dataset_ids)):
            raise ValueError("duplicate dataset_id in AtlasDocument")
        publication_ids = [item.publication_id for item in self.publications]
        if len(publication_ids) != len(set(publication_ids)):
            raise ValueError("duplicate publication_id in AtlasDocument")
        known_publications = set(publication_ids)
        for dataset_index, dataset in enumerate(self.datasets):
            _nonblank(dataset.dataset_id, "dataset_id")
            _nonblank(dataset.source_repository, "source_repository")
            _integer(dataset.source_ordinal, "source_ordinal")
            if not isinstance(dataset.status, DatasetStatus):
                raise ValueError("dataset status must be a DatasetStatus")
            _mapping(dataset.metadata, "metadata")
            canonicalize_atlas_metadata(dataset.metadata)
            if not isinstance(dataset.publication_ids, (tuple, list)):
                raise ValueError(
                    f"datasets[{dataset_index}].publication_ids must be an array"
                )
            _string_list(
                list(dataset.publication_ids),
                f"datasets[{dataset_index}].publication_ids",
            )
            _review(_plain(dataset.review), f"datasets[{dataset_index}].review")
            _harmonization(
                _plain(dataset.harmonization),
                f"datasets[{dataset_index}].harmonization",
            )
            for diagnostic in dataset.diagnostics:
                _nonblank(diagnostic.code, "diagnostic code")
                _nonblank(diagnostic.message, "diagnostic message")
                if not isinstance(diagnostic.severity, DiagnosticSeverity):
                    raise ValueError(
                        "diagnostic severity must be a DiagnosticSeverity"
                    )
                _optional_string(diagnostic.path, "diagnostic path")
            unknown = sorted(set(dataset.publication_ids) - known_publications)
            if unknown:
                raise ValueError(
                    f"dataset {dataset.dataset_id!r} references unknown publication: "
                    + ", ".join(unknown)
                )
        for publication_index, publication in enumerate(self.publications):
            _nonblank(publication.publication_id, "publication_id")
            _optional_string(publication.title, "publication title")
            _optional_string(publication.abstract, "publication abstract")
            _review(
                _plain(publication.review),
                f"publications[{publication_index}].review",
            )
        for field_name in (
            "dataset_count",
            "publication_count",
            "completed_dataset_count",
            "failed_dataset_count",
        ):
            _integer(getattr(self.summary, field_name), f"summary {field_name}")
        if self.summary.dataset_count != len(self.datasets):
            raise ValueError("summary dataset_count does not match datasets")
        if self.summary.publication_count != len(self.publications):
            raise ValueError("summary publication_count does not match publications")
        completed = sum(
            item.status == DatasetStatus.HARMONIZED for item in self.datasets
        )
        failed = sum(item.status == DatasetStatus.FAILED for item in self.datasets)
        if self.summary.completed_dataset_count != completed:
            raise ValueError(
                "summary completed_dataset_count does not match datasets"
            )
        if self.summary.failed_dataset_count != failed:
            raise ValueError("summary failed_dataset_count does not match datasets")

    def to_mapping(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": SCHEMA_VERSION,
            "atlas": _plain(self.atlas),
            "run": _plain(self.run),
            "datasets": _plain(self.datasets),
            "publications": _plain(self.publications),
            "summary": _plain(self.summary),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AtlasDocument":
        data = _mapping(value, "AtlasDocument")
        _only(
            data,
            {"schema_version", "atlas", "run", "datasets", "publications", "summary"},
            "AtlasDocument",
        )
        version = data.get("schema_version")
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(f"unsupported Atlas schema version: {version!r}")

        atlas_data = _mapping(data.get("atlas"), "AtlasIdentity")
        _only(atlas_data, {"atlas_id", "title", "theme"}, "AtlasIdentity")
        for field_name in ("atlas_id", "title", "theme"):
            if not isinstance(atlas_data.get(field_name), str):
                raise ValueError(f"atlas {field_name} must be a string")

        run_data = _mapping(data.get("run"), "AtlasRun")
        _only(run_data, {"run_id", "created_at", "config", "status"}, "AtlasRun")
        config_data = _mapping(run_data.get("config"), "AtlasConfig")
        _only(
            config_data,
            {"queries", "metadata_repositories", "options"},
            "AtlasConfig",
        )
        _nonblank(run_data.get("run_id"), "run run_id")
        _nonblank(run_data.get("created_at"), "run created_at")
        queries = _string_list(config_data.get("queries"), "queries")
        repositories = _string_list(
            config_data.get("metadata_repositories"), "metadata_repositories"
        )
        options = _mapping(config_data.get("options"), "options")

        datasets = []
        for dataset_index, raw in enumerate(_list(data.get("datasets"), "datasets")):
            item = _mapping(raw, "Dataset")
            _only(
                item,
                {
                    "dataset_id",
                    "source_repository",
                    "source_ordinal",
                    "status",
                    "metadata",
                    "publication_ids",
                    "review",
                    "harmonization",
                    "diagnostics",
                },
                "Dataset",
            )
            diagnostics = []
            for diagnostic_index, raw_diagnostic in enumerate(
                _list(item.get("diagnostics"), f"datasets[{dataset_index}].diagnostics")
            ):
                diagnostic = _mapping(raw_diagnostic, "Diagnostic")
                _only(
                    diagnostic,
                    {"code", "message", "severity", "path"},
                    "Diagnostic",
                )
                diagnostics.append(
                    Diagnostic(
                        code=_nonblank(diagnostic.get("code"), "diagnostic code"),
                        message=_nonblank(diagnostic.get("message"), "diagnostic message"),
                        severity=DiagnosticSeverity(diagnostic["severity"]),
                        path=_optional_string(diagnostic.get("path"), "diagnostic path"),
                    )
                )
            dataset_id = _nonblank(item.get("dataset_id"), "dataset_id")
            repository = _nonblank(item.get("source_repository"), "source_repository")
            ordinal = _integer(item.get("source_ordinal"), "source_ordinal")
            metadata = canonicalize_atlas_metadata(
                _mapping(item.get("metadata"), "metadata")
            )
            publication_ids = _string_list(
                item.get("publication_ids"),
                f"datasets[{dataset_index}].publication_ids",
            )
            datasets.append(
                Dataset(
                    dataset_id=dataset_id,
                    source_repository=repository,
                    source_ordinal=ordinal,
                    status=DatasetStatus(item["status"]),
                    metadata=dict(metadata),
                    publication_ids=tuple(publication_ids),
                    review=_review(item.get("review"), f"datasets[{dataset_index}].review"),
                    harmonization=_harmonization(
                        item.get("harmonization"),
                        f"datasets[{dataset_index}].harmonization",
                    ),
                    diagnostics=tuple(diagnostics),
                )
            )

        publications = []
        for publication_index, raw in enumerate(
            _list(data.get("publications"), "publications")
        ):
            item = _mapping(raw, "Publication")
            _only(
                item,
                {"publication_id", "title", "abstract", "review"},
                "Publication",
            )
            publications.append(
                Publication(
                    publication_id=_nonblank(item.get("publication_id"), "publication_id"),
                    title=_optional_string(item.get("title"), "publication title"),
                    abstract=_optional_string(item.get("abstract"), "publication abstract"),
                    review=_review(item.get("review"), f"publications[{publication_index}].review"),
                )
            )

        summary_data = _mapping(data.get("summary"), "AtlasSummary")
        _only(
            summary_data,
            {
                "dataset_count",
                "publication_count",
                "completed_dataset_count",
                "failed_dataset_count",
            },
            "AtlasSummary",
        )
        summary_values = {
            field_name: _integer(summary_data.get(field_name), f"summary {field_name}")
            for field_name in (
                "dataset_count",
                "publication_count",
                "completed_dataset_count",
                "failed_dataset_count",
            )
        }
        document = cls(
            schema_version=version,
            atlas=AtlasIdentity(**atlas_data),
            run=AtlasRun(
                run_id=run_data["run_id"],
                created_at=run_data["created_at"],
                config=AtlasConfig(
                    queries=tuple(queries),
                    metadata_repositories=tuple(repositories),
                    options=dict(options),
                ),
                status=RunStatus(run_data["status"]),
            ),
            datasets=tuple(datasets),
            publications=tuple(publications),
            summary=AtlasSummary(**summary_values),
        )
        document.validate()
        return document

    @classmethod
    def load(cls, path: str | Path) -> "AtlasDocument":
        with Path(path).open(encoding="utf-8") as handle:
            return cls.from_mapping(json.load(handle))

    def dump(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(
            f".{destination.name}.{uuid4().hex}.tmp"
        )
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                json.dump(
                    self.to_mapping(),
                    handle,
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)


__all__ = [
    "SCHEMA_VERSION",
    "ArtifactReference",
    "ArtifactRole",
    "AtlasConfig",
    "AtlasDocument",
    "AtlasIdentity",
    "AtlasRun",
    "AtlasSummary",
    "Dataset",
    "DatasetMetadata",
    "DatasetStatus",
    "Diagnostic",
    "DiagnosticSeverity",
    "HarmonizationResult",
    "HarmonizationTarget",
    "Judgement",
    "OntologyMatch",
    "Publication",
    "PublicationReview",
    "PublicationPolicy",
    "ReviewCriterion",
    "RunStatus",
]
