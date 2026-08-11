from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
import os
from pathlib import Path
import sys
import tempfile

from benchmark_ThematicAtlases._fibrosis_references import (
    connected_groups as _connected_groups,
    load_reference_tsv as _load_reference_tsv,
    reference_groups as _reference_groups,
    safe_doi as _safe_doi,
    safe_pmid as _safe_pmid,
)


REPORT_NAME = "fibrosis_meta_pubs_recall_report.json"
DEFAULT_REFERENCES = Path(__file__).with_name("fibrosis_meta_publications.tsv")
DEFAULT_OUTPUT_DIRECTORY = Path("benchmarks")

POST_FILTER_LIMITATION = (
    "This is a post-filter artifact; publications removed by review filtering "
    "may be indistinguishable from publications that were never discovered."
)


def run_benchmark(*, trace_dir: str | Path, references_tsv: str | Path) -> dict:
    """Compare one TA trace with fibrosis meta-publication TSV references."""
    reference_data = _load_reference_tsv(Path(references_tsv))
    output, source = _load_trace(Path(trace_dir))
    reviewed_publications = _reviewed_publication_groups(output)

    aggregate_rows = _match_rows(
        _reference_groups(reference_data["rows"]), reviewed_publications
    )
    reference_sets = []
    for set_id in reference_data["set_ids"]:
        set_rows = [
            row for row in reference_data["rows"] if row["reference_set_id"] == set_id
        ]
        matched_rows = _match_rows(
            _reference_groups(set_rows), reviewed_publications
        )
        reference_sets.append(
            {
                "id": set_id,
                "summary": _summary(len(set_rows), matched_rows),
                "publications": matched_rows,
            }
        )

    return {
        "schema_version": "1.0",
        "benchmark": {
            "method": "fibrosis_meta_publication_recall",
            "references": {
                "format": "tsv",
                "artifact": str(Path(references_tsv)),
                "input_record_count": len(reference_data["rows"]),
                "reference_set_count": len(reference_data["set_ids"]),
            },
        },
        "source": source,
        "aggregate": {
            "summary": _summary(len(reference_data["rows"]), aggregate_rows),
            "publications": aggregate_rows,
        },
        "reference_sets": reference_sets,
    }


def _load_trace(directory: Path) -> tuple[dict, dict]:
    if not directory.is_dir():
        raise ValueError(f"trace directory does not exist or is not a directory: {directory}")
    artifact, view, complete = _trace_artifact(directory)
    with artifact.open(encoding="utf-8") as handle:
        output = json.load(handle)
    if (
        not isinstance(output, dict)
        or not isinstance(output.get("accessions"), list)
        or not isinstance(output.get("publication_texts"), Mapping)
    ):
        raise ValueError(
            "thematic output must contain list 'accessions' and object 'publication_texts'"
        )
    limitations = [POST_FILTER_LIMITATION] if view == "post_filter" else []
    return output, {
        "kind": "dev_trace",
        "artifact": str(artifact),
        "view": view,
        "complete": complete,
        "limitations": limitations,
    }


def _trace_artifact(directory: Path) -> tuple[Path, str, bool]:
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


def _reviewed_publication_groups(output: dict) -> list[dict]:
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
            doi = _safe_doi(publication.get("doi"))
            pmid = _safe_pmid(publication.get("pmid"))
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
    for indices in _connected_groups(identity_keys):
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
                    {item["accession_id"] for item in items if item["accession_id"]}
                ),
                "review": _review_outcome(publication_refs, publication_texts),
            }
        )
    return groups


def _match_rows(references: list[dict], reviewed_publications: list[dict]) -> list[dict]:
    doi_index: dict[str, set[int]] = {}
    pmid_index: dict[str, set[int]] = {}
    for index, publication in enumerate(reviewed_publications):
        for doi in publication["dois"]:
            doi_index.setdefault(doi, set()).add(index)
        for pmid in publication["pmids"]:
            pmid_index.setdefault(pmid, set()).add(index)

    rows = []
    for reference in references:
        doi_matches = set().union(
            *(doi_index.get(doi, set()) for doi in reference["dois"])
        ) if reference["dois"] else set()
        pmid_matches = set().union(
            *(pmid_index.get(pmid, set()) for pmid in reference["pmids"])
        ) if reference["pmids"] else set()
        candidates = doi_matches | pmid_matches
        row = {
            "reference_indices": reference["reference_indices"],
            "references": reference["references"],
            "normalized_identifiers": {
                "dois": reference["dois"],
                "pmids": reference["pmids"],
            },
            "matched_by": [
                identifier
                for identifier, matches in (("doi", doi_matches), ("pmid", pmid_matches))
                if matches
            ],
            "matched_publication": None,
            "conflicting_publications": [],
            "review": None,
        }
        if not candidates:
            row["status"] = "missed"
        elif len(candidates) > 1:
            row["status"] = "conflict"
            row["conflicting_publications"] = [
                _publication_result(reviewed_publications[index])
                for index in sorted(candidates)
            ]
        else:
            row["status"] = "matched"
            publication = reviewed_publications[next(iter(candidates))]
            row["matched_publication"] = _publication_result(publication)
            row["review"] = publication["review"]
        rows.append(row)
    return rows


def _summary(input_count: int, rows: list[dict]) -> dict:
    total = len(rows)
    matched = [row for row in rows if row["status"] == "matched"]
    judgement_counts = {
        "relevant": 0,
        "unsure": 0,
        "not_relevant": 0,
        "other": 0,
    }
    completed = failed = unreviewed = 0
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


def _review_outcome(
    publication_refs: list[str], publication_texts: Mapping[str, object]
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
        judgement = _normalize_judgement(review.get("judgement"))
        if judgement:
            judgements.add(judgement)
    if judgements:
        judgement = next(iter(judgements)) if len(judgements) == 1 else "other"
        return {"status": "completed", "judgement": judgement}
    if failed:
        return {"status": "failed", "judgement": None}
    return {"status": "unreviewed", "judgement": None}


def _normalize_judgement(value: object) -> str:
    judgement = " ".join(str(value or "").lower().replace("_", " ").split())
    if not judgement:
        return ""
    if judgement == "not relevant":
        return "not_relevant"
    if judgement in {"relevant", "unsure"}:
        return judgement
    return "other"


def _publication_result(publication: dict) -> dict:
    return {
        "dois": publication["dois"],
        "pmids": publication["pmids"],
        "publication_text_refs": publication["publication_text_refs"],
        "titles": publication["titles"],
        "accession_ids": publication["accession_ids"],
    }


def _write_report(report: dict, output_directory: Path) -> Path:
    output_directory.mkdir(parents=True, exist_ok=True)
    report_path = output_directory / REPORT_NAME
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=output_directory,
            prefix=f".{REPORT_NAME}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(report, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, report_path)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    return report_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark fibrosis meta-publication recall from a TA trace."
    )
    parser.add_argument("trace_dir", type=Path)
    parser.add_argument("--references", type=Path, default=DEFAULT_REFERENCES)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        report = run_benchmark(
            trace_dir=args.trace_dir,
            references_tsv=args.references,
        )
        report_path = _write_report(report, args.out.resolve())
    except (OSError, TypeError, ValueError) as error:
        print(f"benchmark failed: {error}", file=sys.stderr)
        return 1
    print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
