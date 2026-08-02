from ThematicAtlases.filterer.filterer import AtlasFilterer
from ThematicAtlases.filterer.review import (
    ACCESSIONS,
    AGENTIC_CURATOR,
    PUBLICATIONS,
    PUBLICATION_TEXTS,
    PUBLICATION_TEXT_REF,
    REVIEW_FILTERS,
    PublicationTextReviewer,
)
from ThematicAtlases.collector import AtlasCollector
from ThematicAtlases.filterer.resume import configure_default_resume_factories


configure_default_resume_factories(
    collector_factory=AtlasCollector,
    filterer_factory=AtlasFilterer,
)

__all__ = [
    "ACCESSIONS",
    "AGENTIC_CURATOR",
    "AtlasFilterer",
    "PUBLICATIONS",
    "PUBLICATION_TEXTS",
    "PUBLICATION_TEXT_REF",
    "PublicationTextReviewer",
    "REVIEW_FILTERS",
]
