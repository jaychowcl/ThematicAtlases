from __future__ import annotations

from collections.abc import Mapping
from importlib import resources
import json
from pathlib import Path
import re
from copy import deepcopy


DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", flags=re.IGNORECASE)
DOI_PREFIX = re.compile(
    r"^(?:doi\s*:\s*|https?://(?:dx\.)?doi\.org/)",
    flags=re.IGNORECASE,
)
PMID_PREFIX = re.compile(r"^pmid\s*:\s*", flags=re.IGNORECASE)

POST_FILTER_LIMITATION = (
    "This is a post-filter artifact; publications removed by review filtering "
    "may be indistinguishable from publications that were never discovered."
)
UNKNOWN_STAGE_LIMITATION = (
    "The source stage is unknown; publications removed by review filtering may "
    "be indistinguishable from publications that were never discovered."
)

REFERENCE_SET_FILES = {
    "leonie_2026_fibrosis": "leonie_2026_fibrosis.json",
    "taylor_2020_nafld_fibrosis": "taylor_2020_nafld_fibrosis.json",
}


class ThematicReviewerBenchmark:
    """Measure publication discovery and review recall for a named reference set."""

    def benchmark_reference_publication_recall(
        self,
        *,
        reference_set: str | None = None,
        reference_set_file: str | Path | None = None,
        thematic_output: Mapping[str, object] | str | Path,
    ) -> dict:
        if (reference_set is None) == (reference_set_file is None):
            raise ValueError(
                "exactly one of reference_set or reference_set_file is required"
            )
        reference_data = (
            self._load_reference_set(reference_set)
            if reference_set is not None
            else self._load_reference_set_file(reference_set_file)
        )
        reference_publications = reference_data["reference_publications"]
        references = self._reference_groups(reference_publications)
        output, source = self._load_thematic_output(thematic_output)
        reviewed_publications = self._reviewed_publication_groups(output)
        rows = self._match_rows(references, reviewed_publications)
        return {
            "schema_version": "1.1",
            "benchmark": {
                "method": "reference_publication_recall",
                "reference_set": {
                    "id": reference_data["id"],
                    "name": reference_data["name"],
                    "description": reference_data["description"],
                    "source": reference_data["source"],
                    "publication_count": len(reference_publications),
                },
            },
            "source": source,
            "summary": self._summary(
                input_count=len(reference_publications),
                rows=rows,
            ),
            "publications": rows,
        }

    @staticmethod
    def available_reference_sets() -> tuple[str, ...]:
        return tuple(REFERENCE_SET_FILES)

    def load_reference_set(self, reference_set: str) -> dict:
        """Return a validated copy of one packaged reference set."""
        return deepcopy(self._load_reference_set(reference_set))

    @classmethod
    def _load_reference_set(cls, reference_set: str) -> dict:
        filename = REFERENCE_SET_FILES.get(reference_set)
        if filename is None:
            available = ", ".join(sorted(REFERENCE_SET_FILES))
            raise ValueError(
                f"unknown reference set {reference_set!r}; available: {available}"
            )
        data_file = resources.files(
            "benchmark_ThematicAtlases.thematic_reviewer"
        ).joinpath("data", filename)
        with data_file.open(encoding="utf-8") as handle:
            reference_data = json.load(handle)
        return cls._validate_reference_set(
            reference_data,
            label=f"packaged reference set {reference_set!r}",
            expected_id=reference_set,
        )

    @classmethod
    def _load_reference_set_file(cls, path: str | Path) -> dict:
        path = Path(path)
        with path.open(encoding="utf-8") as handle:
            reference_data = json.load(handle)
        return cls._validate_reference_set(
            reference_data,
            label=f"reference set file {str(path)!r}",
        )

    @staticmethod
    def _validate_reference_set(
        reference_data,
        *,
        label: str,
        expected_id: str | None = None,
    ) -> dict:
        required = {
            "schema_version",
            "id",
            "name",
            "description",
            "source",
            "reference_publications",
        }
        if (
            not isinstance(reference_data, dict)
            or not required <= reference_data.keys()
            or not isinstance(reference_data.get("id"), str)
            or not reference_data["id"].strip()
            or not isinstance(reference_data.get("name"), str)
            or not isinstance(reference_data.get("description"), str)
            or not isinstance(reference_data.get("source"), Mapping)
            or not isinstance(reference_data.get("reference_publications"), list)
            or not reference_data["reference_publications"]
            or (expected_id is not None and reference_data.get("id") != expected_id)
        ):
            raise ValueError(f"invalid reference set: {label}")
        return reference_data

    def _reference_groups(
        self,
        reference_publications: list[Mapping[str, object]],
    ) -> list[dict]:
        if not isinstance(reference_publications, list):
            raise TypeError("reference_publications must be a list of dictionaries")
        if not reference_publications:
            raise ValueError("reference_publications must not be empty")

        items = []
        for index, reference in enumerate(reference_publications):
            if not isinstance(reference, Mapping):
                raise TypeError(
                    f"reference publication at index {index} must be a dictionary"
                )
            doi = self._normalize_reference_doi(reference.get("doi"), index=index)
            pmid = self._normalize_reference_pmid(reference.get("pmid"), index=index)
            if not doi and not pmid:
                raise ValueError(
                    f"reference publication at index {index} requires a DOI or PMID"
                )
            items.append(
                {
                    "index": index,
                    "reference": self._json_value(dict(reference)),
                    "doi": doi,
                    "pmid": pmid,
                }
            )

        identity_keys = []
        for item in items:
            keys = []
            if item["doi"]:
                keys.append(("doi", item["doi"]))
            if item["pmid"]:
                keys.append(("pmid", item["pmid"]))
            identity_keys.append(keys)
        grouped_indices = self._connected_groups(identity_keys)
        groups = []
        for indices in grouped_indices:
            group_items = [items[index] for index in indices]
            groups.append(
                {
                    "reference_indices": [item["index"] for item in group_items],
                    "references": [item["reference"] for item in group_items],
                    "dois": sorted(
                        {item["doi"] for item in group_items if item["doi"]}
                    ),
                    "pmids": sorted(
                        {item["pmid"] for item in group_items if item["pmid"]},
                        key=int,
                    ),
                }
            )
        return groups

    def _reviewed_publication_groups(self, output: dict) -> list[dict]:
        publication_texts = output["publication_texts"]
        occurrences = []

        for accession in output["accessions"]:
            if not isinstance(accession, Mapping):
                continue
            accession_id = str(accession.get("datalink_id", "") or "").strip()
            publications = accession.get("publications", [])
            if not isinstance(publications, list):
                continue
            for publication in publications:
                if not isinstance(publication, Mapping):
                    continue
                doi = self._safe_doi(publication.get("doi"))
                pmid = self._safe_pmid(publication.get("pmid"))
                publication_ref = str(
                    publication.get("publication_text_ref", "") or ""
                ).strip()
                if not doi and not pmid and not publication_ref:
                    continue
                occurrences.append(
                    {
                        "doi": doi,
                        "pmid": pmid,
                        "publication_ref": publication_ref,
                        "title": str(publication.get("title", "") or "").strip(),
                        "accession_id": accession_id,
                    }
                )

        identity_keys = []
        for item in occurrences:
            keys = []
            if item["doi"]:
                keys.append(("doi", item["doi"]))
            if item["pmid"]:
                keys.append(("pmid", item["pmid"]))
            if item["publication_ref"]:
                keys.append(("publication_ref", item["publication_ref"]))
            identity_keys.append(keys)

        groups = []
        for indices in self._connected_groups(identity_keys):
            items = [occurrences[index] for index in indices]
            publication_refs = sorted(
                {item["publication_ref"] for item in items if item["publication_ref"]}
            )
            groups.append(
                {
                    "dois": sorted({item["doi"] for item in items if item["doi"]}),
                    "pmids": sorted(
                        {item["pmid"] for item in items if item["pmid"]}, key=int
                    ),
                    "publication_text_refs": publication_refs,
                    "titles": sorted({item["title"] for item in items if item["title"]}),
                    "accession_ids": sorted(
                        {
                            item["accession_id"]
                            for item in items
                            if item["accession_id"]
                        }
                    ),
                    "review": self._review_outcome(
                        publication_refs=publication_refs,
                        publication_texts=publication_texts,
                    ),
                }
            )
        return groups

    def _match_rows(
        self,
        references: list[dict],
        reviewed_publications: list[dict],
    ) -> list[dict]:
        doi_index: dict[str, set[int]] = {}
        pmid_index: dict[str, set[int]] = {}
        for index, publication in enumerate(reviewed_publications):
            for doi in publication["dois"]:
                doi_index.setdefault(doi, set()).add(index)
            for pmid in publication["pmids"]:
                pmid_index.setdefault(pmid, set()).add(index)

        rows = []
        for reference in references:
            doi_matches = (
                set().union(*(doi_index.get(doi, set()) for doi in reference["dois"]))
                if reference["dois"]
                else set()
            )
            pmid_matches = (
                set().union(
                    *(pmid_index.get(pmid, set()) for pmid in reference["pmids"])
                )
                if reference["pmids"]
                else set()
            )
            candidates = doi_matches | pmid_matches
            matched_by = [
                identifier
                for identifier, matches in (
                    ("doi", doi_matches),
                    ("pmid", pmid_matches),
                )
                if matches
            ]

            row = {
                "reference_indices": reference["reference_indices"],
                "references": reference["references"],
                "normalized_identifiers": {
                    "dois": reference["dois"],
                    "pmids": reference["pmids"],
                },
                "matched_by": matched_by,
                "matched_publication": None,
                "conflicting_publications": [],
                "review": None,
            }
            if not candidates:
                row["status"] = "missed"
            elif len(candidates) > 1:
                row["status"] = "conflict"
                row["conflicting_publications"] = [
                    self._publication_result(reviewed_publications[index])
                    for index in sorted(candidates)
                ]
            else:
                row["status"] = "matched"
                publication = reviewed_publications[next(iter(candidates))]
                row["matched_publication"] = self._publication_result(publication)
                row["review"] = publication["review"]
            rows.append(row)
        return rows

    def _summary(self, input_count: int, rows: list[dict]) -> dict:
        total = len(rows)
        matched = [row for row in rows if row["status"] == "matched"]
        judgement_counts = {
            "relevant": 0,
            "unsure": 0,
            "not_relevant": 0,
            "other": 0,
        }
        completed = 0
        failed = 0
        unreviewed = 0
        for row in matched:
            review = row["review"]
            if review["status"] == "completed":
                completed += 1
                judgement_counts[review["judgement"]] += 1
            elif review["status"] == "failed":
                failed += 1
            else:
                unreviewed += 1

        relevant = judgement_counts["relevant"]
        candidates = relevant + judgement_counts["unsure"]
        return {
            "input_record_count": input_count,
            "reference_publication_count": total,
            "duplicate_record_count": input_count - total,
            "matched_count": len(matched),
            "missed_count": sum(row["status"] == "missed" for row in rows),
            "conflict_count": sum(row["status"] == "conflict" for row in rows),
            "discovery_recall": len(matched) / total,
            "review_completed_count": completed,
            "review_failed_count": failed,
            "unreviewed_count": unreviewed,
            "judgement_counts": judgement_counts,
            "relevant_recall": relevant / total,
            "candidate_recall": candidates / total,
        }

    def _load_thematic_output(
        self,
        thematic_output: Mapping[str, object] | str | Path,
    ) -> tuple[dict, dict]:
        if isinstance(thematic_output, Mapping):
            output = dict(thematic_output)
            source = self._source(
                kind="object", artifact=None, view="unknown", complete=None
            )
        elif isinstance(thematic_output, (str, Path)):
            path = Path(thematic_output)
            if path.is_dir():
                path, view, complete = self._trace_artifact(path)
                source = self._source(
                    kind="dev_trace",
                    artifact=str(path),
                    view=view,
                    complete=complete,
                )
            else:
                view = self._artifact_view(path.name)
                output_complete = (
                    True
                    if path.name
                    in {"02_reviewed_datasets.json", "06_final_atlas.json"}
                    else None
                )
                source = self._source(
                    kind="json",
                    artifact=str(path),
                    view=view,
                    complete=output_complete,
                )
            with open(path, encoding="utf-8") as handle:
                output = json.load(handle)
        else:
            raise TypeError(
                "thematic_output must be an atlas dictionary, JSON path, or trace directory"
            )

        if (
            not isinstance(output, dict)
            or not isinstance(output.get("accessions"), list)
            or not isinstance(output.get("publication_texts"), Mapping)
        ):
            raise ValueError(
                "thematic output must contain list 'accessions' and object 'publication_texts'"
            )
        return output, source

    def _trace_artifact(self, directory: Path) -> tuple[Path, str, bool]:
        candidates = (
            ("resume_review_progress.json", "pre_filter"),
            ("02_reviewed_datasets.json", "post_filter"),
            ("06_final_atlas.json", "post_filter"),
        )
        for name, view in candidates:
            path = directory / name
            if path.is_file():
                complete = (
                    (directory / "02_reviewed_datasets.json").is_file()
                    or (directory / "06_final_atlas.json").is_file()
                    if name == "resume_review_progress.json"
                    else True
                )
                return path, view, complete
        raise FileNotFoundError(
            f"No supported thematic review artifact found under {directory}"
        )

    @staticmethod
    def _artifact_view(name: str) -> str:
        if name == "resume_review_progress.json":
            return "pre_filter"
        if name in {"02_reviewed_datasets.json", "06_final_atlas.json"}:
            return "post_filter"
        return "unknown"

    @staticmethod
    def _source(
        kind: str,
        artifact: str | None,
        view: str,
        complete: bool | None,
    ) -> dict:
        limitations = []
        if view == "post_filter":
            limitations.append(POST_FILTER_LIMITATION)
        elif view == "unknown":
            limitations.append(UNKNOWN_STAGE_LIMITATION)
        return {
            "kind": kind,
            "artifact": artifact,
            "view": view,
            "complete": complete,
            "limitations": limitations,
        }

    def _review_outcome(
        self,
        publication_refs: list[str],
        publication_texts: Mapping[str, object],
    ) -> dict:
        judgements = set()
        failed = False
        for publication_ref in publication_refs:
            publication_text = publication_texts.get(publication_ref)
            if not isinstance(publication_text, Mapping):
                continue
            review = publication_text.get("agentic_curator")
            if not isinstance(review, Mapping):
                continue
            if review.get("review_status") == "failed":
                failed = True
                continue
            judgement = self._normalize_judgement(review.get("judgement"))
            if judgement:
                judgements.add(judgement)

        if judgements:
            judgement = next(iter(judgements)) if len(judgements) == 1 else "other"
            return {"status": "completed", "judgement": judgement}
        if failed:
            return {"status": "failed", "judgement": None}
        return {"status": "unreviewed", "judgement": None}

    @staticmethod
    def _normalize_judgement(value) -> str:
        judgement = " ".join(str(value or "").lower().replace("_", " ").split())
        if not judgement:
            return ""
        if judgement == "not relevant":
            return "not_relevant"
        if judgement in {"relevant", "unsure"}:
            return judgement
        return "other"

    @staticmethod
    def _publication_result(publication: dict) -> dict:
        return {
            "dois": publication["dois"],
            "pmids": publication["pmids"],
            "publication_text_refs": publication["publication_text_refs"],
            "titles": publication["titles"],
            "accession_ids": publication["accession_ids"],
        }

    def _normalize_reference_doi(self, value, *, index: int) -> str:
        if value is None or str(value).strip() == "":
            return ""
        try:
            return self._normalize_doi(value)
        except ValueError as error:
            raise ValueError(
                f"invalid DOI at reference index {index}: {value!r}"
            ) from error

    def _normalize_reference_pmid(self, value, *, index: int) -> str:
        if value is None or str(value).strip() == "":
            return ""
        try:
            return self._normalize_pmid(value)
        except ValueError as error:
            raise ValueError(
                f"invalid PMID at reference index {index}: {value!r}"
            ) from error

    def _safe_doi(self, value) -> str:
        try:
            return self._normalize_doi(value)
        except ValueError:
            return ""

    def _safe_pmid(self, value) -> str:
        try:
            return self._normalize_pmid(value)
        except ValueError:
            return ""

    @staticmethod
    def _normalize_doi(value) -> str:
        doi = DOI_PREFIX.sub("", str(value or "").strip()).strip()
        doi = doi.rstrip(".,;").lower()
        if not DOI_PATTERN.fullmatch(doi):
            raise ValueError("invalid DOI")
        return doi

    @staticmethod
    def _normalize_pmid(value) -> str:
        if isinstance(value, bool):
            raise ValueError("invalid PMID")
        pmid = PMID_PREFIX.sub("", str(value or "").strip()).strip()
        if not pmid.isdecimal() or int(pmid) < 1:
            raise ValueError("invalid PMID")
        return str(int(pmid))

    @staticmethod
    def _connected_groups(
        identity_keys: list[list[tuple[str, str]]],
    ) -> list[list[int]]:
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

    @staticmethod
    def _json_value(value):
        return json.loads(json.dumps(value, default=repr))
