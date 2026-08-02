import json
import logging

import pytest

from ThematicAtlases.atlas import Atlas
from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.document_adapter import AtlasDocumentAdapter
from ThematicAtlases.domain import AtlasDocument, RunStatus
from ThematicAtlases.run_store import AtlasRunStore


def initialize_run_store(run_dir, status="running"):
    manifest = json.loads((run_dir / "00_run_manifest.json").read_text())
    run_id = str(manifest.get("run_id") or run_dir.name)
    store = AtlasRunStore(run_dir / "atlas_run.sqlite3")
    store.create_run(run_id, f"atlas-{run_id}", "1.0", manifest)
    store.set_run_status(run_id, status)
    return store


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
        scrape_fulltext_accessions=True,
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

    def collect_accession_metadata(
        self,
        jsons,
        metadata_repositories=None,
        checkpoint_store=None,
    ):
        return list(jsons)


class RecordingFilterer:
    calls: list[dict] = []

    def filter_jsons(
        self,
        jsons=None,
        file=None,
        theme=None,
        review_filter="none",
        review_strategy="direct",
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


def test_create_atlas_requires_nonblank_theme_before_external_work() -> None:
    RecordingCollector.calls = []

    with pytest.raises(ValueError, match="create_atlas requires a non-empty theme"):
        Atlas(
            metadata={},
            collector=RecordingCollector(),
            harmonizer=RecordingHarmonizer(),
        ).create_atlas(theme=" ", generate_queries=False, query=["manual"])

    assert RecordingCollector.calls == []


def test_create_atlas_defaults_to_generated_queries_and_thematic_review() -> None:
    RecordingCollector.calls = []
    RecordingFilterer.calls = []
    RecordingQueryGenerator.calls = []

    result = Atlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
        harmonizer=RecordingHarmonizer(),
        query_generator=RecordingQueryGenerator(),
    ).create_atlas(theme="fibrosis")

    assert RecordingQueryGenerator.calls == [("fibrosis", 3)]
    assert RecordingFilterer.calls[0]["theme"] == "fibrosis"
    assert result["run"]["config"]["options"]["thematic_review"] is True


def test_create_atlas_without_generation_requires_a_query_before_collection() -> None:
    RecordingCollector.calls = []

    with pytest.raises(ValueError, match="requires at least one query"):
        Atlas(
            metadata={},
            collector=RecordingCollector(),
            harmonizer=RecordingHarmonizer(),
        ).create_atlas(theme="fibrosis", generate_queries=False)

    assert RecordingCollector.calls == []


def test_create_atlas_can_disable_thematic_review_without_review_llm_preflight() -> None:
    class UnexpectedCredentialChecker:
        def check(self):
            raise AssertionError("review credentials should not be checked")

    RecordingFilterer.calls = []
    Atlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
        harmonizer=RecordingHarmonizer(),
        credential_checker=UnexpectedCredentialChecker(),
    ).create_atlas(
        query=["manual"],
        theme="fibrosis",
        generate_queries=False,
        thematic_review=False,
    )

    assert RecordingFilterer.calls[0]["theme"] is None


@pytest.mark.parametrize(
    "options, message",
    [
        ({"review_filter": "not_relevant"}, "review_filter"),
        ({"review_before_metadata": True}, "review_before_metadata"),
    ],
)
def test_create_atlas_rejects_review_controls_when_thematic_review_is_disabled(
    options,
    message,
) -> None:
    with pytest.raises(ValueError, match=message):
        Atlas(metadata={}, harmonizer=RecordingHarmonizer()).create_atlas(
            query=["manual"],
            theme="fibrosis",
            generate_queries=False,
            thematic_review=False,
            **options,
        )


def test_collect_datasets_generates_queries_inside_atlas(tmp_path) -> None:
    query_file = tmp_path / "queries.txt"
    query_file.write_text("# ignored\nfile query\n", encoding="utf-8")
    RecordingCollector.calls = []
    RecordingQueryGenerator.calls = []

    result = Atlas(
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
    assert result["run"]["config"]["queries"] == [
        "explicit query",
        "file query",
        "generated one",
        "generated two",
    ]


def test_create_and_resume_preserve_resolved_generated_query_provenance(tmp_path) -> None:
    RecordingCollector.calls = []
    RecordingQueryGenerator.calls = []
    atlas = Atlas(
        metadata={"atlas_id": "atlas-generated"},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
        harmonizer=RecordingHarmonizer(),
        query_generator=RecordingQueryGenerator(),
    )

    created = atlas.create_atlas(
        query=["explicit query"],
        theme="fibrosis theme",
        generate_queries=True,
        max_generated_queries=2,
        collect_metadata=False,
        dev_trace=True,
        dev_out_dir=str(tmp_path),
    )
    run_id = created["run"]["run_id"]
    resumed = atlas.resume(dev_out_dir=str(tmp_path), run_id=run_id)

    expected = ["explicit query", "generated one", "generated two"]
    assert created["run"]["config"]["queries"] == expected
    assert resumed["run"]["config"]["queries"] == expected
    assert resumed == created


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


def test_generated_queries_are_checkpointed(tmp_path) -> None:
    Atlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
        query_generator=RecordingQueryGenerator(),
    ).collect_datasets(
        theme="fibrosis",
        generate_queries=True,
        dev_trace=True,
        dev_out_dir=str(tmp_path),
        run_id="query-checkpoint",
    )

    store = CheckpointStore(
        tmp_path / "query-checkpoint" / "atlas_run.sqlite3"
    )
    items = store.items("query_generation")
    assert len(items) == 1
    assert items[0]["status"] == "available"
    assert items[0]["payload"]["queries"]


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

    atlas.create_atlas(query=["a"], theme="theme", generate_queries=False)
    atlas.create_atlas(query=["a"], theme="theme", generate_queries=False)

    assert events == ["cache", "collect", "collect"]


def test_create_atlas_preflights_credentials_before_semantic_cache() -> None:
    events = []

    class RecordingChecker:
        def check(self):
            events.append("credentials")

    class RecordingStore:
        def cache_all(self):
            events.append("cache")
            return {"successful": ["efo"], "failed": []}

    Atlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
        ontostore=RecordingStore(),
        cache_ontologies=True,
        credential_checker=RecordingChecker(),
    ).create_atlas(query=["a"], theme="theme", generate_queries=False)

    assert events[:2] == ["credentials", "cache"]


def test_create_atlas_does_not_cache_ontologies_by_default() -> None:
    class UnexpectedStore:
        def cache_all(self):
            raise AssertionError("cache_all should be opt-in")

    Atlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
        ontostore=UnexpectedStore(),
    ).create_atlas(query=["a"], theme="theme", generate_queries=False)


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
        ).create_atlas(query=["a"], theme="theme", generate_queries=False)


def test_atlas_rejects_managed_ontostore_with_custom_harmonizer() -> None:
    with pytest.raises(ValueError, match="custom harmonizer"):
        Atlas(metadata={}, harmonizer=object(), ontostore=object())

def test_collect_datasets_collects_then_filters_and_returns_atlas_object() -> None:
    RecordingCollector.calls = []
    RecordingFilterer.calls = []
    collector = RecordingCollector()
    filterer = RecordingFilterer()
    reviewer = object()

    result = Atlas(metadata={}, collector=collector, filterer=filterer).collect_datasets(
        query=["a"],
        file="queries.txt",
        theme="fibrosis",
        review_filter="not_relevant",
        metadata_repositories=["arrayexpress"],
        max_publications=25,
        reviewer=reviewer,
        collect_metadata=False,
    )
    document = AtlasDocument.from_mapping(result)
    assert [item.dataset_id for item in document.datasets] == ["GSE1"]
    assert document.atlas.theme == "fibrosis"
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

    document = AtlasDocument.load(outfile)
    assert document.schema_version == "1.0"
    assert [item.dataset_id for item in document.datasets] == ["GSE1"]
    assert [item.publication_id for item in document.publications] == ["1"]


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

    legacy = {"accessions": [{"datalink_id": "GSE1"}], "publication_texts": {}}
    datasets = AtlasDocumentAdapter().assemble(
        legacy,
        atlas_metadata={},
        run_id="run-1",
        created_at="2026-07-31T00:00:00Z",
        theme="",
        config={},
        run_status=RunStatus.RUNNING,
    ).to_mapping()
    harmonizer = RecordingHarmonizer()

    result = Atlas(metadata={}, harmonizer=harmonizer).harmonize_datasets(
        datasets=datasets,
        harmonization_details_out="details.json",
        harmonization_options={"ols_lookup_judge": False},
    )
    assert AtlasDocument.from_mapping(result).run.status == RunStatus.COMPLETE
    assert RecordingHarmonizer.calls[0][1:] == (
        "details.json",
        {"ols_lookup_judge": False},
    )
    assert RecordingHarmonizer.calls[0][0]["accessions"][0]["datalink_id"] == "GSE1"


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

    result = RecordingAtlas(metadata={}).create_atlas(
        query=["a"],
        file="queries.txt",
        theme="fibrosis",
        review_filter="none",
        metadata_repositories=["arrayexpress"],
        max_publications=25,
        collect_metadata=False,
        harmonization_details_out="harmonization.json",
        generate_queries=False,
    )
    document = AtlasDocument.from_mapping(result)
    assert document.run.run_id == "20260623T142233"
    assert [item.dataset_id for item in document.datasets] == ["GSE1"]
    assert RecordingAtlas.calls == [
        (
            "collect_datasets",
            {
                "query": ["a"],
                "file": "queries.txt",
                "out": None,
                "theme": "fibrosis",
                    "review_filter": "none",
                    "review_strategy": "direct",
                    "metadata_repositories": ["arrayexpress"],
                "max_publications": 25,
                "reviewer": None,
                "collect_metadata": False,
                    "generate_queries": False,
                    "max_generated_queries": 3,
                    "review_before_metadata": False,
                    "scrape_fulltext_accessions": True,
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

    RecordingAtlas(metadata={}).create_atlas(
        query=["a"],
        theme="theme",
        generate_queries=False,
        out=str(outfile),
    )

    document = AtlasDocument.load(outfile)
    assert [item.dataset_id for item in document.datasets] == ["GSE1"]
    assert [item.publication_id for item in document.publications] == ["1"]
    summary = json.loads((tmp_path / "atlas.summary.json").read_text(encoding="utf-8"))
    assert summary["dataset_count"] == 1
    assert summary["publication_count"] == 1


def test_create_atlas_without_output_or_trace_writes_no_files(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)

    Atlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
    ).create_atlas(query=["a"], theme="theme", generate_queries=False)

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
    ).create_atlas(
        query=["a"],
        theme="theme",
        generate_queries=False,
        dev_trace=True,
        dev_out_dir=str(dev_dir),
    )

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
        "atlas_run.sqlite3",
        "unsupported_accessions.json",
    ]
    document = AtlasDocument.load(run_dir / "06_final_atlas.json")
    assert [item.dataset_id for item in document.datasets] == ["GSE1"]


def test_create_atlas_logs_progress_and_stats(caplog) -> None:
    caplog.set_level(logging.INFO, logger="ThematicAtlases.atlas")

    Atlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
    ).create_atlas(query=["a"], theme="theme", generate_queries=False)

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
    initialize_run_store(run_dir)
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

    assert AtlasDocument.from_mapping(result).datasets[0].dataset_id == "GSE1"
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
        initialize_run_store(run_dir)
        (run_dir / "02_reviewed_datasets.json").write_text(
            json.dumps({"accessions": [{"datalink_id": run_id}], "publication_texts": {}}),
            encoding="utf-8",
        )
    completed = root / "20260712T120000"
    completed.mkdir()
    (completed / "00_run_manifest.json").write_text(
        json.dumps({"run_id": "20260712T120000"}), encoding="utf-8"
    )
    initialize_run_store(completed, status="complete")
    (completed / "06_final_atlas.json").write_text(
        json.dumps({"accessions": [], "publication_texts": {}}), encoding="utf-8"
    )

    result = Atlas(
        metadata={}, collector=RecordingCollector(), filterer=RecordingFilterer(), harmonizer=RecordingHarmonizer()
    ).resume(dev_out_dir=str(root))

    assert AtlasDocument.from_mapping(result).datasets[0].dataset_id == "20260712T110000"


def test_collect_datasets_traces_incremental_review_progress(tmp_path) -> None:
    class ProgressFilterer(RecordingFilterer):
        def filter_jsons(self, jsons=None, _review_progress_callback=None, **kwargs):
            _review_progress_callback({"1": {"text": "reviewed"}})
            return {"accessions": list(jsons or []), "publication_texts": {}}

        def accessions_with_publication_text_refs(self, accessions, publication_texts):
            return accessions

    from ThematicAtlases.trace import DevTraceWriter
    trace = DevTraceWriter(str(tmp_path), "run", {})
    Atlas(metadata={}, collector=RecordingCollector(), filterer=ProgressFilterer()).collect_datasets(
        query=["fibrosis"], _trace_writer=trace
    )
    progress = json.loads((tmp_path / "run" / "resume_review_progress.json").read_text())
    assert progress["publication_texts"] == {"1": {"text": "reviewed"}}


def test_collect_datasets_can_own_resumable_discovery_trace(tmp_path) -> None:
    result = Atlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
    ).collect_datasets(
        query=["fibrosis"],
        dev_trace=True,
        dev_out_dir=str(tmp_path),
        run_id="discovery-run",
    )

    run_dir = tmp_path / "discovery-run"
    manifest = json.loads((run_dir / "00_run_manifest.json").read_text())
    assert manifest["command"] == "collect-datasets"
    assert (run_dir / "atlas_run.sqlite3").exists()
    assert not (run_dir / "resume_state.sqlite").exists()
    assert json.loads((run_dir / "collection_snapshot.json").read_text()) == result
    assert not (run_dir / "06_final_atlas.json").exists()


def test_amend_queries_archives_manifest_and_updates_resumable_configuration(
    tmp_path,
) -> None:
    from ThematicAtlases.trace import DevTraceWriter

    trace = DevTraceWriter(
        str(tmp_path),
        "run-1",
        {
            "command": "collect-datasets",
            "query": ["old"],
            "query_file": None,
            "max_publications": 5000,
        },
    )
    trace.checkpoint_store.validate_fingerprint(
        {"query": ["old"], "query_file": None, "max_publications": 5000}
    )

    archive = Atlas(metadata={}).amend_queries(
        dev_out_dir=str(tmp_path),
        run_id="run-1",
        queries=["old", "expanded"],
        max_publications_per_query=[5000, 15000],
    )

    manifest = json.loads(
        (tmp_path / "run-1" / "00_run_manifest.json").read_text()
    )
    assert manifest["query"] == ["old", "expanded"]
    assert manifest["max_publications"] is None
    assert manifest["max_publications_per_query"] == [5000, 15000]
    archived_manifest = json.loads((archive / "00_run_manifest.json").read_text())
    assert archived_manifest["previous_manifest"]["query"] == ["old"]
    trace.checkpoint_store.validate_fingerprint(
        {
            "query": ["old", "expanded"],
            "query_file": None,
            "max_publications": None,
            "max_publications_per_query": [5000, 15000],
        }
    )


def test_amend_queries_preserves_existing_whitespace_equivalent_configuration(
    tmp_path,
) -> None:
    from ThematicAtlases.trace import DevTraceWriter

    trace = DevTraceWriter(
        str(tmp_path),
        "run-1",
        {
            "command": "collect-datasets",
            "query": ["TITLE_ABS:(fibrosis\n OR fibrotic)"],
            "query_file": None,
            "max_publications": None,
            "max_publications_per_query": [5000],
        },
    )
    original = {
        "query": ["TITLE_ABS:(fibrosis\n OR fibrotic)"],
        "query_file": None,
        "max_publications": None,
        "max_publications_per_query": [5000],
    }
    trace.checkpoint_store.validate_fingerprint(original)

    Atlas(metadata={}).amend_queries(
        dev_out_dir=str(tmp_path),
        run_id="run-1",
        queries=["TITLE_ABS:(fibrosis OR fibrotic)"],
        max_publications_per_query=[5000],
    )

    assert trace.checkpoint_store.get_meta("run_fingerprint")["configuration"] == original
    assert trace.checkpoint_store.get_meta("run_configuration_amendments") is None


def test_resume_discovery_trace_stops_before_harmonization(tmp_path) -> None:
    run_dir = tmp_path / "trace" / "discovery-run"
    run_dir.mkdir(parents=True)
    (run_dir / "00_run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "discovery-run",
                "command": "collect-datasets",
                "query": ["fibrosis"],
                "theme": None,
                "review_filter": "none",
            }
        ),
        encoding="utf-8",
    )
    initialize_run_store(run_dir)
    (run_dir / "01_collected_accessions.json").write_text(
        json.dumps([{"datalink_id": "GSE1", "publications": []}]),
        encoding="utf-8",
    )

    class NoHarmonizer:
        def harmonize_datasets(self, **kwargs):
            raise AssertionError("discovery resume must not harmonize")

    result = Atlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
        harmonizer=NoHarmonizer(),
    ).resume(dev_out_dir=str(tmp_path / "trace"))

    assert AtlasDocument.from_mapping(result).datasets[0].dataset_id == "GSE1"
    assert (run_dir / "collection_snapshot.json").exists()
    assert not (run_dir / "06_final_atlas.json").exists()


def test_create_atlas_passes_checkpoint_store_to_harmonizer(tmp_path) -> None:
    calls = []

    class CheckpointHarmonizer:
        def harmonize_datasets(
            self,
            datasets,
            details_out=None,
            harmonization_options=None,
            checkpoint_store=None,
        ):
            calls.append(checkpoint_store)
            return datasets, []

    Atlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
        harmonizer=CheckpointHarmonizer(),
    ).create_atlas(
        query=["fibrosis"],
        theme="fibrosis",
        generate_queries=False,
        dev_trace=True,
        dev_out_dir=str(tmp_path),
    )

    assert calls and calls[0] is not None


def test_resume_retries_harmonization_marked_retryable_in_sqlite(tmp_path) -> None:
    from ThematicAtlases.checkpoint import CheckpointStore

    run_dir = tmp_path / "trace" / "retry-harmonization"
    run_dir.mkdir(parents=True)
    (run_dir / "00_run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "retry-harmonization",
                "command": "create-atlas",
                "theme": None,
                "review_filter": "none",
                "harmonization_options": {},
            }
        ),
        encoding="utf-8",
    )
    initialize_run_store(run_dir)
    datasets = {
        "accessions": [{"datalink_id": "GSE1", "accession_metadata": {"x": 1}}],
        "publication_texts": {},
    }
    (run_dir / "02_reviewed_datasets.json").write_text(
        json.dumps(datasets), encoding="utf-8"
    )
    (run_dir / "resume_harmonized_datasets.json").write_text(
        json.dumps({**datasets, "stale": True}), encoding="utf-8"
    )
    CheckpointStore(run_dir / "atlas_run.sqlite3").put(
        "harmonization",
        "work-key",
        1,
        "retryable_error",
        error="temporary timeout",
    )
    calls = []

    class RetryHarmonizer:
        def harmonize_datasets(
            self,
            datasets,
            details_out=None,
            harmonization_options=None,
            checkpoint_store=None,
        ):
            calls.append(datasets)
            return {**datasets, "retried": True}, []

    result = Atlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
        harmonizer=RetryHarmonizer(),
    ).resume(dev_out_dir=str(tmp_path / "trace"))

    assert calls == [datasets]
    assert AtlasDocument.from_mapping(result).datasets[0].dataset_id == "GSE1"
    assert "stale" not in result


def test_resume_ignores_final_output_when_collection_has_retryable_item(
    tmp_path,
) -> None:
    from ThematicAtlases.checkpoint import CheckpointStore

    run_dir = tmp_path / "trace" / "retry-collection"
    run_dir.mkdir(parents=True)
    (run_dir / "00_run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "retry-collection",
                "command": "collect-datasets",
                "query": ["fibrosis"],
                "theme": None,
                "review_filter": "none",
            }
        ),
        encoding="utf-8",
    )
    initialize_run_store(run_dir)
    stale = {"accessions": [{"datalink_id": "STALE"}], "publication_texts": {}}
    (run_dir / "06_final_atlas.json").write_text(
        json.dumps(stale), encoding="utf-8"
    )
    store = CheckpointStore(run_dir / "atlas_run.sqlite3")
    store.put(
        "geo_metadata",
        "GSE1",
        1,
        "retryable_error",
        error="temporary timeout",
    )
    calls = []

    class RecoveringCollector:
        def collect_jsons(self, checkpoint_store=None, **kwargs):
            calls.append(kwargs)
            checkpoint_store.put(
                "geo_metadata",
                "GSE1",
                1,
                "available",
                payload={"records": []},
            )
            return [{"datalink_id": "GSE1", "publications": []}]

    result = Atlas(
        metadata={},
        collector=RecoveringCollector(),
        filterer=RecordingFilterer(),
    ).resume(dev_out_dir=str(tmp_path / "trace"), run_id="retry-collection")

    assert len(calls) == 1
    assert AtlasDocument.from_mapping(result).datasets[0].dataset_id == "GSE1"


@pytest.mark.parametrize("stage", ["pubmed_enrichment", "sra_xml", "ena_fastq"])
def test_resume_ignores_final_output_for_retryable_enrichment_stage(tmp_path, stage) -> None:
    from ThematicAtlases.checkpoint import CheckpointStore

    run_dir = tmp_path / "trace" / f"retry-{stage}"
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": run_dir.name,
        "query": ["fibrosis"],
        "collect_metadata": True,
        "metadata_repositories": ["geo"],
        "review_filter": "none",
        "review_strategy": "direct",
        "generate_queries": False,
        "max_generated_queries": 3,
        "review_before_metadata": False,
    }
    (run_dir / "00_run_manifest.json").write_text(json.dumps(manifest))
    initialize_run_store(run_dir)
    (run_dir / "06_final_atlas.json").write_text(json.dumps({"accessions": [{"final": True}]}))
    (run_dir / "01_collected_accessions.json").write_text(json.dumps({"accessions": []}))
    store = CheckpointStore(run_dir / "atlas_run.sqlite3")
    store.put(stage, "item", 1, "retryable_error", error="timeout")

    class RecordingCollector:
        def collect_jsons(self, checkpoint_store=None, **kwargs):
            checkpoint_store.put(stage, "item", 1, "available", payload={})
            return [{"datalink_id": "GSE1", "publications": []}]

    atlas = Atlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
    )
    result = atlas.resume(dev_out_dir=str(tmp_path / "trace"), run_id=run_dir.name)

    assert result != {"accessions": [{"final": True}]}

def test_collect_datasets_can_review_before_collecting_metadata() -> None:
    events = []
    raw = [
        {
            "datalink_id": "GSE_KEEP",
            "publications": [{"publication_text_ref": "keep"}],
        },
        {
            "datalink_id": "GSE_DROP",
            "publications": [{"publication_text_ref": "drop"}],
        },
    ]

    class StrategyCollector:
        def collect_jsons(self, collect_metadata=True, **kwargs):
            events.append(("discover", collect_metadata))
            return raw

        def collect_accession_metadata(self, jsons, **kwargs):
            events.append(("metadata", [item["datalink_id"] for item in jsons]))
            return [
                {
                    **jsons[0],
                    "metadata_status": "available",
                    "accession_metadata": {"series": {"title": "kept"}},
                }
            ]

    class StrategyFilterer:
        def filter_jsons(self, jsons=None, **kwargs):
            assert all("accession_metadata" not in item for item in jsons)
            events.append(("review", [item["datalink_id"] for item in jsons]))
            return {
                "accessions": [jsons[0]],
                "publication_texts": {
                    "keep": {"text": "relevant"},
                    "drop": {"text": "not relevant"},
                },
            }

    result = Atlas(
        metadata={},
        collector=StrategyCollector(),
        filterer=StrategyFilterer(),
    ).collect_datasets(
        query=["fibrosis"],
        theme="fibrosis theme",
        review_filter="not_relevant",
        review_before_metadata=True,
    )

    assert events == [
        ("discover", False),
        ("review", ["GSE_KEEP", "GSE_DROP"]),
        ("metadata", ["GSE_KEEP"]),
    ]
    document = AtlasDocument.from_mapping(result)
    assert document.datasets[0].metadata == {"series": {"title": "kept"}}
    assert [item.publication_id for item in document.publications] == ["keep"]


def test_collect_datasets_can_stop_after_publication_text_before_review(tmp_path) -> None:
    events = []
    raw = [{"datalink_id": "GSE1", "publications": [{"pmid": "1"}]}]

    class CollectionOnlyCollector:
        def collect_jsons(self, collect_metadata=True, **kwargs):
            events.append(("collect", collect_metadata))
            return raw

        def collect_accession_metadata(self, **kwargs):
            raise AssertionError("metadata must remain deferred")

    class PublicationTextOnlyFilterer:
        def filter_jsons(self, jsons=None, theme=None, review_filter=None, **kwargs):
            events.append(("publication_text", theme, review_filter))
            assert jsons == raw
            return {
                "accessions": [
                    {
                        **raw[0],
                        "publications": [
                            {**raw[0]["publications"][0], "publication_text_ref": "1"}
                        ],
                    }
                ],
                "publication_texts": {"1": {"text": "publication body"}},
            }

        def accessions_with_publication_text_refs(self, accessions, publication_texts):
            return accessions

    class NoCredentials:
        def check(self):
            raise AssertionError("static collection-only mode must not preflight LLM credentials")

    result = Atlas(
        metadata={},
        collector=CollectionOnlyCollector(),
        filterer=PublicationTextOnlyFilterer(),
        credential_checker=NoCredentials(),
    ).collect_datasets(
        query=["fibrosis"],
        theme="fibrosis theme",
        review_filter="not_relevant",
        review_before_metadata=True,
        stop_before_review=True,
        dev_trace=True,
        dev_out_dir=str(tmp_path),
        run_id="collection-only",
    )

    assert events == [("collect", False), ("publication_text", None, "none")]
    document = AtlasDocument.from_mapping(result)
    assert [item.publication_id for item in document.publications] == ["1"]
    run_dir = tmp_path / "collection-only"
    manifest = json.loads((run_dir / "00_run_manifest.json").read_text())
    assert manifest["stop_before_review"] is True
    assert json.loads((run_dir / "resume_publication_collection.json").read_text())["publication_texts"]["1"]["text"] == "publication body"
    assert not (run_dir / "02_reviewed_datasets.json").exists()
    assert not (run_dir / "resume_metadata_enriched_datasets.json").exists()
    assert AtlasDocument.load(run_dir / "collection_snapshot.json") == document
    assert not (run_dir / "06_final_atlas.json").exists()


def test_resume_can_override_old_trace_to_stop_before_review(tmp_path) -> None:
    from ThematicAtlases.checkpoint import CheckpointStore

    run_dir = tmp_path / "trace" / "existing"
    run_dir.mkdir(parents=True)
    (run_dir / "00_run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "existing",
                "command": "collect-datasets",
                "query": ["fibrosis"],
                "theme": "fibrosis theme",
                "review_filter": "not_relevant",
                "review_before_metadata": True,
                "collect_metadata": True,
            }
        ),
        encoding="utf-8",
    )
    initialize_run_store(run_dir)
    store = CheckpointStore(run_dir / "atlas_run.sqlite3")
    store.put(
        "thematic_review",
        "direct:1",
        1,
        "available",
        payload={"publication_text": {"agentic_curator": {"judgement": "relevant"}}},
    )
    before = store.get("thematic_review", "direct:1")

    class ResumeCollector:
        def collect_jsons(self, collect_metadata=True, checkpoint_store=None, **kwargs):
            assert collect_metadata is False
            assert checkpoint_store is not None
            return [{"datalink_id": "GSE1", "publications": [{"pmid": "1"}]}]

    class ResumeFilterer:
        def filter_jsons(self, jsons=None, theme=None, review_filter=None, **kwargs):
            assert theme is None
            assert review_filter == "none"
            return {"accessions": list(jsons), "publication_texts": {"1": {"text": "body"}}}

        def accessions_with_publication_text_refs(self, accessions, publication_texts):
            return accessions

    class NoCredentials:
        def check(self):
            raise AssertionError("collection-only resume must not preflight LLM credentials")

    result = Atlas(
        metadata={},
        collector=ResumeCollector(),
        filterer=ResumeFilterer(),
        credential_checker=NoCredentials(),
    ).resume(
        dev_out_dir=str(tmp_path / "trace"),
        run_id="existing",
        stop_before_review=True,
    )

    assert [
        item.publication_id
        for item in AtlasDocument.from_mapping(result).publications
    ] == ["PMID:1"]
    assert store.get("thematic_review", "direct:1") == before
    assert (run_dir / "resume_publication_collection.json").exists()
    assert not (run_dir / "02_reviewed_datasets.json").exists()


def test_review_before_metadata_requires_theme() -> None:
    with pytest.raises(ValueError, match="requires a theme"):
        Atlas(metadata={}).collect_datasets(
            query=["fibrosis"],
            review_before_metadata=True,
        )


def test_review_before_metadata_trace_writes_enriched_checkpoint(tmp_path) -> None:
    class LocalAtlas(Atlas):
        def _dev_run_id(self):
            return "review-first"

    LocalAtlas(
        metadata={},
        collector=RecordingCollector(),
        filterer=RecordingFilterer(),
    ).collect_datasets(
        query=["fibrosis"],
        theme="fibrosis",
        review_before_metadata=True,
        dev_trace=True,
        dev_out_dir=str(tmp_path),
    )

    run_dir = tmp_path / "review-first"
    manifest = json.loads((run_dir / "00_run_manifest.json").read_text())
    assert manifest["review_before_metadata"] is True
    assert (run_dir / "resume_metadata_enriched_datasets.json").exists()


def test_resume_review_first_trace_enriches_reviewed_survivors_only(tmp_path) -> None:
    run_dir = tmp_path / "trace" / "review-first"
    run_dir.mkdir(parents=True)
    (run_dir / "00_run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "review-first",
                "command": "collect-datasets",
                "theme": "fibrosis",
                "review_filter": "not_relevant",
                "review_before_metadata": True,
                "collect_metadata": True,
                "metadata_repositories": ["geo"],
            }
        ),
        encoding="utf-8",
    )
    initialize_run_store(run_dir)
    reviewed = {
        "accessions": [
            {
                "datalink_id": "GSE_KEEP",
                "publications": [{"publication_text_ref": "1"}],
            }
        ],
        "publication_texts": {"1": {"text": "relevant"}},
    }
    (run_dir / "02_reviewed_datasets.json").write_text(
        json.dumps(reviewed), encoding="utf-8"
    )
    calls = []

    class ResumeCollector:
        def collect_jsons(self, **kwargs):
            raise AssertionError("discovery must not rerun")

        def collect_accession_metadata(self, jsons, **kwargs):
            calls.append(jsons)
            return [{**jsons[0], "metadata_status": "available"}]

    class NoReviewFilterer:
        def filter_jsons(self, **kwargs):
            raise AssertionError("review must not rerun")

    result = Atlas(
        metadata={},
        collector=ResumeCollector(),
        filterer=NoReviewFilterer(),
    ).resume(dev_out_dir=str(tmp_path / "trace"), run_id="review-first")

    assert calls == [reviewed["accessions"]]
    document = AtlasDocument.from_mapping(result)
    assert document.datasets[0].dataset_id == "GSE_KEEP"
    assert [item.publication_id for item in document.publications] == ["1"]
    assert (run_dir / "resume_metadata_enriched_datasets.json").exists()
