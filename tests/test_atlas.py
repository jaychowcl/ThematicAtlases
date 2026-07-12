import json
import logging

import pytest

from ThematicAtlases.atlas import Atlas


class RecordingCollector:
    calls: list[dict] = []

    def collect_jsons(
        self,
        query=None,
        file=None,
        out=None,
        metadata_repositories=None,
        max_publications=None,
        collect_metadata=True,
    ):
        self.__class__.calls.append(
            {
                "query": query,
                "file": file,
                "out": out,
                "metadata_repositories": metadata_repositories,
                "max_publications": max_publications,
                "collect_metadata": collect_metadata,
            }
        )
        return [{"datalink_id": "GSE1", "publications": []}]


class RecordingFilterer:
    calls: list[dict] = []

    def filter_jsons(
        self,
        jsons=None,
        file=None,
        theme=None,
        review_filter="none",
        reviewer=None,
        _review_progress_callback=None,
    ):
        self.__class__.calls.append(
            {
                "jsons": jsons,
                "file": file,
                "theme": theme,
                "review_filter": review_filter,
                "reviewer": reviewer,
            }
        )
        return {
            "accessions": list(jsons or []),
            "publication_texts": {},
        }


class RecordingHarmonizer:
    def harmonize_datasets(self, datasets, details_out=None, harmonization_options=None):
        return datasets, {"targets": []}


class RecordingQueryGenerator:
    calls = []

    def generate_queries(self, theme, max_queries=3):
        self.__class__.calls.append((theme, max_queries))
        return {"queries": ["generated one", "generated two"]}


def test_collect_datasets_generates_queries_inside_atlas(tmp_path) -> None:
    query_file = tmp_path / "queries.txt"
    query_file.write_text("# ignored\nfile query\n", encoding="utf-8")
    RecordingCollector.calls = []
    RecordingQueryGenerator.calls = []

    Atlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
        query_generator=RecordingQueryGenerator(),
    ).collect_datasets(
        query=["explicit query"],
        file=str(query_file),
        theme="fibrosis theme",
        generate_queries=True,
        max_generated_queries=2,
    )

    assert RecordingQueryGenerator.calls == [("fibrosis theme", 2)]
    assert RecordingCollector.calls[0]["query"] == [
        "explicit query",
        "file query",
        "generated one",
        "generated two",
    ]
    assert RecordingCollector.calls[0]["file"] is None


def test_collect_datasets_validates_generated_queries_before_collection() -> None:
    class InvalidQueryGenerator:
        def generate_queries(self, theme, max_queries=3):
            return {"queries": [""]}

    RecordingCollector.calls = []

    with pytest.raises(ValueError, match="invalid queries list"):
        Atlas(
            metadata={},
            collector=RecordingCollector(),
            query_generator=InvalidQueryGenerator(),
        ).collect_datasets(theme="fibrosis", generate_queries=True)

    assert RecordingCollector.calls == []


def test_collect_datasets_requires_theme_when_generating_queries() -> None:
    RecordingCollector.calls = []

    with pytest.raises(ValueError, match="requires a non-empty theme"):
        Atlas(metadata={}, collector=RecordingCollector()).collect_datasets(
            theme=" ",
            generate_queries=True,
        )

    assert RecordingCollector.calls == []


def test_collect_datasets_does_not_create_query_generator_without_flag() -> None:
    class UnexpectedQueryGenerator:
        def generate_queries(self, theme, max_queries=3):
            raise AssertionError("query generator should not be called")

    Atlas(
        metadata={},
        collector=RecordingCollector(),
        query_generator=UnexpectedQueryGenerator(),
    ).collect_datasets(query=["manual query"])


def test_collect_datasets_runs_injected_credential_preflight_once_before_llm() -> None:
    class RecordingCredentialChecker:
        calls = 0

        def check(self):
            self.__class__.calls += 1

    RecordingCredentialChecker.calls = 0
    RecordingCollector.calls = []
    atlas = Atlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
        query_generator=RecordingQueryGenerator(),
        credential_checker=RecordingCredentialChecker(),
    )

    atlas.collect_datasets(theme="fibrosis", generate_queries=True)

    assert RecordingCredentialChecker.calls == 1
    assert RecordingCollector.calls


def test_credential_preflight_failure_prevents_collection() -> None:
    class FailingCredentialChecker:
        def check(self):
            raise RuntimeError("Google credentials unavailable")

    RecordingCollector.calls = []
    with pytest.raises(RuntimeError, match="Google credentials unavailable"):
        Atlas(
            metadata={},
            collector=RecordingCollector(),
            credential_checker=FailingCredentialChecker(),
        ).collect_datasets(theme="fibrosis")
    assert RecordingCollector.calls == []


def test_create_atlas_eagerly_caches_injected_ontostore_once_before_collection() -> None:
    events = []

    class RecordingStore:
        def cache_all(self):
            events.append("cache")
            return {"successful": ["efo"], "failed": []}

    class OrderedCollector(RecordingCollector):
        def collect_jsons(self, **kwargs):
            events.append("collect")
            return super().collect_jsons(**kwargs)

    atlas = Atlas(
        metadata={},
        collector=OrderedCollector(),
        filterer=RecordingFilterer(),
        ontostore=RecordingStore(),
        cache_ontologies=True,
    )

    atlas.create_atlas(query=["a"])
    atlas.create_atlas(query=["a"])

    assert events == ["cache", "collect", "collect"]


def test_create_atlas_does_not_cache_ontologies_by_default() -> None:
    class UnexpectedStore:
        def cache_all(self):
            raise AssertionError("cache_all should be opt-in")

    Atlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
        ontostore=UnexpectedStore(),
    ).create_atlas(query=["a"])


def test_ontology_cache_failure_prevents_collection() -> None:
    class FailingStore:
        def cache_all(self):
            raise RuntimeError("ontology cache failed")

    class UnexpectedCollector:
        def collect_jsons(self, **kwargs):
            raise AssertionError("collection must not start")

    with pytest.raises(RuntimeError, match="ontology cache failed"):
        Atlas(
            metadata={},
            collector=UnexpectedCollector(),
            ontostore=FailingStore(),
            cache_ontologies=True,
        ).create_atlas(query=["a"])


def test_atlas_rejects_managed_ontostore_with_custom_harmonizer() -> None:
    with pytest.raises(ValueError, match="custom harmonizer"):
        Atlas(metadata={}, harmonizer=object(), ontostore=object())

def test_collect_datasets_collects_then_filters_and_returns_atlas_object() -> None:
    RecordingCollector.calls = []
    RecordingFilterer.calls = []
    collector = RecordingCollector()
    filterer = RecordingFilterer()
    reviewer = object()

    assert Atlas(metadata={}, collector=collector, filterer=filterer).collect_datasets(
        query=["a"],
        file="queries.txt",
        theme="fibrosis",
        review_filter="not_relevant",
        metadata_repositories=["arrayexpress"],
        max_publications=25,
        reviewer=reviewer,
        collect_metadata=False,
    ) == {
        "accessions": [{"datalink_id": "GSE1", "publications": []}],
        "publication_texts": {},
    }
    assert RecordingCollector.calls == [
        {
            "query": ["a"],
            "file": "queries.txt",
            "out": None,
            "metadata_repositories": ["arrayexpress"],
            "max_publications": 25,
            "collect_metadata": False,
        }
    ]
    assert RecordingFilterer.calls == [
        {
            "jsons": [{"datalink_id": "GSE1", "publications": []}],
            "file": None,
            "theme": "fibrosis",
            "review_filter": "not_relevant",
            "reviewer": reviewer,
        }
    ]


def test_collect_datasets_defaults_to_metadata_collection() -> None:
    RecordingCollector.calls = []

    Atlas(metadata={}, collector=RecordingCollector()).collect_datasets(query=["a"])

    assert RecordingCollector.calls == [
        {
            "query": ["a"],
            "file": None,
            "out": None,
            "metadata_repositories": None,
            "max_publications": None,
            "collect_metadata": True,
        }
    ]


def test_collect_datasets_writes_final_atlas_object(tmp_path) -> None:
    class LocalFilterer(RecordingFilterer):
        def filter_jsons(self, **kwargs):
            return {
                "accessions": [{"datalink_id": "GSE1", "publication_text_ref": "1"}],
                "publication_texts": {"1": {"text": "full text"}},
            }

    outfile = tmp_path / "datasets.json"

    Atlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=LocalFilterer(),
    ).collect_datasets(query=["a"], out=str(outfile))

    assert outfile.read_text(encoding="utf-8") == '{\n  "accessions": [\n    {\n      "datalink_id": "GSE1",\n      "publication_text_ref": "1"\n    }\n  ],\n  "publication_texts": {\n    "1": {\n      "text": "full text"\n    }\n  }\n}'


def test_collect_datasets_writes_no_dev_snapshots(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    Atlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
    ).collect_datasets(query=["a"])

    assert not (tmp_path / ".dev").exists()


def test_harmonize_datasets_delegates_to_harmonizer() -> None:
    class RecordingHarmonizer:
        calls = []

        def harmonize_datasets(
            self, datasets, details_out=None, harmonization_options=None
        ):
            self.__class__.calls.append(
                (datasets, details_out, harmonization_options)
            )
            return {**datasets, "harmonized": True}, []

    datasets = {"accessions": [{"datalink_id": "GSE1"}], "publication_texts": {}}
    harmonizer = RecordingHarmonizer()

    assert Atlas(metadata={}, harmonizer=harmonizer).harmonize_datasets(
        datasets=datasets,
        harmonization_details_out="details.json",
        harmonization_options={"llm": False},
    ) == {**datasets, "harmonized": True}
    assert RecordingHarmonizer.calls == [
        (datasets, "details.json", {"llm": False})
    ]


def test_create_atlas_collects_then_harmonizes_and_returns_final_object() -> None:
    class RecordingAtlas(Atlas):
        calls: list[tuple[str, dict]] = []

        def _dev_run_id(self):
            return "20260623T142233"

        def collect_datasets(self, **kwargs):
            self.__class__.calls.append(("collect_datasets", kwargs))
            return {"accessions": [{"datalink_id": "GSE1"}], "publication_texts": {}}

        def harmonize_datasets(
            self,
            datasets,
            harmonization_details_out=None,
            harmonization_options=None,
        ):
            self.__class__.calls.append(
                (
                    "harmonize_datasets",
                    {
                        "datasets": datasets,
                        "harmonization_details_out": harmonization_details_out,
                        "harmonization_options": harmonization_options,
                    },
                )
            )
            return {**datasets, "harmonized": True}

    RecordingAtlas.calls = []

    assert RecordingAtlas(metadata={}).create_atlas(
        query=["a"],
        file="queries.txt",
        theme="fibrosis",
        review_filter="none",
        metadata_repositories=["arrayexpress"],
        max_publications=25,
        collect_metadata=False,
        harmonization_details_out="harmonization.json",
    ) == {
        "accessions": [{"datalink_id": "GSE1"}],
        "publication_texts": {},
        "harmonized": True,
    }
    assert RecordingAtlas.calls == [
        (
            "collect_datasets",
            {
                "query": ["a"],
                "file": "queries.txt",
                "out": None,
                "theme": "fibrosis",
                "review_filter": "none",
                "metadata_repositories": ["arrayexpress"],
                "max_publications": 25,
                "reviewer": None,
                "collect_metadata": False,
                "generate_queries": False,
                "max_generated_queries": 3,
            },
        ),
        (
            "harmonize_datasets",
            {
                "datasets": {
                    "accessions": [{"datalink_id": "GSE1"}],
                    "publication_texts": {},
                },
                    "harmonization_details_out": "harmonization.json",
                    "harmonization_options": None,
            },
        ),
    ]


def test_create_atlas_writes_final_harmonized_object(tmp_path) -> None:
    class RecordingAtlas(Atlas):
        def collect_datasets(self, **kwargs):
            return {
                "accessions": [{"datalink_id": "GSE1", "publication_text_ref": "1"}],
                "publication_texts": {"1": {"text": "full text"}},
            }

        def harmonize_datasets(
            self,
            datasets,
            harmonization_details_out=None,
            harmonization_options=None,
        ):
            return {**datasets, "harmonized": True}

    outfile = tmp_path / "atlas.json"

    RecordingAtlas(metadata={}).create_atlas(query=["a"], out=str(outfile))

    assert json.loads(outfile.read_text(encoding="utf-8")) == {
        "accessions": [{"datalink_id": "GSE1", "publication_text_ref": "1"}],
        "publication_texts": {"1": {"text": "full text"}},
        "harmonized": True,
    }
    summary = json.loads((tmp_path / "atlas.summary.json").read_text(encoding="utf-8"))
    assert summary["counts"] == {
        "accessions": 1,
        "publications": 0,
        "publication_texts": 1,
    }


def test_create_atlas_without_output_or_trace_writes_no_files(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)

    Atlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
    ).create_atlas(query=["a"])

    assert list(tmp_path.iterdir()) == []


def test_create_atlas_writes_complete_opt_in_dev_trace(tmp_path) -> None:
    class LocalAtlas(Atlas):
        def _dev_run_id(self):
            return "20260623T142233"

    dev_dir = tmp_path / "debug"

    LocalAtlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
    ).create_atlas(query=["a"], dev_trace=True, dev_out_dir=str(dev_dir))

    run_dir = dev_dir / "20260623T142233"
    assert sorted(path.name for path in run_dir.iterdir()) == [
        "00_run_manifest.json",
        "01_collected_accessions.json",
        "02_reviewed_datasets.json",
        "03_pre_harmonization_accession_metadata.json",
        "04_harmonization_details.json",
        "05_post_harmonization_accession_metadata.json",
        "06_final_atlas.json",
        "07_summary.json",
    ]
    assert json.loads(
        (run_dir / "06_final_atlas.json").read_text(
            encoding="utf-8"
        )
    ) == {
        "accessions": [
            {
                "datalink_id": "GSE1",
                "publications": [],
                "ontology_harmonization_status": "unavailable",
            }
        ],
        "publication_texts": {},
    }


def test_create_atlas_logs_progress_and_stats(caplog) -> None:
    caplog.set_level(logging.INFO, logger="ThematicAtlases.atlas")

    Atlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
    ).create_atlas(query=["a"])

    assert "Atlas create_atlas progress stage=collect-datasets" in caplog.text
    assert "Atlas create_atlas progress stage=harmonize-datasets" in caplog.text
    assert "final_accessions=1" in caplog.text
    assert "publication_texts=0" in caplog.text


def test_resume_from_collected_accessions_skips_collection(tmp_path) -> None:
    run_dir = tmp_path / "trace" / "20260712T215848"
    run_dir.mkdir(parents=True)
    (run_dir / "00_run_manifest.json").write_text(
        json.dumps({
            "run_id": "20260712T215848",
            "atlas_out": str(tmp_path / "atlas.json"),
            "theme": "fibrosis",
            "review_filter": "not_relevant",
            "harmonization_options": {},
        }),
        encoding="utf-8",
    )
    (run_dir / "01_collected_accessions.json").write_text(
        json.dumps([{"datalink_id": "GSE1", "publications": []}]),
        encoding="utf-8",
    )

    class NoCollector:
        def collect_jsons(self, **kwargs):
            raise AssertionError("collection must not rerun")

    atlas = Atlas(
        metadata={},
        collector=NoCollector(),
        filterer=RecordingFilterer(),
        harmonizer=RecordingHarmonizer(),
    )
    result = atlas.resume(dev_out_dir=str(tmp_path / "trace"))

    assert result["accessions"][0]["datalink_id"] == "GSE1"
    assert (run_dir / "02_reviewed_datasets.json").exists()
    assert (run_dir / "06_final_atlas.json").exists()


def test_resume_uses_latest_incomplete_valid_trace(tmp_path) -> None:
    root = tmp_path / "trace"
    for run_id in ("20260712T100000", "20260712T110000"):
        run_dir = root / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "00_run_manifest.json").write_text(
            json.dumps({"run_id": run_id, "theme": None, "review_filter": "none"}),
            encoding="utf-8",
        )
        (run_dir / "02_reviewed_datasets.json").write_text(
            json.dumps({"accessions": [{"datalink_id": run_id}], "publication_texts": {}}),
            encoding="utf-8",
        )
    completed = root / "20260712T120000"
    completed.mkdir()
    (completed / "00_run_manifest.json").write_text(
        json.dumps({"run_id": "20260712T120000"}), encoding="utf-8"
    )
    (completed / "06_final_atlas.json").write_text(
        json.dumps({"accessions": [], "publication_texts": {}}), encoding="utf-8"
    )

    result = Atlas(
        metadata={}, collector=RecordingCollector(), filterer=RecordingFilterer(), harmonizer=RecordingHarmonizer()
    ).resume(dev_out_dir=str(root))

    assert result["accessions"][0]["datalink_id"] == "20260712T110000"
