import json
from dataclasses import replace
from pathlib import Path

import pytest

from ThematicAtlases.domain import (
    AtlasConfig,
    AtlasDocument,
    AtlasIdentity,
    AtlasRun,
    AtlasSummary,
    Dataset,
    DatasetStatus,
    Diagnostic,
    DiagnosticSeverity,
    Publication,
    RunStatus,
)
from meta_standards_converter.runtime_contracts import (
    CompletenessStatus,
    EvidenceConfidence,
    ExecutionStatus,
    OperationStatusV2,
    PublicationDisposition,
    ValidationStatus,
)


def _document() -> AtlasDocument:
    return AtlasDocument(
        atlas=AtlasIdentity(atlas_id="atlas-lung", title="Lung atlas", theme="lung"),
        run=AtlasRun(
            run_id="01JTEST",
            created_at="2026-07-31T13:39:54Z",
            config=AtlasConfig(
                queries=("lung fibrosis",),
                metadata_repositories=("geo",),
            ),
            status=RunStatus.COMPLETE,
        ),
        datasets=(
            Dataset(
                dataset_id="GSE1",
                source_repository="geo",
                source_ordinal=0,
                status=DatasetStatus.HARMONIZED,
                publication_ids=("PMID:1",),
                metadata={"accession": "GSE1"},
                diagnostics=(
                    Diagnostic(
                        code="metadata_note",
                        message="retained source value",
                        severity=DiagnosticSeverity.WARNING,
                    ),
                ),
            ),
        ),
        publications=(Publication(publication_id="PMID:1", title="Study"),),
        summary=AtlasSummary(
            dataset_count=1,
            publication_count=1,
            completed_dataset_count=1,
            failed_dataset_count=0,
        ),
    )


def test_document_round_trips_deterministically(tmp_path):
    document = _document()
    output = tmp_path / "nested" / "atlas.json"

    document.dump(output)

    assert output.read_text(encoding="utf-8").endswith("\n")
    assert AtlasDocument.load(output) == document
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == "1.0"
    assert document.to_mapping() == AtlasDocument.from_mapping(
        document.to_mapping()
    ).to_mapping()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda data: data.update(schema_version="2.0"), "unsupported Atlas schema"),
        (
            lambda data: data["datasets"].append(dict(data["datasets"][0])),
            "duplicate dataset_id",
        ),
        (
            lambda data: data["datasets"][0].update(
                publication_ids=["PMID:missing"]
            ),
            "unknown publication",
        ),
        (
            lambda data: data["summary"].update(dataset_count=2),
            "summary dataset_count",
        ),
    ],
)
def test_document_rejects_invalid_cross_references_and_summary(mutate, message):
    payload = _document().to_mapping()
    mutate(payload)

    with pytest.raises(ValueError, match=message):
        AtlasDocument.from_mapping(payload)


def test_document_rejects_unknown_top_level_fields():
    payload = _document().to_mapping()
    payload["fragmented_legacy_payload"] = {}

    with pytest.raises(ValueError, match="unknown AtlasDocument fields"):
        AtlasDocument.from_mapping(payload)


def test_harmonization_uses_clean_operation_status_v2_contract() -> None:
    payload = _document().to_mapping()
    payload["datasets"][0]["harmonization"] = {
        "targets": [],
        "status": OperationStatusV2(
            execution=ExecutionStatus.DEGRADED,
            completeness=CompletenessStatus.COMPLETE,
            evidence_confidence=EvidenceConfidence.INSUFFICIENT,
            validation=ValidationStatus.VALID,
            publication=PublicationDisposition.REVIEW_REQUIRED,
            terminal_reason="provider_degraded_no_match",
        ).to_dict(),
    }

    document = AtlasDocument.from_mapping(payload)

    assert document.datasets[0].harmonization.status.execution.value == "degraded"
    assert document.to_mapping()["datasets"][0]["harmonization"] == payload[
        "datasets"
    ][0]["harmonization"]


def test_harmonization_rejects_removed_legacy_quality_shape() -> None:
    payload = _document().to_mapping()
    payload["datasets"][0]["harmonization"] = {
        "targets": [],
        "degraded_stages": ["target_checker"],
    }

    with pytest.raises(ValueError, match="unknown .*harmonization fields"):
        AtlasDocument.from_mapping(payload)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda data: data["run"]["config"].update(queries="lung"), "queries must be an array"),
        (
            lambda data: data["datasets"][0].update(publication_ids=[1]),
            r"publication_ids\[0\] must be a nonblank string",
        ),
        (
            lambda data: data["datasets"][0].update(source_ordinal=True),
            "source_ordinal must be an integer",
        ),
        (
            lambda data: data["datasets"][0].update(
                review={
                    "judgement": "relevant",
                    "criteria": [{"criterion": "human", "passed": 1}],
                    "evidence": [],
                }
            ),
            "passed must be boolean or null",
        ),
    ],
)
def test_document_rejects_ambiguous_wire_types(mutate, message):
    payload = _document().to_mapping()
    mutate(payload)

    with pytest.raises(ValueError, match=message):
        AtlasDocument.from_mapping(payload)


def test_document_rejects_ambiguous_types_when_serializing_producer_objects():
    document = _document()
    invalid_dataset = replace(document.datasets[0], source_ordinal=True)

    with pytest.raises(ValueError, match="source_ordinal must be an integer"):
        replace(document, datasets=(invalid_dataset,)).to_mapping()


@pytest.mark.parametrize("field", ["title", "theme"])
def test_document_rejects_blank_identity_text(field):
    payload = _document().to_mapping()
    payload["atlas"][field] = "  "

    with pytest.raises(ValueError, match=f"atlas {field} must not be blank"):
        AtlasDocument.from_mapping(payload)


def test_owner_golden_fixture_is_a_valid_stable_wire_contract():
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "contracts"
        / "atlas-document-v1.json"
    )

    document = AtlasDocument.load(fixture)

    assert document.schema_version == "1.0"
    assert [dataset.dataset_id for dataset in document.datasets] == [
        "GSE100",
        "GSE200",
    ]
    assert document.to_mapping() == json.loads(fixture.read_text(encoding="utf-8"))
