from ThematicAtlases.harmonizer import AtlasHarmonizer


def test_harmonize_jsons_preserves_placeholder_behavior() -> None:
    assert AtlasHarmonizer().harmonize_jsons() is None
