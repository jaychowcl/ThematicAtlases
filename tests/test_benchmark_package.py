import importlib

def test_benchmark_package_has_no_public_python_benchmark_api() -> None:
    package = importlib.import_module("benchmark_ThematicAtlases")

    assert package.__all__ == []
    assert not hasattr(package, "ThematicReviewerBenchmark")


def test_benchmark_subpackages_are_separate_import_namespaces() -> None:
    fibrosis_recall = importlib.import_module(
        "benchmark_ThematicAtlases.benchmark_fibrosis_meta_pubs_recall"
    )
    fibrosis_query_recall = importlib.import_module(
        "benchmark_ThematicAtlases.benchmark_fibrosis_meta_pubs_query_recall"
    )
    fibrosis_review = importlib.import_module(
        "benchmark_ThematicAtlases.benchmark_fibrosis_meta_pubs_review"
    )

    assert fibrosis_recall.__all__ == []
    assert fibrosis_query_recall.__all__ == []
    assert fibrosis_review.__all__ == []


def test_obsolete_benchmark_namespaces_are_removed() -> None:
    for module in (
        "benchmark_ThematicAtlases.ontology_harmonizer",
        "benchmark_ThematicAtlases.thematic_reviewer",
    ):
        try:
            importlib.import_module(module)
        except ModuleNotFoundError:
            continue
        raise AssertionError(f"obsolete benchmark namespace remains importable: {module}")
