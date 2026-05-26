from ThematicAtlases import ThematicAtlas, __version__


def test_package_exports_version() -> None:
    assert __version__ == "0.1.0"


def test_thematic_atlas_serializes_to_dict() -> None:
    atlas = ThematicAtlas(
        name="Fibrosis",
        description="Fibrosis-related transcriptomic datasets",
        metadata={"theme": "fibrosis"},
    )

    assert atlas.to_dict() == {
        "name": "Fibrosis",
        "description": "Fibrosis-related transcriptomic datasets",
        "metadata": {"theme": "fibrosis"},
    }


def test_thematic_atlas_metadata_defaults_are_independent() -> None:
    first = ThematicAtlas(name="First")
    second = ThematicAtlas(name="Second")

    first.metadata["key"] = "value"

    assert second.metadata == {}
