import importlib


def test_benchmark_package_is_importable_and_has_no_public_api() -> None:
    package = importlib.import_module("benchmark_ThematicAtlases")

    assert [name for name in vars(package) if not name.startswith("_")] == []
