import json

from ThematicAtlases.atlas import Atlas
from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.cli_atlas import main
from ThematicAtlases.document_adapter import AtlasDocumentAdapter
from ThematicAtlases.domain import AtlasDocument, RunStatus
from ThematicAtlases.filterer import PublicationTextReviewer
from ThematicAtlases.harmonizer import AtlasHarmonizer
from meta_standards_converter.runtime_contracts import (
    CompletenessStatus,
    EvidenceConfidence,
    ExecutionStatus,
    OperationStatusV2,
    PublicationDisposition,
    ValidationStatus,
)


SUCCESS_STATUS = OperationStatusV2(
    execution=ExecutionStatus.SUCCEEDED,
    completeness=CompletenessStatus.COMPLETE,
    evidence_confidence=EvidenceConfidence.HIGH,
    validation=ValidationStatus.VALID,
    publication=PublicationDisposition.PUBLISHABLE,
    terminal_reason="harmonization_complete",
).to_dict()


class FakeEPMC:
    accessions = [
        {
            "datalink_id": "GSE101",
            "datalink_id_scheme": "GEO",
            "publications": [
                {"source": "MED", "epmc_id": "101", "pmid": "101", "title": "Fibrosis study"}
            ],
        }
    ]

    def collect_accessions(self, **kwargs):
        return [dict(item) for item in self.accessions]

    def collect_publication_texts(self, publications, **kwargs):
        return [
            {
                **publication,
                "text": "A fibrosis dataset.",
                "text_source": "abstract",
                "full_text_status": "unavailable",
            }
            for publication in publications
        ]


class FakeGEO:
    def collect_accession_metadata(self, jsons, **kwargs):
        return [
            {
                **record,
                "metadata_repository": "geo",
                "metadata_source": "fake-miniml",
                "metadata_status": "available",
                "accession_metadata": {"organism": "mouse"},
            }
            for record in jsons
        ]


class FakeReviewer:
    def review_relevancy(self, **kwargs):
        return {
            "strategy": kwargs["strategy"],
            "evidences": ["fibrosis"],
            "judgement": "relevant",
            "reasoning": "The text describes fibrosis.",
            "confidence": "high",
            "accessions_to_remove": [],
        }


class FakeOntologyHarmonizer:
    def harmonize_miniml_json(self, **kwargs):
        return {
            "contract_version": "2.0",
            "status": SUCCESS_STATUS,
            "miniml_json": {**kwargs["miniml_json"], "hz_organism": "Mus musculus"},
            "harmonization_targets": [{"path": "/organism"}],
            "workflow": "offline-fake",
            "target_paths": [{"path": "/organism"}],
            "controls": {"target_checker": True},
        }


class FakeCredentials:
    calls = 0

    def check(self):
        self.__class__.calls += 1


def _atlas(epmc=FakeEPMC) -> Atlas:
    FakeCredentials.calls = 0
    reviewer = PublicationTextReviewer(reviewer_factory=FakeReviewer)
    harmonizer = AtlasHarmonizer(
        ontology_harmonizer=FakeOntologyHarmonizer(),
        credential_checker=FakeCredentials(),
    )
    return Atlas(
        metadata={},
        epmc_wrapper_factory=epmc,
        metadata_handlers={"geo": FakeGEO},
        publication_text_reviewer=reviewer,
        harmonizer=harmonizer,
    )


def test_real_component_atlas_system_workflow_is_offline_and_checkpointed(tmp_path) -> None:
    output = tmp_path / "published" / "nested" / "atlas.json"
    details = tmp_path / "published" / "details" / "harmonization.json"
    trace_root = tmp_path / "trace"

    result = _atlas().create_atlas(
        query=["fibrosis"],
        out=str(output),
        theme="fibrosis",
        generate_queries=False,
        review_filter="not_relevant",
        dev_trace=True,
        dev_out_dir=str(trace_root),
        harmonization_details_out=str(details),
    )

    document = AtlasDocument.from_mapping(result)
    assert document.datasets[0].dataset_id == "GSE101"
    assert document.datasets[0].metadata == {
        "organism": "mouse",
        "hz_organism": "Mus musculus",
    }
    assert document.datasets[0].status.value == "harmonized"
    assert document.publications[0].review.judgement.value == "relevant"
    assert json.loads(output.read_text(encoding="utf-8")) == result
    harmonization_details = json.loads(details.read_text(encoding="utf-8"))
    execution_identity = harmonization_details[0].pop(
        "harmonization_execution_identity"
    )
    assert execution_identity["contract_version"] == "fallback-1.0"
    assert execution_identity["model"]["provider"].endswith(
        ".FakeOntologyHarmonizer"
    )
    assert harmonization_details == [
        {
            "datalink_id": "GSE101",
            "run_status": "completed",
            "harmonization_targets": [{"path": "/organism"}],
            "workflow": "offline-fake",
            "target_paths": [{"path": "/organism"}],
            "status": SUCCESS_STATUS,
            "controls": {"target_checker": True},
        }
    ]
    summary = json.loads((output.parent / "atlas.summary.json").read_text(encoding="utf-8"))
    assert summary["dataset_count"] == 1
    assert summary["publication_count"] == 1
    run_dir = next(path for path in trace_root.iterdir() if path.is_dir())
    assert {path.name for path in run_dir.iterdir()} == {
        "00_run_manifest.json",
        "06_final_atlas.json",
            "07_summary.json",
            "08_retry_report.json",
            "atlas_run.sqlite3",
        "atlas_run.sqlite3.locks",
        "unsupported_accessions.json",
    }
    store = CheckpointStore(run_dir / "atlas_run.sqlite3")
    assert [item["status"] for item in store.items("thematic_review")] == ["available"]
    assert [item["status"] for item in store.items("harmonization")] == ["available"]
    assert FakeCredentials.calls == 1


def test_real_component_atlas_system_workflow_preserves_empty_results(tmp_path) -> None:
    class EmptyEPMC(FakeEPMC):
        accessions = []

    output = tmp_path / "empty" / "atlas.json"
    details = tmp_path / "empty" / "details.json"

    result = _atlas(EmptyEPMC).create_atlas(
        query=["none"],
        theme="none",
        generate_queries=False,
        out=str(output),
        harmonization_details_out=str(details),
    )
    assert AtlasDocument.from_mapping(result).datasets == ()
    assert json.loads(details.read_text(encoding="utf-8")) == []
    summary = json.loads((output.parent / "atlas.summary.json").read_text())
    assert summary["dataset_count"] == 0
    assert summary["publication_count"] == 0


def test_harmonize_cli_creates_nested_output_and_details_parents(tmp_path) -> None:
    source = tmp_path / "input.json"
    source_document = AtlasDocumentAdapter().assemble(
        {"accessions": [{"datalink_id": "GSE0", "accession_metadata": None}]},
        atlas_metadata={"atlas_id": "atlas-test"},
        run_id="run-1",
        created_at="2026-07-31T00:00:00Z",
        theme="",
        config={},
        run_status=RunStatus.RUNNING,
    )
    source_document.dump(source)
    output = tmp_path / "nested" / "atlas.json"
    details = tmp_path / "nested" / "audit" / "details.json"

    assert main(
        [
            "harmonize-datasets",
            "--file",
            str(source),
            "--out",
            str(output),
            "--harmonization-details-out",
            str(details),
        ]
    ) == 0
    assert AtlasDocument.load(output).datasets[0].status.value == "discovered"
    written = json.loads(details.read_text(encoding="utf-8"))
    assert written[0]["datalink_id"] == "GSE0"
    assert written[0]["status"]["execution"] == "not_run"
