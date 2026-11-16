"""TA-owned configuration of AC's existing overridable criterion limit."""

from agentic_curator import ThematicReviewer


def configured_reviewer(*, max_review_criteria=12, factory=None, cancelled=None):
    from ThematicAtlases.filterer.review import validate_max_review_criteria

    limit = validate_max_review_criteria(max_review_criteria)
    reviewer = factory() if factory is not None else ThematicReviewer(cancelled=cancelled)
    # Only fresh, TA-owned AC instances are configured here. Caller-injected
    # reviewers are checked by PublicationTextReviewer without mutation.
    if isinstance(reviewer, ThematicReviewer):
        reviewer.MAX_CRITERIA = limit
    return reviewer
