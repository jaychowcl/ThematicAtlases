import json

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
            "strategy": "websearch",
            "target_paths": [{"path": "/samples"}],
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
    assert result["accessions"][0]["ontology_harmonization_status"] == "available"
    assert details == [
        {
            "datalink_id": "GSE1",
            "status": "available",
            "harmonization_targets": [{"id": "target-1"}],
            "strategy": "websearch",
            "target_paths": [{"path": "/samples"}],
        }
    ]


def test_harmonize_datasets_marks_unsupported_metadata_unavailable() -> None:
    result, details = AtlasHarmonizer().harmonize_datasets(
        {"accessions": [{"datalink_id": "GSE1", "accession_metadata": None}]}
    )

    assert result["accessions"][0]["accession_metadata"] is None
    assert result["accessions"][0]["ontology_harmonization_status"] == "unavailable"
    assert details == [{"datalink_id": "GSE1", "status": "unavailable"}]


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
                "strategy": "websearch",
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
        "ontology_harmonization_status": "error",
        "ontology_harmonization_error": "provider unavailable",
    }
    assert result["accessions"][1]["accession_metadata"]["harmonized"] is True
    assert details[0] == {
        "datalink_id": "GSE1",
        "status": "error",
        "error": "provider unavailable",
    }
    assert details[1]["status"] == "available"


def test_harmonize_datasets_writes_optional_details_file(tmp_path) -> None:
    details_out = tmp_path / "harmonization.json"

    AtlasHarmonizer().harmonize_datasets(
        {"accessions": [{"datalink_id": "GSE1", "accession_metadata": None}]},
        details_out=str(details_out),
    )

    assert json.loads(details_out.read_text(encoding="utf-8")) == [
        {"datalink_id": "GSE1", "status": "unavailable"}
    ]


def test_harmonizer_accepts_injected_instance_and_forwards_options() -> None:
    class RecordingHarmonizer:
        calls = []

        def harmonize_miniml_json(self, **kwargs):
            self.__class__.calls.append(kwargs)
            return {
                "miniml_json": kwargs["miniml_json"],
                "harmonization_targets": [],
                "strategy": kwargs["strategy"],
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
            "strategy": "rag",
            "target_paths": [{"path": "/samples"}],
            "llm": False,
        },
    )

    assert RecordingHarmonizer.calls == [
        {
            "publication_context": None,
            "miniml_json": {"value": "x"},
            "strategy": "rag",
            "target_paths": [{"path": "/samples"}],
            "llm": False,
        }
    ]


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
        harmonization_options={"llm": True},
    )

    assert result["accessions"][0]["ontology_harmonization_status"] == "unavailable"


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


def test_harmonizer_memoizes_identical_metadata_and_context() -> None:
    class CountingHarmonizer:
        calls = 0

        def harmonize_miniml_json(self, **kwargs):
            self.__class__.calls += 1
            return {
                "miniml_json": {**kwargs["miniml_json"], "harmonized": True},
                "harmonization_targets": [],
                "strategy": "websearch",
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
                "strategy": "websearch",
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
