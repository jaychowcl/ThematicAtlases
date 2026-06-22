import json
import logging

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


def test_harmonize_datasets_returns_input_object() -> None:
    datasets = {"accessions": [{"datalink_id": "GSE1"}], "publication_texts": {}}

    assert Atlas(metadata={}).harmonize_datasets(datasets=datasets) is datasets


def test_create_atlas_collects_then_harmonizes_and_returns_final_object() -> None:
    class RecordingAtlas(Atlas):
        calls: list[tuple[str, dict]] = []

        def collect_datasets(self, **kwargs):
            self.__class__.calls.append(("collect_datasets", kwargs))
            return {"accessions": [{"datalink_id": "GSE1"}], "publication_texts": {}}

        def harmonize_datasets(self, datasets):
            self.__class__.calls.append(("harmonize_datasets", {"datasets": datasets}))
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
            },
        ),
        (
            "harmonize_datasets",
            {
                "datasets": {
                    "accessions": [{"datalink_id": "GSE1"}],
                    "publication_texts": {},
                }
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

        def harmonize_datasets(self, datasets):
            return {**datasets, "harmonized": True}

    outfile = tmp_path / "atlas.json"

    RecordingAtlas(metadata={}).create_atlas(query=["a"], out=str(outfile))

    assert json.loads(outfile.read_text(encoding="utf-8")) == {
        "accessions": [{"datalink_id": "GSE1", "publication_text_ref": "1"}],
        "publication_texts": {"1": {"text": "full text"}},
        "harmonized": True,
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
