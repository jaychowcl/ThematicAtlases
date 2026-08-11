from __future__ import annotations

import csv
import io
from pathlib import Path
import re


TSV_COLUMNS = (
    "reference_set_id",
    "source_reference_number",
    "doi",
    "pmid",
    "title",
)

DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", flags=re.IGNORECASE)
DOI_PREFIX = re.compile(
    r"^(?:doi\s*:\s*|https?://(?:dx\.)?doi\.org/)", flags=re.IGNORECASE
)
PMID_PREFIX = re.compile(r"^pmid\s*:\s*", flags=re.IGNORECASE)


def load_reference_tsv(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    if '"' in text:
        raise ValueError("reference TSV must not contain double quotes")
    reader = csv.DictReader(
        io.StringIO(text, newline=""),
        delimiter="\t",
        quoting=csv.QUOTE_NONE,
    )
    fieldnames = tuple(reader.fieldnames or ())
    missing = [column for column in TSV_COLUMNS if column not in fieldnames]
    if missing:
        raise ValueError(
            "reference TSV is missing required columns: " + ", ".join(missing)
        )
    unexpected = [column for column in fieldnames if column not in TSV_COLUMNS]
    if unexpected:
        raise ValueError(
            "reference TSV has unexpected columns: " + ", ".join(unexpected)
        )
    if fieldnames != TSV_COLUMNS:
        raise ValueError("reference TSV columns are not in the required order")
    raw_rows = [dict(row) for row in reader]

    if not raw_rows:
        raise ValueError("reference TSV must contain at least one publication")

    rows = []
    set_ids: dict[str, None] = {}
    for index, raw in enumerate(raw_rows, start=2):
        if raw.get(None):
            raise ValueError(f"reference TSV row {index} has unexpected fields")
        row = {
            column: str(raw.get(column, "") or "").strip()
            for column in TSV_COLUMNS
        }
        set_id = row["reference_set_id"]
        if not set_id:
            raise ValueError(f"reference TSV row {index} requires reference_set_id")
        if not row["title"]:
            raise ValueError(f"reference TSV row {index} requires title")
        set_ids.setdefault(set_id, None)

        doi = normalize_reference_doi(row["doi"], row=index)
        pmid = normalize_reference_pmid(row["pmid"], row=index)
        if not doi and not pmid:
            raise ValueError(f"reference TSV row {index} requires a DOI or PMID")
        rows.append(
            {
                "reference_set_id": set_id,
                "source_reference_number": optional_integer(
                    row["source_reference_number"],
                    label=f"source_reference_number in row {index}",
                ),
                "doi": doi,
                "pmid": pmid,
                "title": row["title"],
            }
        )
    return {"rows": rows, "set_ids": tuple(set_ids)}


def optional_integer(value: str, *, label: str) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{label} must be an integer") from error


def reference_groups(reference_publications: list[dict]) -> list[dict]:
    identity_keys = []
    for reference in reference_publications:
        keys = []
        if reference["doi"]:
            keys.append(("doi", reference["doi"]))
        if reference["pmid"]:
            keys.append(("pmid", reference["pmid"]))
        identity_keys.append(keys)

    groups = []
    for indices in connected_groups(identity_keys):
        items = [reference_publications[index] for index in indices]
        groups.append(
            {
                "reference_indices": indices,
                "references": items,
                "dois": sorted({item["doi"] for item in items if item["doi"]}),
                "pmids": sorted(
                    {item["pmid"] for item in items if item["pmid"]}, key=int
                ),
            }
        )
    return groups


def normalize_reference_doi(value: object, *, row: int) -> str:
    if not str(value or "").strip():
        return ""
    try:
        return normalize_doi(value)
    except ValueError as error:
        raise ValueError(f"invalid DOI in reference TSV row {row}: {value!r}") from error


def normalize_reference_pmid(value: object, *, row: int) -> str:
    if not str(value or "").strip():
        return ""
    try:
        return normalize_pmid(value)
    except ValueError as error:
        raise ValueError(f"invalid PMID in reference TSV row {row}: {value!r}") from error


def safe_doi(value: object) -> str:
    try:
        return normalize_doi(value)
    except ValueError:
        return ""


def safe_pmid(value: object) -> str:
    try:
        return normalize_pmid(value)
    except ValueError:
        return ""


def normalize_doi(value: object) -> str:
    doi = DOI_PREFIX.sub("", str(value or "").strip()).strip()
    doi = doi.rstrip(".,;").lower()
    if not DOI_PATTERN.fullmatch(doi):
        raise ValueError("invalid DOI")
    return doi


def normalize_pmid(value: object) -> str:
    if isinstance(value, bool):
        raise ValueError("invalid PMID")
    pmid = PMID_PREFIX.sub("", str(value or "").strip()).strip()
    if not pmid.isdecimal() or int(pmid) < 1:
        raise ValueError("invalid PMID")
    return str(int(pmid))


def connected_groups(identity_keys: list[list[tuple[str, str]]]) -> list[list[int]]:
    parents = list(range(len(identity_keys)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    owners = {}
    for index, keys in enumerate(identity_keys):
        for key in keys:
            if key in owners:
                union(index, owners[key])
            else:
                owners[key] = index
    groups: dict[int, list[int]] = {}
    for index in range(len(identity_keys)):
        groups.setdefault(find(index), []).append(index)
    return sorted(groups.values(), key=lambda indices: indices[0])
