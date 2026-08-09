import json

import pytest

from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.harmonizer import AtlasHarmonizer
from agentic_curator.contracts import MINiMLAnnotationPatch
from meta_standards_converter.runtime_contracts import (
    CompletenessStatus,
    EvidenceConfidence,
    ExecutionStatus,
    OperationStatusV2,
    PublicationDisposition,
    SafeErrorEnvelope,
    ValidationStatus,
)


def operation_status(
    execution: ExecutionStatus = ExecutionStatus.SUCCEEDED,
    *,
    evidence: EvidenceConfidence = EvidenceConfidence.HIGH,
    publication: PublicationDisposition = PublicationDisposition.PUBLISHABLE,
    terminal_reason: str = "harmonization_complete",
    errors: tuple[SafeErrorEnvelope, ...] = (),
) -> dict:
    return OperationStatusV2(
        execution=execution,
        completeness=CompletenessStatus.COMPLETE,
        evidence_confidence=evidence,
        validation=ValidationStatus.VALID,
        publication=publication,
        terminal_reason=terminal_reason,
        errors=errors,
    ).to_dict()


def harmonization_result(miniml_json, **extra) -> dict:
    return {
        "contract_version": "2.0",
        "status": operation_status(),
        "miniml_json": miniml_json,
        **extra,
    }


class RecordingOntologyHarmonizer:
    calls: list[dict] = []

    def harmonize_miniml_json(self, publication_context=None, miniml_json=None):
        self.__class__.calls.append(
            {
                "publication_context": publication_context,
                "miniml_json": miniml_json,
            }
        )
        return harmonization_result(
            {**miniml_json, "hz_organism": "mus musculus"},
            harmonization_targets=[{"id": "target-1"}],
            workflow="local_rag_ols",
            target_paths=[{"path": "/samples"}],
            controls={"direct_lookup_judge": True},
        )


def test_harmonize_datasets_prefers_patch_first_typed_miniml_boundary() -> None:
    document = {
        "miniml_schema_version": "2.0",
        "source": {"format": "test"},
        "database": [], "organization": [], "contributor": [], "platform": [],
        "series": {"iid": "GSE1"},
        "sample": [{"iid": "GSM1", "channel": [{"source": {"value": "lung"}}]}],
    }

    class PatchHarmonizer:
        calls = []

        def harmonize_miniml_annotations(self, **kwargs):
            self.calls.append(kwargs["miniml_json"])
            target = {
                "id": "target-1",
                "hz_field": "organism_part",
                "hz_label": "lung",
                "occurrences": [{
                    "pre_hz_field_path": "/sample/0/channel/0/source",
                    "pre_hz_label_path": "/sample/0/channel/0/source/value",
                    "parent_path": "/sample/0/channel/0/source",
                }],
            }
            return {
                "contract_version": "2.0",
                "status": operation_status(),
                "workflow": "local_exact",
                "harmonization_targets": [target],
                "annotation_patch": MINiMLAnnotationPatch.from_targets(
                    kwargs["miniml_json"], [target]
                ).to_mapping(),
            }

        def apply_miniml_annotation_patch(self, document, patch):
            from agentic_curator import OntologyHarmonizer
            return OntologyHarmonizer().apply_miniml_annotation_patch(document, patch)

    result, details = AtlasHarmonizer(
        ontology_harmonizer=PatchHarmonizer()
    ).harmonize_datasets({"accessions": [{
        "datalink_id": "GSE1", "accession_metadata": document
    }]})

    metadata = result["accessions"][0]["accession_metadata"]
    annotations = metadata["sample"][0]["channel"][0]["source"]["annotations"]
    assert annotations == [{"field": "organism_part", "value": "lung"}]
    assert details[0]["annotation_patch"]["schema_version"] == "2.0"


def test_explicit_legacy_harmonizer_output_is_strictly_validated() -> None:
    document = {
        "miniml_schema_version": "2.0",
        "source": {"format": "test"},
        "database": [], "organization": [], "contributor": [], "platform": [],
        "series": {"iid": "GSE1"}, "sample": [],
    }

    class InvalidLegacyHarmonizer:
        def harmonize_miniml_json(self, **kwargs):
            return {
                "miniml_json": {**kwargs["miniml_json"], "hz_organism": "mouse"},
                "harmonization_targets": [],
            }

    result, details = AtlasHarmonizer(
        ontology_harmonizer=InvalidLegacyHarmonizer()
    ).harmonize_datasets(
        {"accessions": [{"datalink_id": "GSE1", "accession_metadata": document}]}
    )

    assert result["accessions"][0]["ontology_harmonization_run_status"] == "error"
    assert details[0]["error"]["error_type"] == "MINiMLModelError"
    assert "unsupported MINiML package field" not in json.dumps(details[0])


def test_harmonize_datasets_replaces_metadata_and_builds_publication_context() -> None:
    RecordingOntologyHarmonizer.calls = []
    datasets = {
        "accessions": [
            {
                "datalink_id": "GSE1",
                "accession_metadata": {"organism": "Mouse"},
                "publications": [
                    {"title": "Study one", "abstractText": "Abstract one."},
                    {"title": "Study two", "abstractText": ""},
                ],
            }
        ],
        "publication_texts": {},
    }

    result, details = AtlasHarmonizer(
        ontology_harmonizer_factory=RecordingOntologyHarmonizer
    ).harmonize_datasets(datasets)

    assert RecordingOntologyHarmonizer.calls == [
        {
            "publication_context": (
                "Title: Study one\nAbstract: Abstract one.\n\nTitle: Study two"
            ),
            "miniml_json": {"organism": "Mouse"},
        }
    ]
    assert result["accessions"][0]["accession_metadata"] == {
        "organism": "Mouse",
        "hz_organism": "mus musculus",
    }
    assert result["accessions"][0]["ontology_harmonization_run_status"] == "completed"
    assert result["accessions"][0]["ontology_harmonization_status"] == operation_status()
    assert "ontology_harmonization_quality_status" not in result["accessions"][0]
    assert details == [
        {
            "datalink_id": "GSE1",
            "run_status": "completed",
            "harmonization_targets": [{"id": "target-1"}],
            "workflow": "local_rag_ols",
            "target_paths": [{"path": "/samples"}],
            "status": operation_status(),
            "controls": {"direct_lookup_judge": True},
        }
    ]


def test_harmonize_datasets_marks_unsupported_metadata_unavailable() -> None:
    result, details = AtlasHarmonizer().harmonize_datasets(
        {"accessions": [{"datalink_id": "GSE1", "accession_metadata": None}]}
    )

    assert result["accessions"][0]["accession_metadata"] is None
    assert result["accessions"][0]["ontology_harmonization_run_status"] == "not_run"
    assert details == [{
        "datalink_id": "GSE1",
        "run_status": "not_run",
        "status": OperationStatusV2(
            execution=ExecutionStatus.NOT_RUN,
            completeness=CompletenessStatus.EMPTY,
            evidence_confidence=EvidenceConfidence.NOT_ASSESSED,
            validation=ValidationStatus.NOT_RUN,
            publication=PublicationDisposition.NOT_REQUESTED,
            terminal_reason="metadata_unavailable",
        ).to_dict(),
    }]


def test_harmonize_datasets_keeps_metadata_and_annotates_individual_errors() -> None:
    class FailingThenSuccessfulHarmonizer:
        calls = 0

        def harmonize_miniml_json(self, publication_context=None, miniml_json=None):
            self.__class__.calls += 1
            if self.calls == 1:
                raise RuntimeError("provider unavailable")
            return harmonization_result(
                {**miniml_json, "harmonized": True},
                harmonization_targets=[],
                workflow="local_rag_ols",
                target_paths=[],
            )

    datasets = {
        "accessions": [
            {"datalink_id": "GSE1", "accession_metadata": {"value": "one"}},
            {"datalink_id": "GSE2", "accession_metadata": {"value": "two"}},
        ]
    }

    result, details = AtlasHarmonizer(
        ontology_harmonizer_factory=FailingThenSuccessfulHarmonizer
    ).harmonize_datasets(datasets)

    assert result["accessions"][0] == {
        "datalink_id": "GSE1",
        "accession_metadata": {"value": "one"},
        "ontology_harmonization_run_status": "error",
        "ontology_harmonization_status": details[0]["status"],
        "ontology_harmonization_error": details[0]["error"],
    }
    assert details[0]["error"]["error_type"] == "RuntimeError"
    assert "provider unavailable" not in json.dumps(details[0])
    assert result["accessions"][1]["accession_metadata"]["harmonized"] is True
    assert details[0] == {
        "datalink_id": "GSE1",
        "run_status": "error",
        "status": details[0]["status"],
        "error": details[0]["error"],
    }
    assert details[1]["run_status"] == "completed"


def test_harmonizer_checkpoints_each_work_item_and_reuses_completed_items(
    tmp_path,
) -> None:
    class InterruptingHarmonizer:
        calls = []

        def harmonize_miniml_json(self, publication_context=None, miniml_json=None):
            self.__class__.calls.append(miniml_json["value"])
            if miniml_json["value"] == "two":
                raise KeyboardInterrupt()
            return harmonization_result(
                {**miniml_json, "harmonized": True},
                harmonization_targets=[],
                workflow="local_rag_ols",
                target_paths=[],
            )

    datasets = {
        "accessions": [
            {"datalink_id": "GSE1", "accession_metadata": {"value": "one"}},
            {"datalink_id": "GSE2", "accession_metadata": {"value": "two"}},
        ]
    }
    store = CheckpointStore(tmp_path / "resume_state.sqlite")

    try:
        AtlasHarmonizer(
            ontology_harmonizer=InterruptingHarmonizer()
        ).harmonize_datasets(datasets, checkpoint_store=store)
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("test interruption must propagate")

    class CompletingHarmonizer:
        calls = []

        def harmonize_miniml_json(self, publication_context=None, miniml_json=None):
            self.__class__.calls.append(miniml_json["value"])
            return harmonization_result(
                {**miniml_json, "harmonized": True},
                harmonization_targets=[],
                workflow="local_rag_ols",
                target_paths=[],
            )

    result, _ = AtlasHarmonizer(
        ontology_harmonizer=CompletingHarmonizer()
    ).harmonize_datasets(datasets, checkpoint_store=store)

    assert InterruptingHarmonizer.calls == ["one", "two"]
    assert CompletingHarmonizer.calls == ["two"]
    assert all(
        record["accession_metadata"]["harmonized"]
        for record in result["accessions"]
    )


def test_harmonize_datasets_writes_optional_details_file(tmp_path) -> None:
    details_out = tmp_path / "harmonization.json"

    AtlasHarmonizer().harmonize_datasets(
        {"accessions": [{"datalink_id": "GSE1", "accession_metadata": None}]},
        details_out=str(details_out),
    )

    written = json.loads(details_out.read_text(encoding="utf-8"))
    assert written[0]["datalink_id"] == "GSE1"
    assert written[0]["status"]["execution"] == "not_run"


def test_harmonizer_accepts_injected_instance_and_forwards_options() -> None:
    class RecordingHarmonizer:
        calls = []

        def harmonize_miniml_json(self, **kwargs):
            self.__class__.calls.append(kwargs)
            return harmonization_result(
                kwargs["miniml_json"],
                harmonization_targets=[],
                workflow="local_rag_ols",
                target_paths=kwargs["target_paths"],
            )

    upstream = RecordingHarmonizer()
    AtlasHarmonizer(ontology_harmonizer=upstream).harmonize_datasets(
        {
            "accessions": [
                {"datalink_id": "GSE1", "accession_metadata": {"value": "x"}}
            ]
        },
        harmonization_options={
            "target_paths": [{"path": "/samples"}],
            "target_checker": False,
            "direct_lookup_judge": False,
            "rag_lookup": True,
            "rag_lookup_judge": False,
            "ols_lookup": True,
            "ols_lookup_judge": False,
            "field_assignment_judge": False,
        },
    )

    assert RecordingHarmonizer.calls == [
        {
            "publication_context": None,
            "miniml_json": {"value": "x"},
            "target_paths": [{"path": "/samples"}],
            "target_checker": False,
            "direct_lookup_judge": False,
            "rag_lookup": True,
            "rag_lookup_judge": False,
            "ols_lookup": True,
            "ols_lookup_judge": False,
            "field_assignment_judge": False,
        }
    ]


@pytest.mark.parametrize(
    "retired_option", ["llm", "lookup_llm_judge", "search_llm_judge"]
)
def test_harmonizer_rejects_retired_runtime_options_before_work(
    retired_option,
) -> None:
    def unexpected_factory():
        raise AssertionError("retired options must fail before construction")

    with pytest.raises(ValueError, match=f"removed harmonization option.*{retired_option}"):
        AtlasHarmonizer(
            ontology_harmonizer_factory=unexpected_factory
        ).harmonize_datasets(
            {"accessions": [{"datalink_id": "E-MTAB-1", "accession_metadata": None}]},
            harmonization_options={retired_option: False},
        )


def test_default_ontology_harmonizer_receives_injected_ontostore() -> None:
    from agentic_curator.curators.ontology_harmonizer import OntoStore

    store = OntoStore(ontology_frameworks={})
    harmonizer = AtlasHarmonizer(ontostore=store)._ontology_harmonizer()

    assert harmonizer.ontostore is store


def test_harmonizer_work_key_includes_ordered_preferred_ontologies() -> None:
    class PreferenceStore:
        preferred_ontology_ids = ("custom", "efo")

    harmonizer = AtlasHarmonizer(ontostore=PreferenceStore())
    first = harmonizer._work_key(
        metadata={"value": "lung"},
        publication_context=None,
        harmonization_options={},
    )
    PreferenceStore.preferred_ontology_ids = ("efo", "custom")
    second = harmonizer._work_key(
        metadata={"value": "lung"},
        publication_context=None,
        harmonization_options={},
    )

    assert first != second
    assert json.loads(first)["preferred_ontology_ids"] == ["custom", "efo"]
    assert json.loads(second)["preferred_ontology_ids"] == ["efo", "custom"]


def test_harmonizer_details_include_preferred_ontology_trace() -> None:
    class PreferenceTracingHarmonizer:
        def harmonize_miniml_json(self, **kwargs):
            return harmonization_result(
                kwargs["miniml_json"],
                harmonization_targets=[],
                workflow="local_rag_ols",
                target_paths=[],
                preferred_ontology_ids=["custom", "efo"],
            )

    _, details = AtlasHarmonizer(
        ontology_harmonizer=PreferenceTracingHarmonizer()
    ).harmonize_datasets(
        {
            "accessions": [
                {"datalink_id": "GSE1", "accession_metadata": {"value": "lung"}}
            ]
        }
    )

    assert details[0]["preferred_ontology_ids"] == ["custom", "efo"]


def test_harmonizer_surfaces_degraded_upstream_result() -> None:
    class DegradedHarmonizer:
        def harmonize_miniml_json(self, **kwargs):
            return {
                "miniml_json": kwargs["miniml_json"],
                "harmonization_targets": [],
                "workflow": "local_rag_ols",
                "target_paths": [],
                "contract_version": "2.0",
                "status": operation_status(
                    ExecutionStatus.DEGRADED,
                    evidence=EvidenceConfidence.INSUFFICIENT,
                    publication=PublicationDisposition.REVIEW_REQUIRED,
                    terminal_reason="provider_degraded_no_match",
                    errors=(
                        SafeErrorEnvelope(
                            error_type="InvalidModelOutputError",
                            provider="llm",
                            stage="target_checker",
                        ),
                    ),
                ),
            }

    result, details = AtlasHarmonizer(
        ontology_harmonizer=DegradedHarmonizer()
    ).harmonize_datasets(
        {"accessions": [{"datalink_id": "GSE1", "accession_metadata": {}}]}
    )

    status = result["accessions"][0]["ontology_harmonization_status"]
    assert status["execution"] == "degraded"
    assert status["publication"] == "review_required"
    assert status["errors"][0]["stage"] == "target_checker"
    assert "ontology_harmonization_quality_status" not in result["accessions"][0]
    assert details[0]["status"] == status
    assert "quality_status" not in details[0]
    assert "degraded_stages" not in details[0]


def test_null_metadata_never_constructs_ontology_harmonizer() -> None:
    def unexpected_factory():
        raise AssertionError("ontology harmonizer should not be constructed")

    result, _ = AtlasHarmonizer(
        ontology_harmonizer_factory=unexpected_factory
    ).harmonize_datasets(
        {
            "accessions": [
                {
                    "datalink_id": "E-MTAB-1",
                    "metadata_repository": "arrayexpress",
                    "accession_metadata": None,
                }
            ]
        },
        harmonization_options={"target_checker": True},
    )

    assert result["accessions"][0]["ontology_harmonization_run_status"] == "not_run"


def test_unsupported_repository_never_constructs_ontology_harmonizer() -> None:
    def unexpected_factory():
        raise AssertionError("unsupported repositories must stop before construction")

    result, details = AtlasHarmonizer(
        ontology_harmonizer_factory=unexpected_factory
    ).harmonize_datasets({
        "accessions": [{
            "datalink_id": "SCP259",
            "metadata_repository": "single_cell_portal",
            "accession_metadata": {"value": "x"},
        }]
    })

    assert result["accessions"][0]["ontology_harmonization_run_status"] == "not_run"
    assert details[0]["status"]["terminal_reason"] == "unsupported_repository"


def test_harmonizer_preflights_once_only_when_metadata_is_eligible() -> None:
    class RecordingChecker:
        calls = 0

        def check(self):
            self.__class__.calls += 1

    checker = RecordingChecker()
    RecordingOntologyHarmonizer.calls = []
    AtlasHarmonizer(
        ontology_harmonizer_factory=RecordingOntologyHarmonizer,
        credential_checker=checker,
    ).harmonize_datasets(
        {
            "accessions": [
                {"datalink_id": "E-MTAB-1", "accession_metadata": None},
                {"datalink_id": "GSE1", "accession_metadata": {"value": "x"}},
                {"datalink_id": "GSE2", "accession_metadata": {"value": "y"}},
            ]
        }
    )

    assert RecordingChecker.calls == 1


def test_harmonizer_skips_credential_preflight_when_all_model_stages_are_off() -> None:
    class UnexpectedChecker:
        def check(self):
            raise AssertionError("deterministic-only controls need no credentials")

    AtlasHarmonizer(
        ontology_harmonizer=RecordingOntologyHarmonizer(),
        credential_checker=UnexpectedChecker(),
    ).harmonize_datasets(
        {"accessions": [{"datalink_id": "GSE1", "accession_metadata": {"value": "x"}}]},
        harmonization_options={
            "target_checker": False,
            "direct_lookup_judge": False,
            "rag_lookup": False,
            "ols_lookup": False,
            "field_assignment_judge": False,
        },
    )


@pytest.mark.parametrize(
    ("enabled_control", "execution"),
    [
        ("target_checker", ExecutionStatus.SUCCEEDED),
        ("direct_lookup_judge", ExecutionStatus.DEGRADED),
        ("rag_lookup", ExecutionStatus.SUCCEEDED),
        ("ols_lookup", ExecutionStatus.DEGRADED),
        ("field_assignment_judge", ExecutionStatus.SUCCEEDED),
    ],
)
def test_harmonizer_adapter_forwards_controls_and_maps_upstream_status(
    enabled_control,
    execution,
) -> None:
    class StatusHarmonizer:
        calls = []

        def harmonize_miniml_json(self, **kwargs):
            self.__class__.calls.append(kwargs)
            return harmonization_result(
                kwargs["miniml_json"],
                harmonization_targets=[],
                workflow="adapter-contract",
                target_paths=[],
                status=operation_status(
                    execution,
                    publication=(
                        PublicationDisposition.REVIEW_REQUIRED
                        if execution is ExecutionStatus.DEGRADED
                        else PublicationDisposition.PUBLISHABLE
                    ),
                    terminal_reason=(
                        "provider_degraded"
                        if execution is ExecutionStatus.DEGRADED
                        else "harmonization_complete"
                    ),
                ),
            )

    StatusHarmonizer.calls = []
    controls = {
        "target_checker": False,
        "direct_lookup_judge": False,
        "rag_lookup": False,
        "ols_lookup": False,
        "field_assignment_judge": False,
        enabled_control: True,
    }
    if enabled_control == "ols_lookup":
        controls["ols_lookup_judge"] = True

    result, details = AtlasHarmonizer(
        ontology_harmonizer=StatusHarmonizer(),
    ).harmonize_datasets(
        {"accessions": [{"datalink_id": "GSE1", "accession_metadata": {"value": "x"}}]},
        harmonization_options=controls,
    )

    assert StatusHarmonizer.calls == [
        {"publication_context": None, "miniml_json": {"value": "x"}, **controls}
    ]
    assert result["accessions"][0]["ontology_harmonization_run_status"] == "completed"
    assert result["accessions"][0]["ontology_harmonization_status"]["execution"] == execution.value
    assert details[0]["status"]["execution"] == execution.value


def test_harmonizer_memoizes_identical_metadata_and_context() -> None:
    class CountingHarmonizer:
        calls = 0

        def harmonize_miniml_json(self, **kwargs):
            self.__class__.calls += 1
            return harmonization_result(
                {**kwargs["miniml_json"], "harmonized": True},
                harmonization_targets=[],
                workflow="local_rag_ols",
                target_paths=[],
            )

    CountingHarmonizer.calls = 0
    result, _ = AtlasHarmonizer(
        ontology_harmonizer=CountingHarmonizer()
    ).harmonize_datasets(
        {
            "accessions": [
                {"datalink_id": "GSE1", "accession_metadata": {"value": "x"}},
                {"datalink_id": "GSE2", "accession_metadata": {"value": "x"}},
            ]
        }
    )

    assert CountingHarmonizer.calls == 1
    assert [record["datalink_id"] for record in result["accessions"]] == [
        "GSE1",
        "GSE2",
    ]


def test_harmonizer_parallel_workers_preserve_accession_order() -> None:
    class EchoHarmonizer:
        def harmonize_miniml_json(self, **kwargs):
            return harmonization_result(
                kwargs["miniml_json"],
                harmonization_targets=[],
                workflow="local_rag_ols",
                target_paths=[],
            )

    result, _ = AtlasHarmonizer(
        ontology_harmonizer=EchoHarmonizer(),
        max_workers=2,
    ).harmonize_datasets(
        {
            "accessions": [
                {"datalink_id": f"GSE{index}", "accession_metadata": {"i": index}}
                for index in range(5)
            ]
        }
    )

    assert [record["datalink_id"] for record in result["accessions"]] == [
        "GSE0",
        "GSE1",
        "GSE2",
        "GSE3",
        "GSE4",
    ]


def test_harmonizer_rejects_zero_workers() -> None:
    with pytest.raises(ValueError, match="max_workers must be a positive integer"):
        AtlasHarmonizer(max_workers=0)


def test_harmonizer_reuses_terminal_checkpoint_without_calling_adapter(tmp_path) -> None:
    class UnexpectedHarmonizer:
        def harmonize_miniml_json(self, **kwargs):
            raise AssertionError("terminal work must not be replayed")

    datasets = {"accessions": [{"datalink_id": "GSE1", "accession_metadata": {"v": 1}}]}
    harmonizer = AtlasHarmonizer(ontology_harmonizer=UnexpectedHarmonizer())
    key = harmonizer._work_key({"v": 1}, None, {})
    import hashlib

    store = CheckpointStore(tmp_path / "resume.sqlite")
    store.put(
        "harmonization",
        hashlib.sha256(key.encode("utf-8")).hexdigest(),
        1,
        "terminal_error",
        error="invalid metadata",
    )

    result, details = harmonizer.harmonize_datasets(datasets, checkpoint_store=store)

    assert result["accessions"][0]["ontology_harmonization_error"]["error_type"] == "RuntimeError"
    assert details[0]["run_status"] == "error"
    assert details[0]["status"]["execution"] == "failed"
    assert "invalid metadata" not in json.dumps(details[0])


def test_harmonizer_replays_retryable_checkpoint_and_records_recovery(tmp_path) -> None:
    class RecoveringHarmonizer:
        calls = 0

        def harmonize_miniml_json(self, **kwargs):
            self.__class__.calls += 1
            return harmonization_result(
                {**kwargs["miniml_json"], "recovered": True},
                harmonization_targets=[],
                workflow="recovery",
                target_paths=[],
            )

    datasets = {"accessions": [{"datalink_id": "GSE1", "accession_metadata": {"v": 1}}]}
    harmonizer = AtlasHarmonizer(ontology_harmonizer=RecoveringHarmonizer())
    key = harmonizer._work_key({"v": 1}, None, {})
    import hashlib

    work_key = hashlib.sha256(key.encode("utf-8")).hexdigest()
    store = CheckpointStore(tmp_path / "resume.sqlite")
    store.put("harmonization", work_key, 1, "retryable_error", error="timeout")

    result, _ = harmonizer.harmonize_datasets(datasets, checkpoint_store=store)

    assert RecoveringHarmonizer.calls == 1
    assert result["accessions"][0]["accession_metadata"]["recovered"] is True
    assert store.get("harmonization", work_key)["status"] == "available"


def test_harmonize_jsons_wrapper_returns_only_atlas_and_writes_details(tmp_path) -> None:
    details = tmp_path / "nested" / "details.json"

    result = AtlasHarmonizer().harmonize_jsons(
        {"accessions": [{"datalink_id": "GSE1", "accession_metadata": None}]},
        details_out=str(details),
        harmonization_options={"target_checker": False},
    )

    assert result["accessions"][0]["ontology_harmonization_run_status"] == "not_run"
    written = json.loads(details.read_text(encoding="utf-8"))
    assert written[0]["datalink_id"] == "GSE1"
    assert written[0]["status"]["execution"] == "not_run"
