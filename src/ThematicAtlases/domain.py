"""Versioned domain model and deterministic JSON codec for Atlas v2."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
import json
import os
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4


SCHEMA_VERSION = "2.0"


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
class PublicationReview:
    judgement: Judgement
    criteria: tuple[ReviewCriterion, ...] = ()
    evidence: tuple[Mapping[str, Any], ...] = ()


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
    degraded_stages: tuple[str, ...] = ()


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


def _only(value: Mapping[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"unknown {name} fields: {', '.join(unknown)}")


def _review(value: Any) -> PublicationReview | None:
    if value is None:
        return None
    data = _mapping(value, "PublicationReview")
    _only(data, {"judgement", "criteria", "evidence"}, "PublicationReview")
    criteria = []
    for raw in data.get("criteria", []):
        item = _mapping(raw, "ReviewCriterion")
        _only(
            item,
            {"criterion", "passed", "confidence", "evidence"},
            "ReviewCriterion",
        )
        criteria.append(ReviewCriterion(**item))
    return PublicationReview(
        judgement=Judgement(data["judgement"]),
        criteria=tuple(criteria),
        evidence=tuple(data.get("evidence", [])),
    )


def _harmonization(value: Any) -> HarmonizationResult | None:
    if value is None:
        return None
    data = _mapping(value, "HarmonizationResult")
    _only(data, {"targets", "degraded_stages"}, "HarmonizationResult")
    targets = []
    for raw in data.get("targets", []):
        item = _mapping(raw, "HarmonizationTarget")
        _only(item, {"raw_value", "path", "match"}, "HarmonizationTarget")
        match = item.get("match")
        if match is not None:
            match = _mapping(match, "OntologyMatch")
            _only(
                match,
                {"label", "accession", "framework", "confidence"},
                "OntologyMatch",
            )
            match = OntologyMatch(**match)
        targets.append(
            HarmonizationTarget(
                raw_value=item["raw_value"], path=item["path"], match=match
            )
        )
    return HarmonizationResult(
        targets=tuple(targets),
        degraded_stages=tuple(data.get("degraded_stages", [])),
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
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported Atlas schema version: {self.schema_version!r}"
            )
        if not self.atlas.atlas_id.strip() or not self.run.run_id.strip():
            raise ValueError("atlas_id and run_id must not be blank")
        if not self.atlas.title.strip():
            raise ValueError("atlas title must not be blank")
        if not self.atlas.theme.strip():
            raise ValueError("atlas theme must not be blank")
        dataset_ids = [item.dataset_id for item in self.datasets]
        if len(dataset_ids) != len(set(dataset_ids)):
            raise ValueError("duplicate dataset_id in AtlasDocument")
        publication_ids = [item.publication_id for item in self.publications]
        if len(publication_ids) != len(set(publication_ids)):
            raise ValueError("duplicate publication_id in AtlasDocument")
        known_publications = set(publication_ids)
        for dataset in self.datasets:
            if not dataset.dataset_id.strip():
                raise ValueError("dataset_id must not be blank")
            unknown = sorted(set(dataset.publication_ids) - known_publications)
            if unknown:
                raise ValueError(
                    f"dataset {dataset.dataset_id!r} references unknown publication: "
                    + ", ".join(unknown)
                )
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
            "schema_version": self.schema_version,
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
        version = str(data.get("schema_version", ""))
        if version != SCHEMA_VERSION:
            raise ValueError(f"unsupported Atlas schema version: {version!r}")

        atlas_data = _mapping(data.get("atlas"), "AtlasIdentity")
        _only(atlas_data, {"atlas_id", "title", "theme"}, "AtlasIdentity")

        run_data = _mapping(data.get("run"), "AtlasRun")
        _only(run_data, {"run_id", "created_at", "config", "status"}, "AtlasRun")
        config_data = _mapping(run_data.get("config"), "AtlasConfig")
        _only(
            config_data,
            {"queries", "metadata_repositories", "options"},
            "AtlasConfig",
        )

        datasets = []
        for raw in data.get("datasets", []):
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
            for raw_diagnostic in item.get("diagnostics", []):
                diagnostic = _mapping(raw_diagnostic, "Diagnostic")
                _only(
                    diagnostic,
                    {"code", "message", "severity", "path"},
                    "Diagnostic",
                )
                diagnostics.append(
                    Diagnostic(
                        code=diagnostic["code"],
                        message=diagnostic["message"],
                        severity=DiagnosticSeverity(diagnostic["severity"]),
                        path=diagnostic.get("path"),
                    )
                )
            datasets.append(
                Dataset(
                    dataset_id=item["dataset_id"],
                    source_repository=item["source_repository"],
                    source_ordinal=item["source_ordinal"],
                    status=DatasetStatus(item["status"]),
                    metadata=dict(item.get("metadata", {})),
                    publication_ids=tuple(item.get("publication_ids", [])),
                    review=_review(item.get("review")),
                    harmonization=_harmonization(item.get("harmonization")),
                    diagnostics=tuple(diagnostics),
                )
            )

        publications = []
        for raw in data.get("publications", []):
            item = _mapping(raw, "Publication")
            _only(
                item,
                {"publication_id", "title", "abstract", "review"},
                "Publication",
            )
            publications.append(
                Publication(
                    publication_id=item["publication_id"],
                    title=item.get("title"),
                    abstract=item.get("abstract"),
                    review=_review(item.get("review")),
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
        document = cls(
            schema_version=version,
            atlas=AtlasIdentity(**atlas_data),
            run=AtlasRun(
                run_id=run_data["run_id"],
                created_at=run_data["created_at"],
                config=AtlasConfig(
                    queries=tuple(config_data.get("queries", [])),
                    metadata_repositories=tuple(
                        config_data.get("metadata_repositories", [])
                    ),
                    options=dict(config_data.get("options", {})),
                ),
                status=RunStatus(run_data["status"]),
            ),
            datasets=tuple(datasets),
            publications=tuple(publications),
            summary=AtlasSummary(**summary_data),
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
    "ReviewCriterion",
    "RunStatus",
]
