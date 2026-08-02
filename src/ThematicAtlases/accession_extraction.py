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
    (
        re.compile(r"(?<![A-Z0-9])EGA[SD]\d{11}(?![A-Z0-9])", re.I),
        "EGA",
        "ega",
        lambda accession: "study" if accession.startswith("EGAS") else "dataset",
    ),
    (
        re.compile(
            r"(?<![A-Z0-9])PHS\d{6,}(?:\.V\d+\.P\d+)?(?![A-Z0-9])",
            re.I,
        ),
        "dbGaP",
        "dbgap",
        "study",
    ),
    (
        re.compile(r"(?<![A-Z0-9])SCP\d+(?![A-Z0-9])", re.I),
        "SingleCellPortal",
        "single_cell_portal",
        "study",
    ),
    (
        re.compile(r"(?<![A-Z0-9])SYN\d+(?![A-Z0-9])", re.I),
        "Synapse",
        "synapse",
        "dataset",
    ),
    (
        re.compile(r"(?<![A-Z0-9])PXD\d{6,}(?![A-Z0-9])", re.I),
        "PRIDE",
        "pride",
        "dataset",
    ),
    (
        re.compile(r"(?<![A-Z0-9])MTBLS\d+(?![A-Z0-9])", re.I),
        "MetaboLights",
        "metabolights",
        "study",
    ),
    (
        re.compile(r"(?<![A-Z0-9])SDY\d+(?![A-Z0-9])", re.I),
        "ImmPort",
        "immport",
        "study",
    ),
    (
        re.compile(r"(?<![A-Z0-9])(?:PRJCA|CRA|HRA)\d+(?![A-Z0-9])", re.I),
        "NGDC",
        "ngdc",
        lambda accession: "project"
        if accession.startswith("PRJCA")
        else "archive",
    ),
)


_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_LINK_PATTERNS: tuple[
    tuple[re.Pattern[str], str, str, str, Callable[[re.Match[str]], str]], ...
] = (
    (
        re.compile(rf"https?://cellxgene\.cziscience\.com/collections/({_UUID})", re.I),
        "CELLxGENE",
        "cellxgene",
        "collection",
        lambda match: f"CELLXGENE-COLLECTION:{match.group(1).upper()}",
    ),
    (
        re.compile(rf"https?://cellxgene\.cziscience\.com/e/({_UUID})\.cxg(?:/|$)", re.I),
        "CELLxGENE",
        "cellxgene",
        "dataset",
        lambda match: f"CELLXGENE-DATASET:{match.group(1).upper()}",
    ),
    (
        re.compile(
            r"(?:https?://(?:www\.)?zenodo\.org/(?:record|records)/|"
            r"https?://doi\.org/10\.5281/zenodo\.)(\d+)",
            re.I,
        ),
        "Zenodo",
        "zenodo",
        "record",
        lambda match: f"ZENODO:{match.group(1)}",
    ),
    (
        re.compile(
            r"(?:https?://doi\.org/)?10\.6084/m9\.figshare\.(\d+(?:\.v\d+)?)",
            re.I,
        ),
        "Figshare",
        "figshare",
        "dataset",
        lambda match: f"FIGSHARE:{match.group(1).upper()}",
    ),
    (
        re.compile(
            r"(?:https?://doi\.org/)?(10\.5061/dryad\.[A-Z0-9._-]+)",
            re.I,
        ),
        "Dryad",
        "dryad",
        "dataset",
        lambda match: f"DRYAD:{match.group(1).upper()}",
    ),
    (
        re.compile(r"(?:https?://doi\.org/)?10\.17632/([A-Z0-9]+\.\d+)", re.I),
        "MendeleyData",
        "mendeley_data",
        "dataset",
        lambda match: f"MENDELEY:{match.group(1).upper()}",
    ),
    (
        re.compile(
            r"(?:persistentId=(?:doi:)?|https?://doi\.org/)?"
            r"(10\.7910/DVN/[A-Z0-9._-]+)",
            re.I,
        ),
        "Dataverse",
        "dataverse",
        "dataset",
        lambda match: f"DATAVERSE:{match.group(1).upper()}",
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


def extract_accessions_from_links(links: list[str] | tuple[str, ...]) -> list[dict[str, str]]:
    """Return ordered unique identifiers found in curated repository links."""

    results: list[dict[str, str]] = []
    indexes: dict[str, int] = {}
    for raw_link in links:
        link = str(raw_link or "").strip()
        if not link:
            continue
        candidates = []
        for pattern, scheme, repository, object_type, accession_factory in _LINK_PATTERNS:
            match = pattern.search(link)
            if match is None:
                continue
            candidates.append(
                {
                    "accession": accession_factory(match),
                    "datalink_id_scheme": scheme,
                    "datalink_category": scheme,
                    "repository": repository,
                    "object_type": object_type,
                    "datalink_url": link,
                }
            )
        candidates.extend(
            {**candidate, "datalink_url": link}
            for candidate in extract_accessions_from_text(link)
        )
        for candidate in candidates:
            key = candidate["accession"].upper()
            if key in indexes:
                if not results[indexes[key]].get("datalink_url"):
                    results[indexes[key]]["datalink_url"] = link
                continue
            indexes[key] = len(results)
            results.append(candidate)
    return results
