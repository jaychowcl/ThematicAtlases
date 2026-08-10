import importlib

def test_benchmark_package_has_no_public_python_benchmark_api() -> None:
    package = importlib.import_module("benchmark_ThematicAtlases")

    assert package.__all__ == []
    assert not hasattr(package, "ThematicReviewerBenchmark")


def test_benchmark_subpackages_are_separate_import_namespaces() -> None:
    fibrosis_recall = importlib.import_module(
        "benchmark_ThematicAtlases.benchmark_fibrosis_meta_pubs_recall"
    )
    ontology_harmonizer = importlib.import_module(
        "benchmark_ThematicAtlases.ontology_harmonizer"
    )

    assert fibrosis_recall.__all__ == []
    assert ontology_harmonizer.__all__ == []
