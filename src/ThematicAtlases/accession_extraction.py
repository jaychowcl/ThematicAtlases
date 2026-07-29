"""Deterministic accession discovery from publication full text."""

from __future__ import annotations

import re
from collections.abc import Callable


def _geo_object_type(accession: str) -> str:
    return {
        "GSE": "series",
        "GSM": "sample",
        "GPL": "platform",
        "GDS": "dataset",
    }[accession[:3]]


def _arrayexpress_object_type(accession: str) -> str:
    return "experiment" if accession.startswith("E-") else "array_design"


def _insdc_object_type(accession: str) -> str:
    return {
        "P": "study",
        "S": "sample",
        "X": "experiment",
        "R": "run",
        "Z": "analysis",
        "A": "submission",
    }[accession[2]]


_Pattern = tuple[
    re.Pattern[str],
    str,
    str,
    str | Callable[[str], str],
]


ACCESSION_PATTERNS: tuple[_Pattern, ...] = (
    (
        re.compile(r"(?<![A-Z0-9])(?:GSE|GSM|GPL|GDS)\d+(?![A-Z0-9])", re.I),
        "GEO",
        "geo",
        _geo_object_type,
    ),
    (
        re.compile(
            r"(?<![A-Z0-9])(?:E|A)-[A-Z0-9]+-\d+(?![A-Z0-9])",
            re.I,
        ),
        "ArrayExpress",
        "arrayexpress",
        _arrayexpress_object_type,
    ),
    (
        re.compile(
            r"(?<![A-Z0-9])S-[A-Z][A-Z0-9]{2,}(?:-?\d[A-Z0-9_-]*)(?![A-Z0-9])",
            re.I,
        ),
        "BioStudies",
        "biostudies",
        "study",
    ),
    (
        re.compile(r"(?<![A-Z0-9])PRJ(?:NA|EB|DB)\d+(?![A-Z0-9])", re.I),
        "BioProject",
        "bioproject",
        "project",
    ),
    (
        re.compile(r"(?<![A-Z0-9])[SED]R[PSXRAZ]\d+(?![A-Z0-9])", re.I),
        "INSDC",
        "insdc",
        _insdc_object_type,
    ),
    (
        re.compile(r"(?<![A-Z0-9])SAM(?:N|EA|D)\d+(?![A-Z0-9])", re.I),
        "BioSample",
        "biosample",
        "biosample",
    ),
)


def extract_accessions_from_text(text: str) -> list[dict[str, str]]:
    """Return normalized, ordered, unique accession matches."""

    matches: list[tuple[int, dict[str, str]]] = []
    seen: set[str] = set()
    for pattern, scheme, repository, object_type_factory in ACCESSION_PATTERNS:
        for match in pattern.finditer(str(text or "")):
            accession = match.group(0).upper()
            if accession in seen:
                continue
            seen.add(accession)
            object_type = (
                object_type_factory(accession)
                if callable(object_type_factory)
                else object_type_factory
            )
            matches.append(
                (
                    match.start(),
                    {
                        "accession": accession,
                        "datalink_id_scheme": scheme,
                        "datalink_category": scheme,
                        "repository": repository,
                        "object_type": object_type,
                    },
                )
            )
    return [item for _, item in sorted(matches, key=lambda pair: pair[0])]
