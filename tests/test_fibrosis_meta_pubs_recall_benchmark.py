from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


pytestmark = pytest.mark.allow_subprocess


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = (
    ROOT
    / "src"
    / "benchmark_ThematicAtlases"
    / "benchmark_fibrosis_meta_pubs_recall"
)
RUNNER = BENCHMARK_DIR / "benchmark_fibrosis_meta_pubs_recall.py"
REFERENCES = BENCHMARK_DIR / "fibrosis_meta_publications.tsv"
REPORT_NAME = "fibrosis_meta_pubs_recall_report.json"

TSV_COLUMNS = (
    "reference_set_id",
    "source_reference_number",
    "doi",
    "pmid",
    "title",
)

JAIMES_CAMPOS_PUBLICATIONS = (
    (
        "10.1101/2025.10.07.25337472",
        "",
        "Pan-fibrotic gene expression signature in major chronic diseases by "
        "integrative bulk and single-cell transcriptomic analyses",
    ),
    (
        "10.1016/j.ygeno.2014.12.002",
        "25528681",
        "RNA-Seq identifies novel myocardial gene expression signatures of heart "
        "failure",
    ),
    (
        "10.1073/pnas.1401724111",
        "25012294",
        "Comparative RNA-sequencing analysis of myocardial and circulating small "
        "RNAs in human heart failure and their utility as biomarkers",
    ),
    (
        "10.1371/journal.pone.0079792",
        "24339868",
        "Differential gene expression of cardiac ion channels in human dilated "
        "cardiomyopathy",
    ),
    (
        "10.2337/db11-0952",
        "22427379",
        "MicroRNA dysregulation in diabetic ischemic heart failure patients",
    ),
    (
        "10.1097/CCM.0000000000002207",
        "28067713",
        "Widespread Down-Regulation of Cardiac Mitochondrial and Sarcomeric Genes "
        "in Patients With Sepsis",
    ),
    (
        "10.1016/j.ygeno.2016.07.001",
        "27417303",
        "Methylome analysis reveals alterations in DNA methylation in the "
        "regulatory regions of left ventricle development genes in human dilated "
        "cardiomyopathy",
    ),
    (
        "10.1136/annrheumdis-2017-212935",
        "29724730",
        "Metabolic pathways and immunometabolism in rare kidney diseases",
    ),
    (
        "10.1016/j.kint.2018.06.031",
        "30301568",
        "Hydroxypropyl-β-cyclodextrin protects from kidney disease in experimental "
        "Alport syndrome and focal segmental glomerulosclerosis",
    ),
    (
        "10.1073/pnas.2019633118",
        "33888584",
        "Chitinase 3-like 1 is a profibrogenic factor overexpressed in the aging "
        "liver and in patients with liver cirrhosis",
    ),
    (
        "10.1016/j.jhep.2021.05.014",
        "34052252",
        "Co-expression gene network analysis reveals novel regulatory pathways "
        "involved in porto-sinusoidal vascular disease",
    ),
    (
        "10.1053/j.gastro.2017.10.048",
        "29158192",
        "Combination of Gene Expression Signature and Model for End-Stage Liver "
        "Disease Score Predicts Survival of Patients With Severe Alcoholic "
        "Hepatitis",
    ),
    (
        "10.1002/hep.29606",
        "29059470",
        "Barrier to autointegration factor 1, procollagen-lysine, 2-oxoglutarate "
        "5-dioxygenase 3, and splicing factor 3b subunit 4 as early-stage cancer "
        "decision markers and drivers of hepatocellular carcinoma",
    ),
    (
        "10.1016/j.jhep.2021.04.049",
        "33992698",
        "Molecular characterisation of hepatocellular carcinoma in patients with "
        "non-alcoholic steatohepatitis",
    ),
    (
        "10.1126/scitranslmed.abo4474",
        "35731891",
        "Molecular signatures of long-term hepatocellular carcinoma risk in "
        "nonalcoholic fatty liver disease",
    ),
    (
        "10.1038/s41598-021-96966-5",
        "34508113",
        "Molecular characterization and cell type composition deconvolution of "
        "fibrosis in NAFLD",
    ),
    (
        "10.1002/hep4.1854",
        "34792289",
        "Single-Cell, Single-Nucleus, and Spatial RNA Sequencing of the Human "
        "Liver Identifies Cholangiocyte and Mesenchymal Heterogeneity",
    ),
    (
        "10.1038/s41586-024-07465-2",
        "38778114",
        "Acquisition of epithelial plasticity in human chronic liver disease",
    ),
    (
        "10.1038/s41467-024-55325-4",
        "39747812",
        "Spatial transcriptomics of healthy and fibrotic human liver at "
        "single-cell resolution",
    ),
    (
        "10.1016/j.jhep.2024.10.044",
        "39522884",
        "Multi-modal analysis of human hepatic stellate cells identifies novel "
        "therapeutic targets for metabolic dysfunction-associated steatotic liver "
        "disease",
    ),
)


def load_runner():
    spec = importlib.util.spec_from_file_location("fibrosis_benchmark_runner", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_tsv(
    path: Path,
    rows: list[dict[str, object]],
    *,
    columns: tuple[str, ...] = TSV_COLUMNS,
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=columns,
            delimiter="\t",
            quotechar=None,
            quoting=csv.QUOTE_NONE,
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            complete = {column: "" for column in columns}
            complete.update(row)
            writer.writerow(complete)


def reference_row(
    *,
    reference_set_id: str,
    doi: str = "",
    pmid: str = "",
    reference_number: object = 1,
) -> dict[str, object]:
    return {
        "reference_set_id": reference_set_id,
        "source_reference_number": reference_number,
        "doi": doi,
        "pmid": pmid,
        "title": f"Publication {doi or pmid}",
    }


def thematic_output() -> dict:
    return {
        "accessions": [
            {
                "datalink_id": "GSE1",
                "publications": [
                    {
                        "doi": "10.1000/matched",
                        "pmid": "123",
                        "title": "Matched publication",
                        "publication_text_ref": "pub-1",
                    }
                ],
            },
            {
                "datalink_id": "GSE2",
                "publications": [
                    {
                        "doi": "DOI: 10.1000/MATCHED",
                        "pmid": "PMID: 123",
                        "title": "Matched publication",
                        "publication_text_ref": "pub-1",
                    }
                ],
            },
        ],
        "publication_texts": {
            "pub-1": {"agentic_curator": {"judgement": "Relevant"}}
        },
    }


def write_trace(directory: Path, *, filename: str = "resume_review_progress.json") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    artifact = directory / filename
    artifact.write_text(json.dumps(thematic_output()), encoding="utf-8")
    return artifact


def test_runner_and_packaged_tsv_replace_old_layout() -> None:
    assert RUNNER.is_file()
    assert REFERENCES.is_file()
    assert not (
        ROOT
        / "src"
        / "benchmark_ThematicAtlases"
        / "thematic_reviewer"
        / "__init__.py"
    ).exists()


def test_packaged_jaimes_campos_reference_set_is_complete_and_validated() -> None:
    with REFERENCES.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        assert tuple(reader.fieldnames or ()) == TSV_COLUMNS
        rows = list(reader)

    set_id = "jaimes_campos_2025_fibrosis"
    jaimes_rows = [row for row in rows if row["reference_set_id"] == set_id]

    assert len(rows) == 92
    assert all(row["source_reference_number"] == "" for row in jaimes_rows)
    assert tuple(
        (row["doi"], row["pmid"], row["title"]) for row in jaimes_rows
    ) == JAIMES_CAMPOS_PUBLICATIONS
    assert "campos_2025_organs&diseases_fibrosis" not in {
        row["reference_set_id"] for row in rows
    }

    doi_set_memberships = {
        doi: {
            row["reference_set_id"]
            for row in rows
            if row["doi"].lower() == doi
        }
        for doi in {row["doi"].lower() for row in rows if row["doi"]}
    }
    assert {
        doi: set_ids
        for doi, set_ids in doi_set_memberships.items()
        if len(set_ids) > 1
    } == {
        "10.1038/s41586-024-07465-2": {
            "leonie_2026_fibrosis",
            set_id,
        },
        "10.1038/s41467-024-55325-4": {
            "leonie_2026_fibrosis",
            set_id,
        },
    }


def test_runner_builds_aggregate_and_per_set_report(tmp_path: Path) -> None:
    runner = load_runner()
    references = tmp_path / "references.tsv"
    write_tsv(
        references,
        [
            reference_row(
                reference_set_id="set-a",
                doi="https://doi.org/10.1000/MATCHED",
            ),
            reference_row(reference_set_id="set-a", pmid="999", reference_number=2),
            reference_row(reference_set_id="set-b", doi="10.1000/matched"),
        ],
    )
    trace = tmp_path / "trace"
    artifact = write_trace(trace)

    report = runner.run_benchmark(trace_dir=trace, references_tsv=references)

    assert report["schema_version"] == "1.0"
    assert report["benchmark"]["method"] == "fibrosis_meta_publication_recall"
    assert report["benchmark"]["references"]["format"] == "tsv"
    assert report["benchmark"]["references"]["artifact"] == str(references)
    assert report["source"] == {
        "kind": "dev_trace",
        "artifact": str(artifact),
        "view": "pre_filter",
        "complete": False,
        "limitations": [],
    }
    assert report["aggregate"]["summary"] == {
        "input_record_count": 3,
        "reference_publication_count": 2,
        "duplicate_record_count": 1,
        "matched_count": 1,
        "missed_count": 1,
        "conflict_count": 0,
        "discovery_recall": 0.5,
        "review_completed_count": 1,
        "review_failed_count": 0,
        "unreviewed_count": 0,
        "judgement_counts": {
            "relevant": 1,
            "unsure": 0,
            "not_relevant": 0,
            "other": 0,
        },
        "relevant_recall": 0.5,
        "candidate_recall": 0.5,
    }
    assert [item["id"] for item in report["reference_sets"]] == ["set-a", "set-b"]
    assert set(report["reference_sets"][0]) == {"id", "summary", "publications"}
    assert report["reference_sets"][0]["summary"]["matched_count"] == 1
    assert report["reference_sets"][0]["summary"]["missed_count"] == 1
    assert report["reference_sets"][1]["summary"]["matched_count"] == 1
    assert report["aggregate"]["publications"][0]["matched_publication"][
        "accession_ids"
    ] == ["GSE1", "GSE2"]


def test_trace_prefers_pre_filter_and_marks_complete_when_later_artifact_exists(
    tmp_path: Path,
) -> None:
    runner = load_runner()
    references = tmp_path / "references.tsv"
    write_tsv(
        references,
        [reference_row(reference_set_id="set-a", doi="10.1000/matched")],
    )
    trace = tmp_path / "trace"
    progress = write_trace(trace)
    (trace / "02_reviewed_datasets.json").write_text(
        json.dumps({"accessions": [], "publication_texts": {}}),
        encoding="utf-8",
    )

    report = runner.run_benchmark(trace_dir=trace, references_tsv=references)

    assert report["source"]["artifact"] == str(progress)
    assert report["source"]["view"] == "pre_filter"
    assert report["source"]["complete"] is True
    assert report["aggregate"]["summary"]["matched_count"] == 1


def test_post_filter_trace_reports_discovery_limitation(tmp_path: Path) -> None:
    runner = load_runner()
    references = tmp_path / "references.tsv"
    write_tsv(
        references,
        [reference_row(reference_set_id="set-a", doi="10.1000/matched")],
    )
    trace = tmp_path / "trace"
    write_trace(trace, filename="06_final_atlas.json")

    report = runner.run_benchmark(trace_dir=trace, references_tsv=references)

    assert report["source"]["view"] == "post_filter"
    assert report["source"]["complete"] is True
    assert report["source"]["limitations"]


def test_report_preserves_conflicts_and_all_review_states(tmp_path: Path) -> None:
    runner = load_runner()
    references = tmp_path / "references.tsv"
    write_tsv(
        references,
        [
            {
                **reference_row(reference_set_id="set-a", doi="10.1000/conflict"),
                "pmid": "222",
            },
            reference_row(reference_set_id="set-a", pmid="3", reference_number=2),
            reference_row(reference_set_id="set-a", pmid="4", reference_number=3),
            reference_row(reference_set_id="set-a", pmid="5", reference_number=4),
            reference_row(reference_set_id="set-a", pmid="6", reference_number=5),
        ],
    )
    output = {
        "accessions": [
            {
                "datalink_id": "GSE1",
                "publications": [
                    {"doi": "10.1000/conflict", "publication_text_ref": "doi"},
                    {"pmid": "222", "publication_text_ref": "pmid"},
                    {"pmid": "3", "publication_text_ref": "failed"},
                    {"pmid": "4", "publication_text_ref": "unreviewed"},
                    {"pmid": "5", "publication_text_ref": "other"},
                    {"pmid": "6", "publication_text_ref": "unsure"},
                ],
            }
        ],
        "publication_texts": {
            "doi": {"agentic_curator": {"judgement": "relevant"}},
            "pmid": {"agentic_curator": {"judgement": "relevant"}},
            "failed": {"agentic_curator": {"review_status": "failed"}},
            "unreviewed": {},
            "other": {"agentic_curator": {"judgement": "possibly relevant"}},
            "unsure": {"agentic_curator": {"judgement": "UNSURE"}},
        },
    }
    trace = tmp_path / "trace"
    trace.mkdir()
    (trace / "resume_review_progress.json").write_text(
        json.dumps(output), encoding="utf-8"
    )

    report = runner.run_benchmark(trace_dir=trace, references_tsv=references)
    summary = report["aggregate"]["summary"]

    assert summary["conflict_count"] == 1
    assert summary["matched_count"] == 4
    assert summary["review_failed_count"] == 1
    assert summary["unreviewed_count"] == 1
    assert summary["judgement_counts"] == {
        "relevant": 0,
        "unsure": 1,
        "not_relevant": 0,
        "other": 1,
    }
    assert report["aggregate"]["publications"][0]["status"] == "conflict"
    assert len(
        report["aggregate"]["publications"][0]["conflicting_publications"]
    ) == 2


def test_cli_uses_bundled_tsv_and_default_benchmarks_directory(
    tmp_path: Path,
) -> None:
    trace = tmp_path / "trace"
    write_trace(trace)

    completed = subprocess.run(
        [sys.executable, str(RUNNER), str(trace)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    report_path = tmp_path / "benchmarks" / REPORT_NAME
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == str(report_path)
    assert completed.stderr == ""
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["benchmark"]["references"]["artifact"] == str(REFERENCES)


def test_cli_replaces_report_and_supports_custom_output_directory(
    tmp_path: Path,
) -> None:
    trace = tmp_path / "trace"
    write_trace(trace)
    out = tmp_path / "custom-output"
    out.mkdir()
    report_path = out / REPORT_NAME
    report_path.write_text('{"stale": true}', encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(RUNNER), str(trace), "--out", str(out)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(report_path.read_text(encoding="utf-8"))["schema_version"] == "1.0"


@pytest.mark.parametrize(
    "rows, message",
    [
        ([], "must contain at least one publication"),
        ([reference_row(reference_set_id="set-a")], "requires a DOI or PMID"),
        (
            [reference_row(reference_set_id="set-a", doi="not-a-doi")],
            "invalid DOI",
        ),
        (
            [
                {
                    **reference_row(reference_set_id="set-a", pmid="1"),
                    "title": 'Quoted "title"',
                }
            ],
            "must not contain double quotes",
        ),
    ],
)
def test_invalid_reference_tsv_fails_without_partial_report(
    tmp_path: Path,
    rows: list[dict[str, object]],
    message: str,
) -> None:
    references = tmp_path / "references.tsv"
    write_tsv(references, rows)
    trace = tmp_path / "trace"
    write_trace(trace)
    out = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            str(trace),
            "--references",
            str(references),
            "--out",
            str(out),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert message in completed.stderr
    assert completed.stdout == ""
    assert not (out / REPORT_NAME).exists()


def test_tsv_rejects_unexpected_header(tmp_path: Path) -> None:
    runner = load_runner()
    references = tmp_path / "references.tsv"
    row = reference_row(reference_set_id="set-a", pmid="1")
    row["unexpected"] = "value"
    write_tsv(references, [row], columns=TSV_COLUMNS + ("unexpected",))

    with pytest.raises(ValueError, match="unexpected columns"):
        runner.run_benchmark(
            trace_dir=write_trace(tmp_path / "trace"),
            references_tsv=references,
        )


def test_tsv_rejects_missing_required_header(tmp_path: Path) -> None:
    runner = load_runner()
    references = tmp_path / "references.tsv"
    references.write_text(
        "reference_set_id\tdoi\nset-a\t10.1000/test\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="missing required columns"):
        runner.run_benchmark(
            trace_dir=write_trace(tmp_path / "trace"),
            references_tsv=references,
        )


def test_missing_supported_trace_artifact_fails_without_report(tmp_path: Path) -> None:
    references = tmp_path / "references.tsv"
    write_tsv(
        references,
        [reference_row(reference_set_id="set-a", pmid="1")],
    )
    trace = tmp_path / "trace"
    trace.mkdir()

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            str(trace),
            "--references",
            str(references),
            "--out",
            str(tmp_path / "out"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "No supported thematic review artifact" in completed.stderr
    assert not (tmp_path / "out" / REPORT_NAME).exists()
