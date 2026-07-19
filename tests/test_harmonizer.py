import json

import pytest

from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.harmonizer import AtlasHarmonizer


class RecordingOntologyHarmonizer:
    calls: list[dict] = []

    def harmonize_miniml_json(self, publication_context=None, miniml_json=None):
        self.__class__.calls.append(
            {
                "publication_context": publication_context,
                "miniml_json": miniml_json,
            }
        )
        return {
            "miniml_json": {**miniml_json, "hz_organism": "mus musculus"},
            "harmonization_targets": [{"id": "target-1"}],
            "workflow": "local_rag_ols",
            "target_paths": [{"path": "/samples"}],
            "controls": {"direct_lookup_judge": True},
        }


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
    assert "ontology_harmonization_status" not in result["accessions"][0]
    assert details == [
        {
            "datalink_id": "GSE1",
            "run_status": "completed",
            "harmonization_targets": [{"id": "target-1"}],
            "workflow": "local_rag_ols",
            "target_paths": [{"path": "/samples"}],
            "controls": {"direct_lookup_judge": True},
        }
    ]


def test_harmonize_datasets_marks_unsupported_metadata_unavailable() -> None:
    result, details = AtlasHarmonizer().harmonize_datasets(
        {"accessions": [{"datalink_id": "GSE1", "accession_metadata": None}]}
    )

    assert result["accessions"][0]["accession_metadata"] is None
    assert result["accessions"][0]["ontology_harmonization_run_status"] == "not_run"
    assert details == [{"datalink_id": "GSE1", "run_status": "not_run"}]


def test_harmonize_datasets_keeps_metadata_and_annotates_individual_errors() -> None:
    class FailingThenSuccessfulHarmonizer:
        calls = 0

        def harmonize_miniml_json(self, publication_context=None, miniml_json=None):
            self.__class__.calls += 1
            if self.calls == 1:
                raise RuntimeError("provider unavailable")
            return {
                "miniml_json": {**miniml_json, "harmonized": True},
                "harmonization_targets": [],
                "workflow": "local_rag_ols",
                "target_paths": [],
            }

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
        "ontology_harmonization_error": "provider unavailable",
    }
    assert result["accessions"][1]["accession_metadata"]["harmonized"] is True
    assert details[0] == {
        "datalink_id": "GSE1",
        "run_status": "error",
        "error": "provider unavailable",
    }
    assert details[1]["status"] == "available"


def test_harmonizer_checkpoints_each_work_item_and_reuses_completed_items(
    tmp_path,
) -> None:
    class InterruptingHarmonizer:
        calls = []

        def harmonize_miniml_json(self, publication_context=None, miniml_json=None):
            self.__class__.calls.append(miniml_json["value"])
            if miniml_json["value"] == "two":
                raise KeyboardInterrupt()
            return {
                "miniml_json": {**miniml_json, "harmonized": True},
                "harmonization_targets": [],
                "workflow": "local_rag_ols",
                "target_paths": [],
            }

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
            return {
                "miniml_json": {**miniml_json, "harmonized": True},
                "harmonization_targets": [],
                "workflow": "local_rag_ols",
                "target_paths": [],
            }

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

    assert json.loads(details_out.read_text(encoding="utf-8")) == [
        {"datalink_id": "GSE1", "run_status": "not_run"}
    ]


def test_harmonizer_accepts_injected_instance_and_forwards_options() -> None:
    class RecordingHarmonizer:
        calls = []

        def harmonize_miniml_json(self, **kwargs):
            self.__class__.calls.append(kwargs)
            return {
                "miniml_json": kwargs["miniml_json"],
                "harmonization_targets": [],
                "workflow": "local_rag_ols",
                "target_paths": kwargs["target_paths"],
            }

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
            return {
                "miniml_json": kwargs["miniml_json"],
                "harmonization_targets": [],
                "workflow": "local_rag_ols",
                "target_paths": [],
                "preferred_ontology_ids": ["custom", "efo"],
            }

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
    "harmonization_options",
    [
        {"target_checker": True, "direct_lookup_judge": False, "rag_lookup": False, "ols_lookup": False, "field_assignment_judge": False},
        {"target_checker": False, "direct_lookup_judge": True, "rag_lookup": False, "ols_lookup": False, "field_assignment_judge": False},
        {"target_checker": False, "direct_lookup_judge": False, "rag_lookup": True, "ols_lookup": False, "field_assignment_judge": False},
        {"target_checker": False, "direct_lookup_judge": False, "rag_lookup": False, "ols_lookup": True, "ols_lookup_judge": True, "field_assignment_judge": False},
        {"target_checker": False, "direct_lookup_judge": False, "rag_lookup": False, "ols_lookup": False, "field_assignment_judge": True},
    ],
)
def test_harmonizer_preflights_for_each_enabled_model_stage(
    harmonization_options,
) -> None:
    class RecordingChecker:
        calls = 0

        def check(self):
            self.__class__.calls += 1

    RecordingChecker.calls = 0
    AtlasHarmonizer(
        ontology_harmonizer=RecordingOntologyHarmonizer(),
        credential_checker=RecordingChecker(),
    ).harmonize_datasets(
        {"accessions": [{"datalink_id": "GSE1", "accession_metadata": {"value": "x"}}]},
        harmonization_options=harmonization_options,
    )

    assert RecordingChecker.calls == 1


def test_harmonizer_memoizes_identical_metadata_and_context() -> None:
    class CountingHarmonizer:
        calls = 0

        def harmonize_miniml_json(self, **kwargs):
            self.__class__.calls += 1
            return {
                "miniml_json": {**kwargs["miniml_json"], "harmonized": True},
                "harmonization_targets": [],
                "workflow": "local_rag_ols",
                "target_paths": [],
            }

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
            return {
                "miniml_json": kwargs["miniml_json"],
                "harmonization_targets": [],
                "workflow": "local_rag_ols",
                "target_paths": [],
            }

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
