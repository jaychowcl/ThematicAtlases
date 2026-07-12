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


def test_collect_datasets_writes_timestamped_dev_snapshots_by_default(
    tmp_path,
    monkeypatch,
) -> None:
    class LocalAtlas(Atlas):
        def _dev_run_id(self):
            return "20260623T142233"

    monkeypatch.chdir(tmp_path)

    LocalAtlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
    ).collect_datasets(query=["a"])

    collected_accessions = tmp_path / ".dev" / "20260623T142233_01_collected_accessions.json"
    collected_datasets = tmp_path / ".dev" / "20260623T142233_02_collected_datasets.json"

    assert json.loads(collected_accessions.read_text(encoding="utf-8")) == [
        {"datalink_id": "GSE1", "publications": []}
    ]
    assert json.loads(collected_datasets.read_text(encoding="utf-8")) == {
        "accessions": [{"datalink_id": "GSE1", "publications": []}],
        "publication_texts": {},
    }


def test_collect_datasets_dev_out_dir_none_writes_no_dev_snapshots(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    Atlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
    ).collect_datasets(query=["a"], dev_out_dir=None)

    assert not (tmp_path / ".dev").exists()


def test_collect_datasets_writes_dev_snapshots_to_custom_directory(tmp_path) -> None:
    class LocalAtlas(Atlas):
        def _dev_run_id(self):
            return "20260623T142233"

    dev_dir = tmp_path / "debug"

    LocalAtlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
    ).collect_datasets(query=["a"], dev_out_dir=str(dev_dir))

    assert (dev_dir / "20260623T142233_01_collected_accessions.json").exists()
    assert (dev_dir / "20260623T142233_02_collected_datasets.json").exists()


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

        def harmonize_datasets(self, datasets, harmonization_details_out=None):
            self.__class__.calls.append(
                (
                    "harmonize_datasets",
                    {
                        "datasets": datasets,
                        "harmonization_details_out": harmonization_details_out,
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
                "dev_out_dir": ".dev",
                    "dev_run_id": "20260623T142233",
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

        def harmonize_datasets(self, datasets, harmonization_details_out=None):
            return {**datasets, "harmonized": True}

    outfile = tmp_path / "atlas.json"

    RecordingAtlas(metadata={}).create_atlas(query=["a"], out=str(outfile))

    assert json.loads(outfile.read_text(encoding="utf-8")) == {
        "accessions": [{"datalink_id": "GSE1", "publication_text_ref": "1"}],
        "publication_texts": {"1": {"text": "full text"}},
        "harmonized": True,
    }


def test_create_atlas_writes_all_dev_snapshots_with_one_run_id(tmp_path) -> None:
    class LocalAtlas(Atlas):
        def _dev_run_id(self):
            return "20260623T142233"

    dev_dir = tmp_path / "debug"

    LocalAtlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
    ).create_atlas(query=["a"], dev_out_dir=str(dev_dir))

    assert sorted(path.name for path in dev_dir.iterdir()) == [
        "20260623T142233_01_collected_accessions.json",
        "20260623T142233_02_collected_datasets.json",
        "20260623T142233_03_harmonized_datasets.json",
    ]
    assert json.loads(
        (dev_dir / "20260623T142233_03_harmonized_datasets.json").read_text(
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
