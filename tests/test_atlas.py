import json
import logging

from ThematicAtlases.atlas import Atlas


class RecordingCollector:
    calls: list[dict] = []

    def collect_jsons(self, query=None, file=None, out=None, metadata_repositories=None):
        self.__class__.calls.append(
            {
                "query": query,
                "file": file,
                "out": out,
                "metadata_repositories": metadata_repositories,
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


class RecordingHarmonizer:
    calls = 0

    def harmonize_jsons(self):
        self.__class__.calls += 1
        return [{"harmonized": True}]


def test_collect_jsons_delegates_to_collector() -> None:
    RecordingCollector.calls = []
    collector = RecordingCollector()

    assert Atlas(metadata={}, collector=collector).collect_jsons(
        query=["a"],
        file="queries.txt",
        out="collected.json",
    ) == [{"datalink_id": "GSE1", "publications": []}]
    assert RecordingCollector.calls == [
        {
            "query": ["a"],
            "file": "queries.txt",
            "out": "collected.json",
            "metadata_repositories": None,
        }
    ]


def test_collect_jsons_passes_metadata_repositories_to_collector() -> None:
    RecordingCollector.calls = []

    Atlas(metadata={}, collector=RecordingCollector()).collect_jsons(
        query=["a"],
        metadata_repositories=["geo", "arrayexpress"],
    )

    assert RecordingCollector.calls == [
        {
            "query": ["a"],
            "file": None,
            "out": None,
            "metadata_repositories": ["geo", "arrayexpress"],
        }
    ]


def test_filter_jsons_delegates_to_filterer() -> None:
    RecordingFilterer.calls = []
    filterer = RecordingFilterer()
    reviewer = object()

    assert Atlas(metadata={}, filterer=filterer).filter_jsons(
        jsons=[{"datalink_id": "GSE1"}],
        file="collected.json",
        theme="fibrosis",
        review_filter="not_relevant",
        reviewer=reviewer,
    ) == {
        "accessions": [{"datalink_id": "GSE1"}],
        "publication_texts": {},
    }
    assert RecordingFilterer.calls == [
        {
            "jsons": [{"datalink_id": "GSE1"}],
            "file": "collected.json",
            "theme": "fibrosis",
            "review_filter": "not_relevant",
            "reviewer": reviewer,
        }
    ]


def test_harmonize_jsons_delegates_to_harmonizer() -> None:
    RecordingHarmonizer.calls = 0

    assert Atlas(metadata={}, harmonizer=RecordingHarmonizer()).harmonize_jsons() == [
        {"harmonized": True}
    ]
    assert RecordingHarmonizer.calls == 1


def test_create_atlas_collects_then_filters_and_returns_final_object() -> None:
    RecordingCollector.calls = []
    RecordingFilterer.calls = []
    collector = RecordingCollector()
    filterer = RecordingFilterer()

    assert Atlas(metadata={}, collector=collector, filterer=filterer).create_atlas(
        query=["a"],
        file="queries.txt",
        theme="fibrosis",
        review_filter="none",
        metadata_repositories=["arrayexpress"],
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
        }
    ]
    assert RecordingFilterer.calls == [
        {
            "jsons": [{"datalink_id": "GSE1", "publications": []}],
            "file": None,
            "theme": "fibrosis",
            "review_filter": "none",
            "reviewer": None,
        }
    ]


def test_create_atlas_writes_final_filtered_object(tmp_path) -> None:
    class LocalFilterer(RecordingFilterer):
        def filter_jsons(self, **kwargs):
            return {
                "accessions": [{"datalink_id": "GSE1", "publication_text_ref": "1"}],
                "publication_texts": {"1": {"text": "full text"}},
            }

    outfile = tmp_path / "atlas.json"

    Atlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=LocalFilterer(),
    ).create_atlas(query=["a"], out=str(outfile))

    assert outfile.read_text(encoding="utf-8") == '{\n  "accessions": [\n    {\n      "datalink_id": "GSE1",\n      "publication_text_ref": "1"\n    }\n  ],\n  "publication_texts": {\n    "1": {\n      "text": "full text"\n    }\n  }\n}'


def test_create_atlas_logs_progress_and_stats(caplog) -> None:
    caplog.set_level(logging.INFO, logger="ThematicAtlases.atlas")

    Atlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
    ).create_atlas(query=["a"])

    assert "Atlas create_atlas progress stage=collect-jsons" in caplog.text
    assert "Atlas create_atlas progress stage=filter-jsons" in caplog.text
    assert "collected_accessions=1" in caplog.text
    assert "final_accessions=1" in caplog.text
    assert "publication_texts=0" in caplog.text
