from ThematicAtlases.curator import ThematicReviewer


def test_thematic_reviewer_can_be_instantiated() -> None:
    assert isinstance(ThematicReviewer(), ThematicReviewer)
