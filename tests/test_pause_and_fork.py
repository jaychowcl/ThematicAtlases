import json

import pytest

from ThematicAtlases.atlas import Atlas
from ThematicAtlases.trace import DevTraceWriter


class RecordingCollectionAtlas(Atlas):
    def __init__(self, **kwargs):
        super().__init__(metadata={"atlas_id": "fibrosis"}, **kwargs)
        self.collection_calls = []

    def collect_datasets(self, **kwargs):
        self.collection_calls.append(kwargs)
        return {
            "accessions": [
                {
                    "datalink_id": "GSE1",
                    "metadata_repository": "geo",
                    "metadata_status": "available",
                    "accession_metadata": {"title": "fibrosis metadata"},
                    "publications": [
                        {
                            "pmid": "1",
                            "publication_text_ref": "PMID:1",
                        }
                    ],
                }
            ],
            "publication_texts": {
                "PMID:1": {"text": "fibrosis publication text"}
            },
        }


class NoHarmonizer:
    def harmonize_datasets(self, **kwargs):
        raise AssertionError("metadata pause must not harmonize")


def test_create_atlas_can_pause_after_metadata_as_resumable_collection(tmp_path):
    atlas = RecordingCollectionAtlas(harmonizer=NoHarmonizer())

    result = atlas.create_atlas(
        query=["fibrosis"],
        theme="human fibrosis",
        review_filter="not_relevant",
        generate_queries=False,
        collect_metadata=True,
        review_before_metadata=False,
        dev_trace=True,
        dev_out_dir=str(tmp_path),
        stop_after="metadata",
    )

    assert atlas.collection_calls[0]["collect_metadata"] is True
    assert atlas.collection_calls[0]["review_before_metadata"] is False
    assert atlas.collection_calls[0]["stop_before_review"] is True
    run_dir = next(path for path in tmp_path.iterdir() if path.is_dir())
    assert result["run"]["status"] == "running"
    assert (run_dir / "atlas_run.sqlite3").is_file()
    assert (run_dir / "collection_snapshot.json").is_file()
    assert (run_dir / "collection_snapshot.summary.json").is_file()
    assert not (run_dir / "02_reviewed_datasets.json").exists()
    assert not (run_dir / "06_final_atlas.json").exists()
    manifest = json.loads((run_dir / "00_run_manifest.json").read_text())
    assert manifest["command"] == "create-atlas"
    assert manifest["stop_after"] == "metadata"


@pytest.mark.parametrize(
    "options, message",
    [
        ({"stop_after": "review"}, "stop_after"),
        (
            {"stop_after": "metadata", "collect_metadata": False},
            "collect_metadata",
        ),
        (
            {"stop_after": "metadata", "review_before_metadata": True},
            "review_before_metadata",
        ),
        (
            {"stop_after": "metadata", "dev_trace": False},
            "dev_trace",
        ),
    ],
)
def test_create_atlas_rejects_invalid_metadata_pause_options(options, message):
    with pytest.raises(ValueError, match=message):
        Atlas(metadata={}).create_atlas(
            query=["fibrosis"],
            theme="human fibrosis",
            generate_queries=False,
            **options,
        )


def _paused_source(root, run_id="source"):
    manifest = {
        "command": "create-atlas",
        "atlas_id": "fibrosis",
        "created_at": run_id,
        "atlas_out": str(root / "fibrosis_atlas.json"),
        "query": ["fibrosis"],
        "query_file": None,
        "theme": "source theme",
        "review_filter": "not_relevant",
        "review_strategy": "direct",
        "prune_accessions": True,
        "metadata_repositories": ["geo", "arrayexpress"],
        "max_publications": None,
        "max_publications_per_query": [10000],
        "collect_metadata": True,
        "generate_queries": False,
        "review_before_metadata": False,
        "scrape_fulltext_accessions": True,
        "harmonization_options": {"target_checker": True},
        "stop_after": "metadata",
    }
    trace = DevTraceWriter(root=str(root), run_id=run_id, manifest=manifest)
    trace.checkpoint_store.validate_fingerprint(
        {
            "query": ["fibrosis"],
            "query_file": None,
            "theme": "source theme",
            "review_filter": "not_relevant",
            "metadata_repositories": ["geo", "arrayexpress"],
            "max_publications": None,
            "collect_metadata": True,
            "prune_accessions": True,
            "max_publications_per_query": [10000],
            "scrape_fulltext_accessions": True,
        }
    )
    trace.checkpoint_store.put(
        "geo_metadata",
        "GSE1",
        1,
        "available",
        payload={"accession_metadata": {"title": "downloaded once"}},
    )
    trace.write(
        "01_collected_accessions.json",
        [{"datalink_id": "GSE1", "accession_metadata": {"title": "downloaded once"}}],
    )
    trace.write(
        "resume_publication_collection.json",
        {"accessions": [], "publication_texts": {"PMID:1": {"text": "body"}}},
    )
    trace.run_store.set_stage_state(run_id, "collection", "complete")
    trace.run_store.set_run_status(run_id, "running")
    return trace.directory


def test_fork_run_clones_metadata_checkpoint_with_new_identity_and_overrides(tmp_path):
    source = _paused_source(tmp_path)

    forked = Atlas(metadata={}).fork_run(
        dev_out_dir=str(tmp_path),
        run_id=source.name,
        new_run_id="theme-b",
        overrides={
            "theme": "alternate fibrosis theme",
            "review_filter": "unsure",
            "harmonization_options": {"target_checker": False},
            "atlas_out": str(tmp_path / "branches" / "theme-b" / "atlas.json"),
        },
    )

    assert forked == tmp_path / "theme-b"
    manifest = json.loads((forked / "00_run_manifest.json").read_text())
    assert manifest["run_id"] == "theme-b"
    assert manifest["theme"] == "alternate fibrosis theme"
    assert manifest["forked_from"]["run_id"] == "source"
    assert (forked / "01_collected_accessions.json").is_file()
    assert not (forked / "02_reviewed_datasets.json").exists()
    assert not (forked / "06_final_atlas.json").exists()
    fork_trace = DevTraceWriter.existing(forked)
    assert fork_trace.run_store.get_run("theme-b") is not None
    assert fork_trace.run_store.get_run("source") is None
    assert fork_trace.checkpoint_store.get("geo_metadata", "GSE1")["status"] == "available"
    assert DevTraceWriter.existing(source).run_store.get_run("source") is not None


@pytest.mark.parametrize(
    "override",
    [
        {"query": ["different"]},
        {"metadata_repositories": ["geo"]},
        {"max_publications_per_query": [1]},
        {"collect_metadata": False},
        {"scrape_fulltext_accessions": False},
    ],
)
def test_fork_run_rejects_discovery_overrides(tmp_path, override):
    _paused_source(tmp_path)

    with pytest.raises(ValueError, match="downstream"):
        Atlas(metadata={}).fork_run(
            dev_out_dir=str(tmp_path),
            run_id="source",
            new_run_id="invalid-fork",
            overrides=override,
        )
