import importlib


def test_benchmark_package_exports_thematic_reviewer_benchmark() -> None:
    package = importlib.import_module("benchmark_ThematicAtlases")

    assert package.__all__ == ["ThematicReviewerBenchmark"]
    assert package.ThematicReviewerBenchmark.__name__ == "ThematicReviewerBenchmark"


def test_benchmark_subpackages_are_separate_import_namespaces() -> None:
    thematic_reviewer = importlib.import_module(
        "benchmark_ThematicAtlases.thematic_reviewer"
    )
    ontology_harmonizer = importlib.import_module(
        "benchmark_ThematicAtlases.ontology_harmonizer"
    )

    assert thematic_reviewer.__all__ == ["ThematicReviewerBenchmark"]
    assert ontology_harmonizer.__all__ == []
