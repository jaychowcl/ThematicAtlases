"""Internal outcomes; legacy facades retain their original mapping/tuple shapes."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RecordsResult:
    records: list[dict]


@dataclass(frozen=True)
class PublicationTextsResult:
    publication_texts: dict


@dataclass(frozen=True)
class ReviewResult:
    publication_text: dict
    reviewed: int
    reused: int
    failed: int

    def to_mapping(self) -> dict:
        return {'publication_text': self.publication_text, 'reviewed': self.reviewed,
                'reused': self.reused, 'failed': self.failed}


@dataclass(frozen=True)
class HarmonizationResult:
    datasets: dict
    details: list[dict]

    def as_pair(self) -> tuple[dict, list[dict]]:
        return self.datasets, self.details
