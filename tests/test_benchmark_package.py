import importlib


def test_benchmark_package_exports_thematic_reviewer_benchmark() -> None:
    package = importlib.import_module("benchmark_ThematicAtlases")

    assert package.__all__ == ["ThematicReviewerBenchmark"]
    assert package.ThematicReviewerBenchmark.__name__ == "ThematicReviewerBenchmark"
