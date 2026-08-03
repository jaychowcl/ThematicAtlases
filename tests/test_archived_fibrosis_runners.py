from pathlib import Path

from benchmark_ThematicAtlases import ThematicReviewerBenchmark


ROOT = Path(__file__).resolve().parents[1]
ARCHIVED_RUNNERS = (
    "run_accession_metadata_collector.py",
    "run_fibrosis_atlas.py",
    "run_fibrosis_discovery.py",
    "run_publication_reviewer.py",
    "run_reference_publication_recall.py",
    "run_reference_set_review.py",
)


def test_noncanonical_fibrosis_runners_are_not_active_repository_interfaces() -> None:
    assert all(not (ROOT / runner).exists() for runner in ARCHIVED_RUNNERS)


def test_fibrosis_reference_assets_and_benchmark_data_remain_available() -> None:
    assert (ROOT / "docs" / "theme_fibrosis.txt").is_file()
    assert (ROOT / "config" / "fibrosis_discovery_queries.json").is_file()

    benchmark = ThematicReviewerBenchmark()
    assert benchmark.available_reference_sets() == (
        "leonie_2026_fibrosis",
        "taylor_2020_nafld_fibrosis",
    )
    assert len(
        benchmark.load_reference_set("leonie_2026_fibrosis")[
            "reference_publications"
        ]
    ) == 21
    assert len(
        benchmark.load_reference_set("taylor_2020_nafld_fibrosis")[
            "reference_publications"
        ]
    ) == 15


def test_documentation_routes_archived_runners_to_the_canonical_gsk_workflow() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "index.md").read_text(encoding="utf-8")
    codebase = (ROOT / "docs" / "codebase.md").read_text(encoding="utf-8")

    assert "Non-canonical fibrosis runners are archived locally" in readme
    assert "gsk_ThematicAtlases_adapter/scripts/create_fibrosis_atlas.py" in readme
    assert "Archived focused runner interfaces" in index
    assert '<a id="interface-focused-runners"></a>' in codebase
    assert '<a id="workflow-fixed-runners"></a>' in codebase
    assert "Archived non-canonical fibrosis runners" in codebase

    for runner in ARCHIVED_RUNNERS:
        assert f".env/bin/python {runner}" not in readme
        assert f".env/bin/python {runner}" not in codebase
